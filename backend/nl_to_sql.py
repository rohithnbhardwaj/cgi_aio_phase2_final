# backend/nl_to_sql.py
from __future__ import annotations

"""
NL → SQL module (demo-friendly, SELECT-only)

What this file does:
- Generates SAFE Postgres SELECT queries from natural language.
- Uses OpenAI (primary) or Ollama (fallback) if configured.
- Falls back to simple heuristics if LLM is unavailable.
- Executes SQL via SQLAlchemy against DATABASE_URL.

Safety guardrails:
- Only allows ONE statement starting with SELECT/WITH.
- Blocks INSERT/UPDATE/DELETE/DROP/ALTER/... (write operations).
- Enforces a LIMIT (default 50) for non-aggregate queries.

Env vars:
- DATABASE_URL (required for execution)
- LLM_PROVIDER=openai|ollama|none   (default: openai if key exists else none)
- OPENAI_API_KEY, OPENAI_MODEL (e.g., gpt-4o-mini)
- OLLAMA_BASE_URL (e.g., http://host.docker.internal:11434)
- OLLAMA_MODEL (e.g., mistral)
- SQL_DEFAULT_LIMIT (default: 50)
- SQL_MAX_LIMIT (default: 200)
"""

# backend/nl_to_sql.py

import os
import re
import logging
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

DEFAULT_LIMIT = int(os.getenv("SQL_DEFAULT_LIMIT", "50"))
MAX_ROWS_RETURNED = int(os.getenv("SQL_MAX_ROWS_RETURNED", "200"))


# -------------------------
# DB helpers
# -------------------------
@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """
    Uses DATABASE_URL if present, otherwise builds from POSTGRES_* env vars.
    """
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        user = os.getenv("POSTGRES_USER", "streamlit")
        pwd = os.getenv("POSTGRES_PASSWORD", "streamlit_pass")
        host = os.getenv("POSTGRES_HOST", "db")
        port = os.getenv("POSTGRES_PORT", "5432")
        db = os.getenv("POSTGRES_DB", "streamlitdb")
        db_url = f"postgresql+psycopg2://{user}:{pwd}@{host}:{port}/{db}"
    return create_engine(db_url, pool_pre_ping=True, future=True)


