"""E&R PokerBet — database engine/session setup.

SQLite default (dev). PG-ready: point ER_DB_URL at
postgresql+psycopg2://user:pass@host:5432/new_er once provisioned (ADR-002).
"""
from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .config import settings
from .models import Base

_engine = create_engine(
    settings.db_url,
    connect_args={"check_same_thread": False} if settings.db_url.startswith("sqlite") else {},
    pool_pre_ping=True,
)

if settings.db_url.startswith("sqlite"):
    @event.listens_for(_engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(_engine)


def session() -> Session:
    return SessionLocal()
