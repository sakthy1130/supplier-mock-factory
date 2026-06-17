"""SQLAlchemy engine and session factory."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

_engine = None
_SessionLocal = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        connect_args = {}
        if settings.database_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        _engine = create_engine(settings.database_url, connect_args=connect_args)
        _SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False)
    return _engine


def get_session_factory():
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def init_db() -> None:
    from app.db.models import Base

    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    _run_migrations(engine)


def _run_migrations(engine) -> None:
    """Apply incremental column additions that create_all won't handle for existing tables."""
    import logging
    from sqlalchemy import text

    log = logging.getLogger(__name__)
    migrations = [
        ("scenarios", "sb_config_id", "VARCHAR(64)"),
    ]
    with engine.connect() as conn:
        for table, column, col_type in migrations:
            # SQLite PRAGMA, works for both SQLite and can be extended for Postgres
            if engine.dialect.name == "sqlite":
                result = conn.execute(text(f"PRAGMA table_info({table})"))
                existing = {row[1] for row in result}
                if column not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
                    conn.commit()
                    log.info("Migration: added column %s.%s", table, column)
            # For PostgreSQL (future)
            elif engine.dialect.name == "postgresql":
                result = conn.execute(text(
                    f"SELECT column_name FROM information_schema.columns "
                    f"WHERE table_name='{table}' AND column_name='{column}'"
                ))
                if result.fetchone() is None:
                    conn.execute(text(
                        f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {col_type}"
                    ))
                    conn.commit()
                    log.info("Migration: added column %s.%s", table, column)


def reset_engine() -> None:
    """Dispose engine — for tests switching DATABASE_URL."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def get_db() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
