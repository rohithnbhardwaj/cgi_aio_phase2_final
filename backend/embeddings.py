# backend/embeddings.py
from __future__ import annotations

import os
import hashlib
import logging
from typing import List, Optional

log = logging.getLogger(__name__)

# Must match your schema ingestion model dimensionality
DEFAULT_EMBED_DIM = int(os.getenv("EMBED_DIM", "384"))
DEFAULT_MODEL_NAME = os.getenv("EMBED_MODEL", "all-MiniLM-L6-v2")

# Optional: if you have a known local snapshot path inside container, set it
VERIFIED_MODEL_PATH = os.getenv(
    "VERIFIED_MODEL_PATH",
    "/home/streamlit/.cache/huggingface/hub/models--sentence-transformers--all-MiniLM-L6-v2/snapshots/"
    "c9745ed1d9f207416be6d2e6f8de32d1f16199bf"
)

_MODEL = None  # cached SentenceTransformer


def _deterministic_fallback_embed(text: str, dim: int = DEFAULT_EMBED_DIM) -> List[float]:
    """
    Deterministic 384-dim fallback (no ML libs needed).
    Prevents Chroma dimension mismatch if HF/Torch cache has permission issues.
    """
    if text is None:
        text = ""

    out: List[float] = []
    counter = 0
    while len(out) < dim:
        h = hashlib.blake2b((text + f"::{counter}").encode("utf-8"), digest_size=64).digest()
        # convert bytes -> floats in [-1, 1]
        for b in h:
            out.append((b / 127.5) - 1.0)
            if len(out) >= dim:
                break
        counter += 1

    return out[:dim]


def _load_sentence_transformer() -> Optional["SentenceTransformer"]:
    global _MODEL

    if _MODEL is not None:
        return _MODEL

    # Ensure caches are writable (avoid /home/streamlit/.cache/torch permission issue)
    os.environ.setdefault("XDG_CACHE_HOME", os.getenv("XDG_CACHE_HOME", "/app/hf_cache"))
    os.environ.setdefault("HF_HOME", os.getenv("HF_HOME", "/app/hf_cache"))
    os.environ.setdefault("TRANSFORMERS_CACHE", os.getenv("TRANSFORMERS_CACHE", "/app/hf_cache"))
    os.environ.setdefault("TORCH_HOME", os.getenv("TORCH_HOME", "/app/hf_cache/torch"))
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
    except Exception as e:
        log.warning("sentence-transformers not available: %s", e)
        return None

    try:
        if VERIFIED_MODEL_PATH and os.path.exists(VERIFIED_MODEL_PATH):
            log.info("Loading SentenceTransformer from local snapshot: %s", VERIFIED_MODEL_PATH)
            _MODEL = SentenceTransformer(VERIFIED_MODEL_PATH)
        else:
            log.info("Loading SentenceTransformer model by name: %s", DEFAULT_MODEL_NAME)
            _MODEL = SentenceTransformer(DEFAULT_MODEL_NAME)
        return _MODEL
    except Exception as e:
        log.warning("Failed to load SentenceTransformer (%s). Using fallback embed.", e)
        return None


def embed_text(text: str) -> List[float]:
    """
    Returns a 384-dim embedding always.
    """
    model = _load_sentence_transformer()
    if model is None:
        return _deterministic_fallback_embed(text, dim=DEFAULT_EMBED_DIM)

    try:
        vec = model.encode([text], show_progress_bar=False)[0]
        vec_list = vec.tolist() if hasattr(vec, "tolist") else list(vec)
        if len(vec_list) != DEFAULT_EMBED_DIM:
            # safety guard
            return _deterministic_fallback_embed(text, dim=DEFAULT_EMBED_DIM)
        return vec_list
    except Exception as e:
        log.warning("Embedding encode failed (%s). Using fallback.", e)
        return _deterministic_fallback_embed(text, dim=DEFAULT_EMBED_DIM)


def embed_texts(texts: List[str]) -> List[List[float]]:
    """
    Batch embedding, always returns len(texts) vectors of 384 dims each.
    """
    model = _load_sentence_transformer()
    if model is None:
        return [_deterministic_fallback_embed(t, dim=DEFAULT_EMBED_DIM) for t in texts]

    try:
        vecs = model.encode(texts, show_progress_bar=False)
        out: List[List[float]] = []
        for i, v in enumerate(vecs):
            v_list = v.tolist() if hasattr(v, "tolist") else list(v)
            if len(v_list) != DEFAULT_EMBED_DIM:
                v_list = _deterministic_fallback_embed(texts[i], dim=DEFAULT_EMBED_DIM)
            out.append(v_list)
        return out
    except Exception as e:
        log.warning("Batch embedding failed (%s). Using fallback.", e)
        return [_deterministic_fallback_embed(t, dim=DEFAULT_EMBED_DIM) for t in texts]