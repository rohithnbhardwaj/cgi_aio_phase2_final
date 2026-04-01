from __future__ import annotations

"""Primary application entrypoint.

Target state:
- LangGraph is the primary orchestrator
- legacy router remains available only as an emergency rollback path
- external contract stays stable: answer_question(question) -> structured result
"""

import os
from typing import Any, Dict

from backend.langsmith_observability import request_trace

ALLOW_LEGACY_ROLLBACK = os.getenv("ALLOW_LEGACY_ROLLBACK", "1") == "1"
LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "cgi-aio-phase2")
DEFAULT_USE_LANGGRAPH = os.getenv("USE_LANGGRAPH_DEFAULT", "1") == "1"
DEFAULT_ENABLE_LANGSMITH = os.getenv("ENABLE_LANGSMITH_DEFAULT", "0") == "1"


def _legacy_answer(question: str) -> Dict[str, Any]:
    from backend.hybrid_qa import answer_question as legacy_answer_question

    out = legacy_answer_question(question)
    out.setdefault("debug", {}).update({
        "router": "phase1_delegate",
        "router_impl": "legacy",
        "langsmith_enabled": False,
    })
    return out


def answer_question(
    question: str,
    *,
    use_langgraph: bool | None = None,
    enable_langsmith: bool | None = None,
) -> Dict[str, Any]:
    """Stable app contract used by Streamlit and tests."""
    use_langgraph = DEFAULT_USE_LANGGRAPH if use_langgraph is None else bool(use_langgraph)
    enable_langsmith = DEFAULT_ENABLE_LANGSMITH if enable_langsmith is None else bool(enable_langsmith)

    if not question or not str(question).strip():
        return {
            "mode": "none",
            "answer": "Please enter a question.",
            "sql": "",
            "rows": [],
            "columns": [],
            "sources": [],
            "debug": {"reason": "empty_question", "router_impl": "entrypoint"},
            "trace": {"enabled": enable_langsmith, "project": LANGSMITH_PROJECT},
        }

    if not use_langgraph and ALLOW_LEGACY_ROLLBACK:
        out = _legacy_answer(question)
        out["trace"] = {"enabled": enable_langsmith, "project": LANGSMITH_PROJECT}
        return out

    from backend.router_graph import get_compiled_graph

    with request_trace(
        enabled=enable_langsmith,
        project_name=LANGSMITH_PROJECT,
        tags=["cgi", "aio", "phase2", "langgraph-primary"],
        metadata={
            "use_langgraph": use_langgraph,
            "question_preview": str(question)[:120],
            "environment": os.getenv("APP_ENV", "dev"),
        },
    ):
        try:
            graph = get_compiled_graph()
            state = graph.invoke(
                {
                    "question": str(question).strip(),
                    "debug": {},
                    "enable_langsmith": enable_langsmith,
                }
            )
            out = state["final"]
            out["trace"] = {"enabled": enable_langsmith, "project": LANGSMITH_PROJECT}
            return out
        except Exception as e:
            if ALLOW_LEGACY_ROLLBACK:
                out = _legacy_answer(question)
                out.setdefault("debug", {})["langgraph_error"] = str(e)
                out["trace"] = {"enabled": enable_langsmith, "project": LANGSMITH_PROJECT}
                return out
            raise
