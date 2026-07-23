"""ساخت موتور و نشست دیتابیس."""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base


def make_engine(url: str = "sqlite:///hesabyar.db", echo: bool = False) -> Engine:
    """ساخت موتور SQLAlchemy.

    برای SQLite گزینه‌ی ``check_same_thread`` غیرفعال می‌شود تا هم حلقه‌ی
    async بات و هم صف کارهای زمان‌بندی‌شده (JobQueue) بتوانند از یک اتصال
    استفاده کنند.
    """
    connect_args: dict = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(url, echo=echo, future=True, connect_args=connect_args)


def init_db(engine: Engine) -> None:
    """ساخت جدول‌ها در صورت نبودن."""
    Base.metadata.create_all(engine)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
