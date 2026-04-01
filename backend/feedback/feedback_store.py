from __future__ import annotations

from typing import Any

from backend.config import Settings


def save_feedback(
    *,
    settings: Settings,
    question: str,
    answer: str,
    helpful: bool,
    correction: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    from backend import feedback_store as phase1_feedback_store

    phase1_feedback_store.save_feedback(
        question=question,
        mode=(meta or {}).get("mode") or "unknown",
        rating=1 if helpful else 0,
        model=((meta or {}).get("debug") or {}).get("model") or "demo",
        sql=(meta or {}).get("sql"),
        answer=answer,
        corrected_answer=correction or None,
        comment=None,
    )
