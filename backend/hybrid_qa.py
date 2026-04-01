# backend/hybrid_qa.py
from __future__ import annotations

"""
Hybrid QA router (Policy/RAG → Destructive Guard → Golden SQL → NL2SQL → RAG fallback)

Order:
1) Policy questions → RAG (if available)
2) Destructive intent guard (blocks DELETE/DROP/etc.)
3) Golden SQL match (Chroma similarity)
4) NL→SQL via LLM (OpenAI / Ollama / heuristic fallback)
5) RAG fallback (if available)

Return shape:
{
  "mode": "sql"|"rag"|"none"|"error",
  "sql": <sql or "">,
  "rows": <list[dict]>,
  "columns": <list[str]>,
  "answer": <string>,
  "sources": <list>,
  "debug": <dict>
}
"""

import os
import re
import logging
from typing import Any, Dict

from backend import nl_to_sql

logger = logging.getLogger(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

try:
    from backend.feedback_store import find_best_golden_sql
except Exception:
    find_best_golden_sql = None  # type: ignore

try:
    from backend.rag import answer as rag_answer  # type: ignore
except Exception:
    rag_answer = None  # type: ignore

def _is_db_unavailable_error(e: Exception) -> bool:
    msg = str(e).lower()
    return any(
        s in msg
        for s in [
            "could not translate host name",          # docker dns missing when container stopped
            "temporary failure in name resolution",
            "could not connect to server",
            "connection refused",
            "timeout expired",
            "server closed the connection unexpectedly",
        ]
    )
def _db_down_response(*, debug: dict, sql: str = "") -> dict:
    return {
        "mode": "sql",
        "sql": sql or "",
        "rows": [],
        "columns": [],
        "answer": (
            "The database is currently unavailable (the `db` service appears to be stopped). "
            "Please start it and try again:\n\n"
            "`docker compose start db`"
        ),
        "sources": [],
        "debug": {"reason": "db_unavailable", **(debug or {})},
    }


def _looks_like_policy_question(q: str) -> bool:
    ql = (q or "").lower()
    return any(
        k in ql
        for k in [

            # Documentation / KB style questions
            "documentation",
            "docs",
            "guide",
            "kb",
            "knowledge base",

            # Tooling docs (Atlassian suite)
            "bamboo",
            "atlassian",
            "jira",
            "confluence",
            "bitbucket",

            # Common terms inside Bamboo guides (helps route doc sections like "Configure your Node.js project")
            "node.js",
            "nodejs",
            "npm",
            "pipeline",
            "build plan",
            "deployment",
            "agent",
            "policy",
            "pto",
            "benefit",
            "holiday",
            "vpn",
            "onboarding",
            "hr",
            "security",
            "manual",
            "remote work",
            "password",  # optional: route password reset to RAG faster
        ]
    )



def _is_constant_select(sql: str) -> bool:
    """Detect constant SELECT statements like: SELECT '...' AS message LIMIT 50."""
    sl = (sql or "").lower()
    return sl.strip().startswith("select") and (" from " not in sl)


def _sql_is_placeholder_answer(sql: str, rows: list, cols: list) -> bool:
    """Detect when NL2SQL answers by selecting a constant string instead of querying tables."""
    if not rows or not cols:
        return False
    if not _is_constant_select(sql):
        return False

    # Any constant SELECT is suspicious; single-cell "schema not available" messages are very common.
    if len(rows) != 1 or len(cols) != 1:
        return True

    v = rows[0].get(cols[0])
    if not isinstance(v, str):
        return True

    vl = v.lower()
    return any(
        p in vl
        for p in [
            "not available in the provided schema",
            "not available in the schema",
            "no data available",
            "i don't have access",
        ]
    )


# Word-boundary regex prevents false positives like "created_at" matching "create"
_DESTRUCTIVE_RE = re.compile(
    r"\b(delete|drop|truncate|wipe|purge|remove|update|insert|alter|create|grant|revoke|replace)\b",
    re.IGNORECASE,
)


def _looks_like_destructive_intent(q: str) -> bool:
    """
    Question-level guard to prevent destructive DB actions.
    Uses word boundaries to avoid false positives like created_at / updated_at.
    """
    ql = (q or "").lower()

    # Allow procedural/policy questions like: "What is the policy to delete an account?"
    if any(k in ql for k in ["policy", "procedure", "guideline", "rule", "hr manual"]):
        return False

    return _DESTRUCTIVE_RE.search(ql) is not None


def answer_question(question: str) -> Dict[str, Any]:
    question = (question or "").strip()
    if not question:
        return {
            "mode": "none",
            "answer": "Please enter a question.",
            "sql": "",
            "rows": [],
            "columns": [],
            "sources": [],
            "debug": {"reason": "empty_question"},
        }

    debug: Dict[str, Any] = {}

    # 1) Policy → RAG first
    if _looks_like_policy_question(question) and rag_answer is not None:
        rag = rag_answer(question)
        rag.setdefault("mode", "rag")
        rag.setdefault("sql", "")
        rag.setdefault("rows", [])
        rag.setdefault("columns", [])
        ql = question.lower()
        docish = any(k in ql for k in [
            "bamboo", "atlassian", "jira", "confluence", "bitbucket",
            "documentation", "docs", "guide", "kb", "knowledge base",
            "node.js", "nodejs"
        ])
        rag.setdefault("debug", {})["reason"] = "doc_rag" if docish else "policy_rag"
        return rag

    # 2) Destructive intent guard (MUST be BEFORE golden lookup / NL→SQL)
    if _looks_like_destructive_intent(question):
        return {
            "mode": "sql",
            "sql": "",
            "rows": [],
            "columns": [],
            "answer": (
                "For safety, I can’t run destructive database actions (DELETE/DROP/TRUNCATE/etc.). "
                "I can help with read-only questions like:\n"
                "- “Show all users”\n"
                "- “How many users are there?”\n"
                "- “List user emails”"
            ),
            "sources": [],
            "debug": {"reason": "blocked_destructive_intent"},
        }

    schema_context = None
    try:
        schema_context = nl_to_sql.fetch_schema_context()
    except Exception as e:
        logger.warning("Failed to fetch schema context: %s", e)

    # 3) Golden query lookup
    if find_best_golden_sql is not None:
        hit = find_best_golden_sql(question)
        if hit:
            sql, gdbg = hit
            debug.update(gdbg)
            try:
                sql_norm = nl_to_sql.validate_and_normalize_sql(sql)
                rows, cols = nl_to_sql.execute_sql(sql_norm)

                # If Golden SQL returns nothing and this looks like a docs/policy question, try RAG.
                if rag_answer is not None and len(rows) == 0 and _looks_like_policy_question(question):
                    rag = rag_answer(question)
                    rag.setdefault("mode", "rag")
                    rag.setdefault("sql", "")
                    rag.setdefault("rows", [])
                    rag.setdefault("columns", [])
                    rag.setdefault("debug", {})["reason"] = "rag_after_golden_empty"
                    rag["debug"].update(debug)
                    return rag

                return {
                    "mode": "sql",
                    "sql": sql_norm,
                    "rows": rows,
                    "columns": cols,
                    "answer": f"Returned {len(rows)} row(s).",
                    "sources": [],
                    "debug": {"reason": "golden_sql_success", **debug, "sql_provider": "golden"},
                }
            except Exception as e:
                debug["golden_sql_error"] = str(e)
                if _is_db_unavailable_error(e):
                    return _db_down_response(debug={"sql_provider": "golden", **debug}, sql=sql_norm)

    # 4) NL→SQL generation + execute
    try:
        sql, sdbg = nl_to_sql.generate_sql(question, schema_context=schema_context)
        debug.update(sdbg)
        sql_norm = nl_to_sql.validate_and_normalize_sql(sql)
        rows, cols = nl_to_sql.execute_sql(sql_norm)

        # If NL2SQL produced a constant SELECT (no FROM) or returned empty rows,
        # try RAG so uploaded docs (e.g., Bamboo guides) can answer.
        if rag_answer is not None:
            if _sql_is_placeholder_answer(sql_norm, rows, cols):
                rag = rag_answer(question)
                rag.setdefault("mode", "rag")
                rag.setdefault("sql", "")
                rag.setdefault("rows", [])
                rag.setdefault("columns", [])
                rag.setdefault("debug", {})["reason"] = "rag_after_sql_placeholder"
                rag["debug"].update(debug)
                return rag

            if len(rows) == 0 and _looks_like_policy_question(question):
                rag = rag_answer(question)
                rag.setdefault("mode", "rag")
                rag.setdefault("sql", "")
                rag.setdefault("rows", [])
                rag.setdefault("columns", [])
                rag.setdefault("debug", {})["reason"] = "rag_after_sql_empty"
                rag["debug"].update(debug)
                return rag
        return {
            "mode": "sql",
            "sql": sql_norm,
            "rows": rows,
            "columns": cols,
            "answer": f"Returned {len(rows)} row(s).",
            "sources": [],
            "debug": {"reason": "sql_success", **debug},
        }
    except Exception as e:
        debug["sql_error"] = str(e)
        if _is_db_unavailable_error(e):
            return _db_down_response(debug={"sql_provider": debug.get("sql_provider", "unknown"), **debug})


    # 5) RAG fallback
    if rag_answer is not None:
        try:
            rag = rag_answer(question)
            rag.setdefault("mode", "rag")
            rag.setdefault("sql", "")
            rag.setdefault("rows", [])
            rag.setdefault("columns", [])
            rag.setdefault("debug", {})["reason"] = "rag_fallback"
            rag["debug"].update(debug)
            return rag
        except Exception as e:
            debug["rag_error"] = str(e)

    return {
        "mode": "sql",
        "sql": "",
        "rows": [],
        "columns": [],
        "answer": f"SQL failed and RAG is unavailable. Error: {debug.get('sql_error')}",
        "sources": [],
        "debug": {"reason": "sql_failed_no_rag", **debug},
    }