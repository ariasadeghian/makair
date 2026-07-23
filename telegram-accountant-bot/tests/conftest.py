"""Fixtureهای مشترک تست (Store روی اسپردشیت ساختگی)."""
import pytest_asyncio

from fakes import FakeSpreadsheet

from hesabyar.db.store import Store


@pytest_asyncio.fixture
async def store():
    """یک Store خالی روی اسپردشیت ساختگی (بدون شبکه)."""
    s = Store(FakeSpreadsheet())
    await s.load()
    return s
