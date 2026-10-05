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

    bind_engine = bind_engine or engine
    Base.metadata.create_all(bind=bind_engine)
    _migrate(bind_engine)


# create_all() never alters existing tables, so schema changes made after a
# database was first created are applied here. Every statement is idempotent.
_POSTGRES_MIGRATIONS = (
    # "uploaded" status (upload and structure became separate steps)
    "ALTER TYPE documentstatus ADD VALUE IF NOT EXISTS 'UPLOADED' BEFORE 'PENDING_REVIEW'",
    "ALTER TABLE documents ALTER COLUMN doc_type DROP NOT NULL",
    "ALTER TABLE documents ALTER COLUMN classification_confidence DROP NOT NULL",
    # any messy billing document is accepted, not just formal invoices
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS document_kind VARCHAR",
    "ALTER TABLE invoice_records ADD COLUMN IF NOT EXISTS additional_fields JSON DEFAULT '[]'",
)


def _migrate(bind_engine) -> None:
    if bind_engine.dialect.name != "postgresql":
        return
    # ALTER TYPE ... ADD VALUE must commit before the new value is usable.
    with bind_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        for statement in _POSTGRES_MIGRATIONS:
            conn.exec_driver_sql(statement)


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
