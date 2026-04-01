from __future__ import annotations

"""Lightweight LangSmith helpers.

This module is intentionally dependency-tolerant:
- if langsmith is installed, tracing_context and @traceable are used
- if not, all helpers gracefully become no-ops

Recommended runtime env:
  LANGSMITH_TRACING=true
  LANGSMITH_API_KEY=...
  LANGSMITH_PROJECT=cgi-aio-phase2
"""

from contextlib import contextmanager
from typing import Any, Callable, Iterator

try:  # pragma: no cover - optional dependency
    from langsmith import traceable, tracing_context  # type: ignore
except Exception:  # pragma: no cover
    def traceable(*_args: Any, **_kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def _decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            return fn
        return _decorator

    @contextmanager
    def tracing_context(**_kwargs: Any) -> Iterator[None]:
        yield


@contextmanager
def request_trace(*, enabled: bool, project_name: str, tags: list[str] | None = None, metadata: dict[str, Any] | None = None):
    """Wrap a request in an optional LangSmith trace context."""
    if not enabled:
        yield
        return

    with tracing_context(
        enabled=True,
        project_name=project_name,
        tags=tags or [],
        metadata=metadata or {},
    ):
        yield
