"""SQLAlchemy engine/session for the local SQLite database.

Swap the URL for a Postgres DSN to upgrade; models are backend-agnostic.
For encryption at rest, keep data/ on a FileVault volume or use a SQLCipher driver.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.settings import get_settings

_settings = get_settings()
_engine = create_engine(
    _settings.db_url,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False},
)
_SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, class_=Session)


# New columns added to pre-existing tables. create_all() creates missing TABLES but
# never ALTERs an existing one, so additive columns need a tiny idempotent migration.
# (table, column, DDL type) — safe to run every startup; already-present columns skip.
_ADDED_COLUMNS = [
    ("content_opportunities", "norm_key", "VARCHAR(120)"),
    ("content_opportunities", "status", "VARCHAR(16) DEFAULT 'open'"),
    ("content_opportunities", "answer_piece_id", "INTEGER"),
]


def _ensure_columns() -> None:
    from sqlalchemy import inspect, text

    insp = inspect(_engine)
    existing_tables = set(insp.get_table_names())
    with _engine.begin() as conn:
        for table, column, ddl in _ADDED_COLUMNS:
            if table not in existing_tables:
                continue  # create_all just made it fresh, with the column already
            cols = {c["name"] for c in insp.get_columns(table)}
            if column not in cols:
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {ddl}'))


def init_db() -> None:
    """Create tables if they don't exist, then apply additive column migrations."""
    from app.db.models import Base  # local import to avoid cycles

    Base.metadata.create_all(_engine)
    _ensure_columns()


@contextmanager
def get_session() -> Iterator[Session]:
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
