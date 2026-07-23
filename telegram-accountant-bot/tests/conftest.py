"""Fixtureهای مشترک تست."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from hesabyar.db.database import init_db, make_session_factory


@pytest.fixture
def session():
    """نشست SQLite در حافظه با یک اتصال ثابت (StaticPool)."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    init_db(engine)
    SessionLocal = make_session_factory(engine)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()
