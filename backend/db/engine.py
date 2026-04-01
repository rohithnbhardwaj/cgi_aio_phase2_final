from __future__ import annotations

from functools import lru_cache

from backend.config import Settings


@lru_cache(maxsize=8)
def _build_engine(database_url: str):
    from sqlalchemy import create_engine

    return create_engine(database_url, pool_pre_ping=True, future=True)


def get_engine(settings: Settings):
    return _build_engine(settings.database_url)
