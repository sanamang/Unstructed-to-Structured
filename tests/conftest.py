import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from invoice_pipeline import models  # noqa: F401 - registers tables on Base.metadata
from invoice_pipeline.db import Base, make_session_factory


@pytest.fixture()
def db_session():
    """An isolated in-memory SQLite database per test - never touches the
    real Postgres instance. StaticPool keeps the single :memory: connection
    alive across uses within the test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = make_session_factory(engine)()
    try:
        yield session
    finally:
        session.close()