def execute_sql(sql: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Executes SQL and returns (rows, columns).
    Only intended for SELECT/WITH queries.
    """
    eng = get_engine()
    with eng.connect() as conn:
        result = conn.execute(text(sql))
        cols = list(result.keys()) if result.returns_rows else []
        rows_raw = result.fetchall() if result.returns_rows else []
        rows: List[Dict[str, Any]] = [dict(zip(cols, row)) for row in rows_raw[:MAX_ROWS_RETURNED]]
    return rows, cols


def fetch_schema_context(schema: str = "public") -> str:
    """
    Produces a compact schema summary for prompting the LLM.
    """
    q = text(
        """
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = :schema
        ORDER BY table_name, ordinal_position
        """
    )
    eng = get_engine()
    tables: Dict[str, List[str]] = {}
    with eng.connect() as conn:
        rows = conn.execute(q, {"schema": schema}).fetchall()

    for t, c, dt in rows:
        tables.setdefault(t, []).append(f"{c} ({dt})")

    lines = []
    for t in sorted(tables.keys()):
        cols = ", ".join(tables[t])
        lines.append(f"- {schema}.{t}: {cols}")
    return "\n".join(lines)


# -------------------------
# SQL safety
# -------------------------
_SQL_FORBIDDEN = re.compile(
    r"\b("
    r"insert|update|delete|drop|alter|truncate|create|grant|revoke|comment|copy|"
    r"vacuum|analyze|attach|detach|cluster|reindex|call|execute|do|"
    r"pg_sleep|pg_terminate_backend|pg_cancel_backend"
    r")\b",
    re.IGNORECASE,
)

_SQL_ALLOWED_START = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)


def _strip_code_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _single_statement(sql: str) -> str:
    sql = sql.strip()
    sql = sql[:-1] if sql.endswith(";") else sql
    if ";" in sql:
        raise ValueError("Multiple SQL statements are not allowed.")
    return sql


def _ensure_limit(sql: str, default_limit: int = DEFAULT_LIMIT) -> str:
    s = sql.strip()
    if re.search(r"\blimit\b", s, re.IGNORECASE):
        return s

    # If it's clearly an aggregate-only query, no limit needed
    if re.search(r"\bcount\s*\(", s, re.IGNORECASE) and not re.search(r"\bgroup\s+by\b", s, re.IGNORECASE):
        return s

    return f"{s} LIMIT {default_limit}"


def validate_and_normalize_sql(sql: str) -> str:
    sql = _strip_code_fences(sql)
    sql = _single_statement(sql)

    if not _SQL_ALLOWED_START.match(sql):
        raise ValueError("Only SELECT/WITH queries are allowed.")

    if _SQL_FORBIDDEN.search(sql):
        raise ValueError("Unsafe SQL detected (write/DDL/admin keyword present).")

    sql = _ensure_limit(sql, DEFAULT_LIMIT)
    return sql.strip()


# -------------------------
# LLM SQL generation
# -------------------------
def _heuristic_sql(question: str) -> Optional[Tuple[str, str]]:
    """
    Tiny fast-path heuristics (cheap + reliable for common demo prompts).
    Returns (sql, explanation) or None.
    """
    q = question.lower().strip()

    if ("user" in q or "users" in q) and "email" in q:
        return ("SELECT email FROM public.users", "Heuristic: selecting email")
    if ("user" in q or "users" in q) and ("all" in q or "show" in q or "list" in q):
        return ("SELECT * FROM public.users", "Heuristic: select rows")
    if "projects" in q and ("list" in q or "show" in q):
        return ("SELECT * FROM public.projects", "Heuristic: list projects")
    if "tasks" in q and ("list" in q or "show" in q):
        return ("SELECT * FROM public.tasks", "Heuristic: list tasks")

    return None


@lru_cache(maxsize=1)
def _openai_client():
    from openai import OpenAI  # type: ignore
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def _openai_chat_sql(question: str, schema_context: str, model: str) -> str:
    client = _openai_client()
    system = (
        "You are a senior analytics engineer. "
        "Generate ONE PostgreSQL SELECT query (or WITH ... SELECT) answering the user's question.\n"
        "Rules:\n"
        "- Output ONLY SQL (no explanation, no markdown).\n"
        "- Use only the tables/columns provided.\n"
        f"- Always include LIMIT {DEFAULT_LIMIT} unless the query is an aggregate-only COUNT.\n"
        "- Never write data (no INSERT/UPDATE/DELETE), no DDL.\n"
    )
    user = f"Schema:\n{schema_context}\n\nQuestion:\n{question}\n\nSQL:"
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0,
    )
    return resp.choices[0].message.content or ""


def _openai_responses_sql(question: str, schema_context: str, model: str) -> str:
    client = _openai_client()
    system = (
        "You are a senior analytics engineer. "
        "Generate ONE PostgreSQL SELECT query (or WITH ... SELECT) answering the user's question.\n"
        "Rules:\n"
        "- Output ONLY SQL (no explanation, no markdown).\n"
        "- Use only the tables/columns provided.\n"
        f"- Always include LIMIT {DEFAULT_LIMIT} unless the query is an aggregate-only COUNT.\n"
        "- Never write data (no INSERT/UPDATE/DELETE), no DDL.\n"
    )
    resp = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": f"Schema:\n{schema_context}\n\nQuestion:\n{question}\n\nSQL:"},
        ],
    )
    if getattr(resp, "output_text", None):
        return resp.output_text  # type: ignore
    return ""


def _ollama_sql(question: str, schema_context: str, base_url: str, model: str) -> str:
    import requests  # type: ignore

    system = (
        "You are a senior analytics engineer. "
        "Generate ONE PostgreSQL SELECT query (or WITH ... SELECT) answering the user's question.\n"
        "Rules:\n"
        "- Output ONLY SQL (no explanation, no markdown).\n"
        "- Use only the tables/columns provided.\n"
        f"- Always include LIMIT {DEFAULT_LIMIT} unless the query is an aggregate-only COUNT.\n"
        "- Never write data (no INSERT/UPDATE/DELETE), no DDL.\n"
    )
    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Schema:\n{schema_context}\n\nQuestion:\n{question}\n\nSQL:"},
        ],
    }
    r = requests.post(f"{base_url.rstrip('/')}/api/chat", json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()
    return (data.get("message") or {}).get("content") or ""


def generate_sql(question: str, schema_context: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
    """
    Returns (sql, debug).
    debug includes provider + explanation.
    """
    schema_context = schema_context or fetch_schema_context()

    # 0) heuristic fast-path
    h = _heuristic_sql(question)
    if h:
        raw_sql, expl = h
        sql = validate_and_normalize_sql(raw_sql)
        return sql, {"sql_provider": "heuristic", "sql_explanation": expl}

    provider = os.getenv("LLM_PROVIDER", "openai").lower().strip()
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    ollama_base = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
    ollama_model = os.getenv("OLLAMA_MODEL", "mistral")

    # 1) OpenAI primary
    if provider in ("openai", "auto") and openai_key:
        try:
            raw = _openai_chat_sql(question, schema_context, openai_model)
            sql = validate_and_normalize_sql(raw)
            return sql, {"sql_provider": "openai", "sql_explanation": "OpenAI generated SQL"}
        except Exception as e1:
            logger.warning("OpenAI chat SQL generation failed; trying Responses API. Error: %s", e1)
            try:
                raw = _openai_responses_sql(question, schema_context, openai_model)
                sql = validate_and_normalize_sql(raw)
                return sql, {"sql_provider": "openai", "sql_explanation": "OpenAI generated SQL (responses)"}
            except Exception as e2:
                logger.warning("OpenAI Responses SQL generation also failed: %s", e2)

    # 2) Ollama fallback
    if provider in ("ollama", "auto", "openai"):
        try:
            raw = _ollama_sql(question, schema_context, ollama_base, ollama_model)
            sql = validate_and_normalize_sql(raw)
            return sql, {"sql_provider": "ollama", "sql_explanation": f"Ollama({ollama_model}) generated SQL"}
        except Exception as e:
            logger.warning("Ollama SQL generation failed: %s", e)

    # 3) final fallback (very conservative)
    return "SELECT 1 LIMIT 1", {"sql_provider": "fallback", "sql_explanation": "Fallback: SELECT 1"}