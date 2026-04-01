from __future__ import annotations

import re
from typing import Any

from backend.config import Settings
from backend.db.safe_exec import describe_database_schema, schema_summary_text
from backend.guardrails.sql_guard import is_select_only_sql
from backend.observability.langsmith import traceable


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", (text or "").lower()))


def _guess_table(question: str, schema: dict[str, list[str]]) -> str | None:
    q_tokens = _tokenize(question)
    best_table = None
    best_score = 0
    for table, columns in schema.items():
        score = 0
        table_tokens = _tokenize(table.replace("_", " "))
        score += len(q_tokens.intersection(table_tokens)) * 4
        for column in columns:
            if column.lower() in q_tokens:
                score += 2
        singular = table[:-1] if table.endswith("s") else table
        if singular in q_tokens:
            score += 2
        if score > best_score:
            best_score = score
            best_table = table
    return best_table


def _heuristic_sql(question: str, settings: Settings) -> dict[str, Any] | None:
    try:
        schema = describe_database_schema(settings)
    except Exception:
        schema = {}
    if not schema:
        return None

    q = (question or "").strip().lower()
    table = _guess_table(q, schema)
    if not table:
        return None
    columns = schema.get(table, [])

    if "email" in q and "email" in columns:
        return {
            "sql": f"SELECT email FROM public.{table}",
            "sql_explanation": f"Selected email values from {table}.",
            "sql_provider": "heuristic",
            "confidence": 0.86,
        }

    if ("how many" in q or "count" in q) and table:
        if "active" in q and "status" in columns:
            return {
                "sql": f"SELECT COUNT(*) AS count FROM public.{table} WHERE LOWER(status) = 'active'",
                "sql_explanation": f"Counted active rows in {table} using the status column.",
                "sql_provider": "heuristic",
                "confidence": 0.83,
            }
        return {
            "sql": f"SELECT COUNT(*) AS count FROM public.{table}",
            "sql_explanation": f"Counted rows from {table}.",
            "sql_provider": "heuristic",
            "confidence": 0.78,
        }

    if any(phrase in q for phrase in ["show", "list", "all", "display"]):
        selected_columns = columns[: min(6, len(columns))] or ["*"]
        return {
            "sql": f"SELECT {', '.join(selected_columns)} FROM public.{table}",
            "sql_explanation": f"Listed representative columns from {table}.",
            "sql_provider": "heuristic",
            "confidence": 0.72,
        }

    return None


@traceable(name="generate_sql", run_type="chain")
def generate_sql(question: str, *, settings: Settings) -> dict[str, Any]:
    heuristic = _heuristic_sql(question, settings)
    if heuristic:
        return heuristic

    try:
        from backend import nl_to_sql

        schema_text = schema_summary_text(settings)
        sql, debug = nl_to_sql.generate_sql(question, schema_context=schema_text)
        candidate_sql = (sql or "").strip()
        if candidate_sql and is_select_only_sql(candidate_sql):
            return {
                "sql": candidate_sql,
                "sql_explanation": debug.get("sql_explanation") or "",
                "sql_provider": debug.get("sql_provider") or settings.llm_provider,
                "confidence": float(debug.get("confidence") or 0.0),
            }
        return {
            "sql": "",
            "sql_explanation": debug.get("sql_explanation") or "Model did not return a safe SELECT-only query.",
            "sql_provider": debug.get("sql_provider") or settings.llm_provider,
            "confidence": float(debug.get("confidence") or 0.0),
        }
    except Exception as exc:
        return {
            "sql": "",
            "sql_explanation": f"NL to SQL generation failed: {exc}",
            "sql_provider": settings.llm_provider,
            "confidence": 0.0,
        }
