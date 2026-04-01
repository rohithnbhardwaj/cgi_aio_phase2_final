from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


AnswerMode = Literal["none", "sql", "rag", "blocked", "error"]


class AnswerResult(BaseModel):
    mode: AnswerMode = "none"
    answer: str = ""
    sql: str = ""
    sql_explanation: str = ""
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[Any] = Field(default_factory=list)
    trace: dict[str, Any] = Field(default_factory=dict)
    debug: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()
