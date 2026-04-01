from __future__ import annotations

from typing import Any

from backend.config import Settings
from backend.guardrails.sql_guard import ensure_limit


def describe_database_schema(settings: Settings, *, max_tables: int = 20, max_columns: int = 20) -> dict[str, list[str]]:
    try:
        from backend import nl_to_sql

        summary = nl_to_sql.fetch_schema_context()
    except Exception:
        summary = ""

    if not summary:
        return {}

    parsed: dict[str, list[str]] = {}
    for line in summary.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        table_part, cols_part = line.split(":", 1)
        table = table_part.split(".")[-1].strip("- ")
        cols = []
        for raw in cols_part.split(",")[:max_columns]:
            col = raw.strip()
            if not col:
                continue
            cols.append(col.split(" ")[0])
        if table:
            parsed[table] = cols
        if len(parsed) >= max_tables:
            break
    return parsed


def schema_summary_text(settings: Settings, *, max_tables: int = 20, max_columns: int = 20) -> str:
    try:
        from backend import nl_to_sql

        return nl_to_sql.fetch_schema_context()
    except Exception:
        summary = describe_database_schema(settings, max_tables=max_tables, max_columns=max_columns)
        if not summary:
            return "No database schema information available."
        return "\n".join(f"- public.{table}: {', '.join(cols)}" for table, cols in summary.items())


def run_select(sql: str, *, settings: Settings, limit: int | None = None) -> dict[str, Any]:
    from backend import nl_to_sql

    normalized = nl_to_sql.validate_and_normalize_sql(sql)
    bounded = ensure_limit(normalized, limit or settings.sql_default_limit)
    rows, cols = nl_to_sql.execute_sql(bounded)
    return {"sql": bounded, "columns": cols, "rows": rows[: settings.max_sql_rows]}
