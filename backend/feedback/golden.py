from __future__ import annotations

from typing import Any

from backend.config import Settings


def lookup_golden_sql(question: str, *, settings: Settings) -> dict[str, Any] | None:
    try:
        from backend import feedback_store as phase1_feedback_store

        hit = phase1_feedback_store.find_best_golden_sql(
            question,
            min_similarity=float(settings.golden_match_min_score),
        )
    except Exception:
        hit = None

    if not hit:
        return None

    sql, debug = hit
    return {
        "matched": True,
        "score": debug.get("golden_score") or debug.get("golden_similarity") or 0.0,
        "sql": sql,
        "answer": "",
        "metadata": debug,
        "debug": debug,
    }
