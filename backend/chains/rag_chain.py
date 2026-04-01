from __future__ import annotations

from backend.config import Settings
from backend.models import AnswerResult
from backend.observability.langsmith import traceable


@traceable(name="rag_answer", run_type="chain")
def answer_with_rag(question: str, *, settings: Settings) -> dict:
    if not settings.rag_enabled:
        return AnswerResult(mode="rag", answer="Document search is disabled.", debug={"reason": "rag_disabled"}).to_dict()

    try:
        from backend import rag

        result = rag.answer(question, k=settings.rag_top_k)
        result.setdefault("mode", "rag")
        result.setdefault("sql", "")
        result.setdefault("rows", [])
        result.setdefault("columns", [])
        result.setdefault("debug", {}).update({"retriever": "phase1_rag_wrapper"})
        return result
    except Exception as exc:
        return AnswerResult(
            mode="rag",
            answer="I could not retrieve supporting document passages.",
            debug={"reason": "rag_error", "error": str(exc)},
        ).to_dict()
