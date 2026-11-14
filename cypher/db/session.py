"""Database engine and session management using SQLAlchemy 2.0."""

from __future__ import annotations

from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from cypher.config import get_settings

_engine = None
_session_factory = None


def get_engine():
    """Lazily initialize and return the SQLAlchemy engine."""
    global _engine
    if _engine is None:
        settings = get_settings()
        database_url = settings.normalized_database_url
        connect_args = {}
        if database_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False

        _engine = create_engine(
            database_url,
            connect_args=connect_args,
            echo=False,
            future=True,
        )
    return _engine


def get_session_factory():
    """Lazily initialize and return the session factory."""
    global _session_factory
    if _session_factory is None:
        engine = get_engine()
        _session_factory = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=engine,
            class_=Session,
            future=True,
        )
    return _session_factory


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session per request."""
    factory = get_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()


def init_db(engine=None) -> None:
    """Create all tables defined in models.

    Idempotent operation (CREATE TABLE IF NOT EXISTS).
    """
    from cypher.db.models import Base

    target_engine = engine or get_engine()
    Base.metadata.create_all(bind=target_engine)
