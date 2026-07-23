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


def init_db() -> None:
    """Create tables if they don't exist."""
    from app.db.models import Base  # local import to avoid cycles

    Base.metadata.create_all(_engine)


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
