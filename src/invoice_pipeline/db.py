"""SQLAlchemy engine/session setup.

`engine`/`SessionLocal` are built from `config.DATABASE_URL` for the running
app. Tests build their own engine (e.g. an in-memory SQLite one) via
`make_engine`/`make_session_factory` instead of importing the module-level
singletons, so they never touch the real Postgres database.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from invoice_pipeline import config


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str | None = None):
    return create_engine(database_url or config.DATABASE_URL)


def make_session_factory(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


engine = make_engine()
SessionLocal = make_session_factory(engine)


def init_db(bind_engine=None) -> None:
    """Create all tables. Import models before calling so they're registered
    on Base.metadata."""
    from invoice_pipeline import models  # noqa: F401

    Base.metadata.create_all(bind=bind_engine or engine)


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
