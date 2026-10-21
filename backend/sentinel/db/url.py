"""Normalize DB URLs for async SQLAlchemy (Railway / Heroku / local)."""

from __future__ import annotations

import os


def resolve_database_url() -> str:
    raw = (
        os.environ.get("DATABASE_URL")
        or os.environ.get("POSTGRES_URL")
        or os.environ.get("POSTGRESQL_URL")
        or ""
    ).strip()
    if not raw or raw.startswith("driver://"):
        raise RuntimeError(
            "DATABASE_URL is missing. "
            "On Railway: add Postgres → Variables → Variable Reference → "
            "Postgres.DATABASE_URL (or paste the connection URL)."
        )
    return normalize_database_url(raw)


def normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://") and "+asyncpg" not in url:
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
    # asyncpg does not accept sslmode= in URL the same way; strip common sync params
    for junk in ("?sslmode=require", "&sslmode=require", "?sslmode=prefer", "&sslmode=prefer"):
        if junk in url:
            url = url.replace(junk, "")
    if url.endswith("?"):
        url = url[:-1]
    return url
