from __future__ import annotations

import re

SQL_COMMAND_PATTERNS = [
    re.compile(r"\bdrop\s+(table|database|schema|view|index)?\b", re.IGNORECASE),
    re.compile(r"\btruncate\s+table\b", re.IGNORECASE),
    re.compile(r"\bdelete\s+from\b", re.IGNORECASE),
    re.compile(r"\binsert\s+into\b", re.IGNORECASE),
    re.compile(r"\bupdate\s+\w+\s+set\b", re.IGNORECASE),
    re.compile(r"\balter\s+(table|database|schema|view|index)\b", re.IGNORECASE),
    re.compile(r"\bgrant\b", re.IGNORECASE),
    re.compile(r"\brevoke\b", re.IGNORECASE),
    re.compile(r"\bcreate\s+(table|database|schema|view|index)\b", re.IGNORECASE),
    re.compile(r"\bremove\s+(the\s+)?database\b", re.IGNORECASE),
]

SQL_COMMENT_RE = re.compile(r"(--.*?$)|(/\*.*?\*/)", re.MULTILINE | re.DOTALL)
FORBIDDEN_SQL_RE = re.compile(
    r"\b(delete\s+from|drop\s+table|drop\s+database|truncate\s+table|insert\s+into|"
    r"update\s+\w+\s+set|alter\s+table|grant\b|revoke\b|create\s+(table|database|schema|view|index))\b",
    re.IGNORECASE,
)
STARTS_SELECT_RE = re.compile(r"^(select|with)\b", re.IGNORECASE | re.DOTALL)
HAS_LIMIT_RE = re.compile(r"\blimit\s+\d+\b", re.IGNORECASE)
HAS_FETCH_RE = re.compile(r"\bfetch\s+first\s+\d+\s+rows\s+only\b", re.IGNORECASE)


def is_destructive_intent(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return False

    lowered = value.lower()
    if any(token in lowered for token in ["policy", "procedure", "guideline", "rule", "manual"]):
        return False

    return any(pattern.search(value) for pattern in SQL_COMMAND_PATTERNS)


def strip_sql_comments(sql: str) -> str:
    return SQL_COMMENT_RE.sub(" ", sql or "")


def normalize_sql(sql: str) -> str:
    cleaned = strip_sql_comments(sql)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if cleaned.endswith(";"):
        cleaned = cleaned[:-1].strip()
    return cleaned


def assert_select_only_sql(sql: str) -> str:
    cleaned = normalize_sql(sql)
    if not cleaned:
        raise ValueError("SQL is empty.")
    if ";" in cleaned:
        raise ValueError("Multiple statements are not allowed.")
    if FORBIDDEN_SQL_RE.search(cleaned):
        raise ValueError("Only SELECT-only SQL is allowed.")
    if not STARTS_SELECT_RE.match(cleaned):
        raise ValueError("Query must begin with SELECT or WITH.")
    return cleaned


def is_select_only_sql(sql: str) -> bool:
    try:
        assert_select_only_sql(sql)
        return True
    except ValueError:
        return False


def ensure_limit(sql: str, limit: int) -> str:
    cleaned = assert_select_only_sql(sql)
    if HAS_LIMIT_RE.search(cleaned) or HAS_FETCH_RE.search(cleaned):
        return cleaned
    return f"{cleaned} LIMIT {int(limit)}"
