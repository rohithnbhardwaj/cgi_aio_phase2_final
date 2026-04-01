from __future__ import annotations

"""Feedback + golden memory store for CGI AIO.

Key fixes in this version:
- corrected SQL is always promoted under mode='sql' even if the original bad answer was RAG
- exact-question SQL promotions overwrite the canonical SQL golden row via deterministic IDs
- find_best_golden_sql only searches SQL-mode entries, so bad RAG corrections cannot shadow data prompts
- destructive/admin prompts are never promoted into the golden SQL memory
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import math
import os
import re
import uuid
from typing import Any, Dict, Iterable, List, Optional, Tuple

import chromadb

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore

try:
    from sentence_transformers import SentenceTransformer
except Exception:  # pragma: no cover
    SentenceTransformer = None  # type: ignore

CHROMA_DIR = os.getenv("CHROMA_DIR", "/app/vector_store")
FEEDBACK_COLLECTION = os.getenv("FEEDBACK_COLLECTION", "feedback_events")
GOLDEN_COLLECTION = os.getenv("GOLDEN_COLLECTION", "golden_queries")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
GOLDEN_MIN_SIM = float(os.getenv("GOLDEN_MIN_SIM", os.getenv("GOLDEN_MIN_SIMILARITY", "0.78")))

# Ranking weights are intentionally simple and stable for demo behavior.
W_SIM = 0.72
W_HELPFUL = 0.20
W_VOLUME = 0.06
W_RECENCY = 0.02

# Keep destructive/admin prompts out of golden SQL memory.
DOC_TOOLING_HINTS = {
    "bamboo", "jira", "confluence", "bitbucket", "atlassian",
    "repository", "repo", "source repository", "build plan", "pipeline",
    "deployment", "agent", "branch", "checkout", "artifact", "plan",
    "documentation", "docs", "guide", "manual", "knowledge base", "kb",
    "policy", "pto", "holiday", "vpn", "onboarding", "hr", "benefits",
}
PROCEDURAL_HINTS = {
    "how to", "how do i", "steps", "procedure", "configure", "configuration",
    "setup", "set up", "guide", "manual", "policy",
}
DESTRUCTIVE_DB_HINTS = {
    "sql", "database", "db", "table", "row", "record", "insert into",
    "delete from", "update ", "drop table", "truncate", "alter table", "create table",
}
DESTRUCTIVE_RE = re.compile(
    r"\b(delete|drop|truncate|wipe|purge|remove|update|insert|alter|create|grant|revoke|replace)\b",
    re.IGNORECASE,
)


@dataclass
class GoldenCandidate:
    gid: str
    question: str
    meta: Dict[str, Any]
    distance: float


# -------------------------
# Chroma + embeddings
# -------------------------

@lru_cache(maxsize=1)
def _client() -> chromadb.PersistentClient:
    return chromadb.PersistentClient(path=CHROMA_DIR)


@lru_cache(maxsize=8)
def _collection(name: str):
    return _client().get_or_create_collection(name, metadata={"hnsw:space": "cosine"})


@lru_cache(maxsize=1)
def _local_embedder():
    if SentenceTransformer is None:  # pragma: no cover
        raise RuntimeError("sentence-transformers is not installed and OpenAI embeddings are unavailable")
    return SentenceTransformer("all-MiniLM-L6-v2")


@lru_cache(maxsize=1)
def _openai_client() -> Optional[OpenAI]:
    if not OPENAI_API_KEY or OpenAI is None:
        return None
    return OpenAI(api_key=OPENAI_API_KEY)


def _embed_texts(texts: Iterable[str]) -> List[List[float]]:
    arr = [str(t or "").strip() for t in texts]
    if not arr:
        return []

    client = _openai_client()
    if client is not None:
        try:
            resp = client.embeddings.create(model=OPENAI_EMBED_MODEL, input=arr)
            return [list(item.embedding) for item in resp.data]
        except Exception:
            # Fall through to local embeddings for resilience in demo/dev.
            pass

    model = _local_embedder()
    embeds = model.encode(arr, normalize_embeddings=True)
    return [list(map(float, row)) for row in embeds]


# -------------------------
# Helpers
# -------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _trim(s: Optional[str], max_len: int = 12000) -> str:
    return (s or "")[:max_len]


def _norm_question(q: str) -> str:
    return re.sub(r"\s+", " ", (q or "").strip().lower())


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _deterministic_golden_id(question: str, mode: str) -> str:
    base = f"{_norm_question(question)}::{mode.strip().lower()}"
    return hashlib.md5(base.encode("utf-8")).hexdigest()


def _cosine_sim_from_distance(distance: float) -> float:
    # For Chroma cosine distance, similarity ~= 1 - distance.
    sim = 1.0 - float(distance)
    return max(0.0, min(1.0, sim))


def _recency_score(ts_iso: Optional[str]) -> float:
    if not ts_iso:
        return 0.0
    try:
        ts = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
        age_days = max(0.0, (datetime.now(timezone.utc) - ts).total_seconds() / 86400.0)
        # Decay over ~180 days.
        return 1.0 / (1.0 + age_days / 30.0)
    except Exception:
        return 0.0


def _helpful_rate(good: int, bad: int) -> float:
    total = max(1, good + bad)
    return good / total


def _volume_score(good: int, bad: int) -> float:
    return min(1.0, math.log1p(max(0, good + bad)) / math.log(11))


def _looks_like_destructive_admin_prompt(question: str) -> bool:
    q = (question or "").strip().lower()
    if not q:
        return False
    if any(k in q for k in DOC_TOOLING_HINTS):
        return False
    if any(k in q for k in PROCEDURAL_HINTS):
        return False
    if not DESTRUCTIVE_RE.search(q):
        return False
    return any(k in q for k in DESTRUCTIVE_DB_HINTS) or bool(
        re.search(r"\b(delete|drop|truncate|insert|update|alter|create)\b", q)
    )


# -------------------------
# Public API
# -------------------------

def save_feedback(
    *,
    question: str,
    mode: str,
    rating: int,
    model: Optional[str] = None,
    sql: Optional[str] = None,
    answer: Optional[str] = None,
    corrected_sql: Optional[str] = None,
    corrected_answer: Optional[str] = None,
    what_went_wrong: Optional[str] = None,
    comment: Optional[str] = None,
) -> Dict[str, Any]:
    question = (question or "").strip()
    if not question:
        raise ValueError("question is required")

    rating = 1 if int(rating) > 0 else 0
    mode = (mode or "unknown").strip().lower() or "unknown"
    corrected_sql = (corrected_sql or "").strip() or None
    corrected_answer = (corrected_answer or "").strip() or None
    final_sql = corrected_sql or (sql or None)
    final_answer = corrected_answer or (answer or None)
    promote_mode = "sql" if corrected_sql else mode
    ts = _now_iso()
    q_emb = _embed_texts([question])[0]

    event_id = uuid.uuid4().hex
    event_meta: Dict[str, Any] = {
        "ts": ts,
        "question": question,
        "question_norm": _norm_question(question),
        "mode": mode,
        "rating": rating,
        "model": model or "demo",
        "sql": _trim(sql),
        "answer": _trim(answer),
        "corrected_sql": _trim(corrected_sql),
        "corrected_answer": _trim(corrected_answer),
        "what_went_wrong": what_went_wrong or "",
        "comment": comment or "",
    }
    _collection(FEEDBACK_COLLECTION).upsert(
        ids=[event_id],
        documents=[question],
        embeddings=[q_emb],
        metadatas=[event_meta],
    )

    out = {"event_id": event_id}

    # Only promote if the prompt is safe and we have something reusable.
    if _looks_like_destructive_admin_prompt(question):
        out["promoted"] = False
        out["promotion_reason"] = "destructive_or_admin_prompt"
        return out

    if not (final_sql or final_answer or rating > 0):
        out["promoted"] = False
        out["promotion_reason"] = "no_reusable_content"
        return out

    golden_id = _deterministic_golden_id(question, promote_mode)
    coll = _collection(GOLDEN_COLLECTION)
    existing = coll.get(ids=[golden_id], include=["metadatas", "documents"])
    existing_meta = ((existing.get("metadatas") or [None])[0] or {})

    good = _safe_int(existing_meta.get("good_count"))
    bad = _safe_int(existing_meta.get("bad_count"))
    if rating > 0:
        good += 1
    else:
        bad += 1

    helpful_rate = _helpful_rate(good, bad)
    canonical_meta: Dict[str, Any] = {
        "ts": ts,
        "created_ts": existing_meta.get("created_ts") or ts,
        "mode": promote_mode,
        "model": model or "demo",
        "sql": _trim(final_sql),
        "answer": _trim(final_answer),
        "question": question,
        "question_norm": _norm_question(question),
        "good_count": good,
        "bad_count": bad,
        "helpful_rate": helpful_rate,
        "what_went_wrong": what_went_wrong or existing_meta.get("what_went_wrong", ""),
        "comment": comment or existing_meta.get("comment", ""),
        "correction_type": "sql" if corrected_sql else ("answer" if corrected_answer else existing_meta.get("correction_type", "")),
        "source": "feedback_promotion",
    }

    coll.upsert(
        ids=[golden_id],
        documents=[question],
        embeddings=[q_emb],
        metadatas=[canonical_meta],
    )

    # If a corrected SQL was supplied, proactively remove exact-question non-sql goldens
    # so they cannot shadow the data path in older retrieval code.
    if corrected_sql:
        all_rows = coll.get(include=["metadatas", "documents"])
        ids = all_rows.get("ids") or []
        docs = all_rows.get("documents") or []
        metas = all_rows.get("metadatas") or []
        to_delete: List[str] = []
        q_norm = _norm_question(question)
        for gid, doc, meta in zip(ids, docs, metas):
            meta = meta or {}
            if gid == golden_id:
                continue
            if _norm_question(doc or meta.get("question") or "") == q_norm and str(meta.get("mode") or "") != "sql":
                to_delete.append(gid)
        if to_delete:
            coll.delete(ids=to_delete)
            out["deleted_conflicts"] = to_delete

    out.update({
        "promoted": True,
        "golden_id": golden_id,
        "mode": promote_mode,
        "good_count": good,
        "bad_count": bad,
        "helpful_rate": helpful_rate,
    })
    return out


def find_best_golden_sql(question: str, min_similarity: Optional[float] = None) -> Optional[Tuple[str, Dict[str, Any]]]:
    question = (question or "").strip()
    if not question:
        return None

    threshold = GOLDEN_MIN_SIM if min_similarity is None else float(min_similarity)
    q_norm = _norm_question(question)
    coll = _collection(GOLDEN_COLLECTION)

    # 1) exact canonical lookup by deterministic SQL id
    exact_id = _deterministic_golden_id(question, "sql")
    exact = coll.get(ids=[exact_id], include=["metadatas", "documents"])
    exact_meta = ((exact.get("metadatas") or [None])[0] or {})
    if exact_meta and (exact_meta.get("sql") or "").strip():
        good = _safe_int(exact_meta.get("good_count"))
        bad = _safe_int(exact_meta.get("bad_count"))
        dbg = {
            "golden_id": exact_id,
            "golden_similarity": 1.0,
            "golden_score": 1.0,
            "golden_good_count": good,
            "golden_bad_count": bad,
            "golden_helpful_rate": _helpful_rate(good, bad),
            "golden_matched_question": (exact.get("documents") or [question])[0],
            "golden_rank_weights": {
                "w_sim": W_SIM,
                "w_helpful": W_HELPFUL,
                "w_volume": W_VOLUME,
                "w_recency": W_RECENCY,
            },
            "sql_provider": "golden",
        }
        return str(exact_meta.get("sql")), dbg

    # 2) semantic SQL-only lookup
    q_emb = _embed_texts([question])[0]
    res = coll.query(
        query_embeddings=[q_emb],
        n_results=8,
        where={"mode": "sql"},
        include=["documents", "metadatas", "distances"],
    )
    ids = (res.get("ids") or [[]])[0]
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]

    candidates: List[Tuple[float, str, Dict[str, Any], float]] = []
    for gid, doc, meta, dist in zip(ids, docs, metas, dists):
        meta = meta or {}
        sql = (meta.get("sql") or "").strip()
        if not sql:
            continue
        sim = _cosine_sim_from_distance(_safe_float(dist, 1.0))
        if sim < threshold and _norm_question(doc or "") != q_norm:
            continue
        good = _safe_int(meta.get("good_count"))
        bad = _safe_int(meta.get("bad_count"))
        helpful = _helpful_rate(good, bad)
        volume = _volume_score(good, bad)
        recency = _recency_score(meta.get("ts"))
        exact_bonus = 0.10 if _norm_question(doc or meta.get("question") or "") == q_norm else 0.0
        score = (W_SIM * sim) + (W_HELPFUL * helpful) + (W_VOLUME * volume) + (W_RECENCY * recency) + exact_bonus
        candidates.append((score, sql, {
            "golden_id": gid,
            "golden_similarity": sim,
            "golden_score": score,
            "golden_good_count": good,
            "golden_bad_count": bad,
            "golden_helpful_rate": helpful,
            "golden_matched_question": doc or meta.get("question") or question,
            "golden_rank_weights": {
                "w_sim": W_SIM,
                "w_helpful": W_HELPFUL,
                "w_volume": W_VOLUME,
                "w_recency": W_RECENCY,
            },
            "sql_provider": "golden",
        }, sim))

    if not candidates:
        return None

    candidates.sort(key=lambda t: (t[0], t[3]), reverse=True)
    _, sql, dbg, _ = candidates[0]
    return sql, dbg



def delete_golden_by_id(golden_id: str) -> Dict[str, Any]:
    """Delete a golden row by id."""
    gid = (golden_id or "").strip()
    if not gid:
        raise ValueError("golden_id is required")
    coll = _collection(GOLDEN_COLLECTION)
    coll.delete(ids=[gid])
    return {"deleted": [gid]}


def cleanup_question_goldens(
    question: str,
    *,
    preferred_sql: Optional[str] = None,
    model: Optional[str] = "cleanup_script",
) -> Dict[str, Any]:
    """Delete conflicting exact-question goldens and optionally re-upsert canonical SQL row.

    Keeps the canonical SQL row id for the exact question and removes every other exact-match row.
    If preferred_sql is supplied, the canonical SQL row is upserted with that SQL.
    """
    question = (question or "").strip()
    if not question:
        raise ValueError("question is required")

    coll = _collection(GOLDEN_COLLECTION)
    q_norm = _norm_question(question)
    canonical_sql_id = _deterministic_golden_id(question, "sql")

    rows = coll.get(include=["metadatas", "documents"])
    ids = rows.get("ids") or []
    docs = rows.get("documents") or []
    metas = rows.get("metadatas") or []

    deleted: List[str] = []
    kept: List[str] = []
    canonical_meta: Dict[str, Any] = {}

    for gid, doc, meta in zip(ids, docs, metas):
        meta = meta or {}
        doc_norm = _norm_question((doc or meta.get("question") or ""))
        if doc_norm != q_norm:
            continue

        if gid == canonical_sql_id:
            kept.append(gid)
            canonical_meta = dict(meta)
            continue

        deleted.append(gid)

    if deleted:
        coll.delete(ids=deleted)

    if preferred_sql:
        q_emb = _embed_texts([question])[0]
        ts = _now_iso()
        good = _safe_int(canonical_meta.get("good_count"))
        bad = _safe_int(canonical_meta.get("bad_count"))
        canonical_meta.update(
            {
                "ts": ts,
                "created_ts": canonical_meta.get("created_ts") or ts,
                "mode": "sql",
                "model": model or "cleanup_script",
                "sql": _trim(preferred_sql),
                "answer": _trim(canonical_meta.get("answer") or ""),
                "question": question,
                "question_norm": q_norm,
                "good_count": good,
                "bad_count": bad,
                "helpful_rate": _helpful_rate(good, bad),
                "correction_type": "sql",
                "source": "cleanup_canonical_sql",
            }
        )
        coll.upsert(
            ids=[canonical_sql_id],
            documents=[question],
            embeddings=[q_emb],
            metadatas=[canonical_meta],
        )
        kept = [canonical_sql_id]

    return {
        "question": question,
        "canonical_sql_id": canonical_sql_id,
        "deleted": deleted,
        "kept": kept,
        "sql_upserted": bool(preferred_sql),
    }
