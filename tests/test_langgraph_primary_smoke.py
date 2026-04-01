"""Minimal smoke tests for the LangGraph-primary router.

These are intentionally small parity checks. Extend them with your LangSmith eval dataset.
"""

from backend.entrypoint import answer_question


def test_empty_question_returns_none():
    out = answer_question("   ", use_langgraph=True, enable_langsmith=False)
    assert out["mode"] == "none"
    assert out["debug"]["reason"] == "empty_question"


def test_destructive_prompt_is_blocked():
    out = answer_question("Delete all users", use_langgraph=True, enable_langsmith=False)
    assert out["debug"]["reason"] == "blocked_destructive_intent"
    assert out["rows"] == []
