from __future__ import annotations

import os
import re
from contextlib import contextmanager
from typing import Any

from backend.config import Settings

try:
    import langsmith as ls
    from langsmith import traceable
except Exception:  # pragma: no cover
    ls = None

    def traceable(*args, **kwargs):  # type: ignore[override]
        def decorator(fn):
            return fn

        return decorator


EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
BEARER_RE = re.compile(r"\b(sk|sess|api)[-_][A-Za-z0-9_-]{8,}\b", re.IGNORECASE)


def _redact_text(value: str) -> str:
    value = EMAIL_RE.sub("[redacted-email]", value)
    value = BEARER_RE.sub("[redacted-secret]", value)
    return value


def redact_payload(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, dict):
        return {k: redact_payload(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_payload(v) for v in value]
    if isinstance(value, tuple):
        return tuple(redact_payload(v) for v in value)
    return value


def configure_langsmith(settings: Settings) -> bool:
    if not settings.langsmith_api_key:
        return False
    os.environ.setdefault("LANGSMITH_API_KEY", settings.langsmith_api_key)
    os.environ.setdefault("LANGSMITH_ENDPOINT", settings.langsmith_endpoint)
    os.environ.setdefault("LANGSMITH_PROJECT", settings.langsmith_project)
    os.environ.setdefault("LANGSMITH_TRACING", "true")
    if settings.langsmith_workspace_id:
        os.environ.setdefault("LANGSMITH_WORKSPACE_ID", settings.langsmith_workspace_id)
    os.environ.setdefault("LANGSMITH_HIDE_INPUTS", "true" if settings.langsmith_mask_inputs else "false")
    os.environ.setdefault("LANGSMITH_HIDE_OUTPUTS", "true" if settings.langsmith_mask_outputs else "false")
    return True


@contextmanager
def tracing_session(
    *,
    settings: Settings,
    enabled: bool,
    run_name: str,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
):
    configured = configure_langsmith(settings)
    if not enabled or not configured or ls is None:
        yield {"enabled": False, "project": settings.langsmith_project}
        return

    clean_metadata = redact_payload(metadata or {}) if settings.langsmith_mask_inputs else (metadata or {})
    clean_tags = list(dict.fromkeys([*settings.langsmith_tags, *(tags or [])]))

    with ls.tracing_context(
        enabled=True,
        project_name=settings.langsmith_project,
        tags=clean_tags,
        metadata={"run_name": run_name, **clean_metadata},
    ):
        yield {
            "enabled": True,
            "project": settings.langsmith_project,
            "tags": clean_tags,
            "metadata": clean_metadata,
        }
