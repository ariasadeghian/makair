"""Fixtureهای مشترک تست (Store روی اسپردشیت‌های ساختگی، بدون شبکه)."""
import pytest_asyncio

from fakes import FakeClient, FakeSpreadsheet

from hesabyar.db.store import Store


@pytest_asyncio.fixture
async def store():
    """Store خالی: اسپردشیت مرکزی + کلاینتِ ساختگی برای شیتِ هر کاربر."""
    s = Store(FakeSpreadsheet(), client=FakeClient(), folder_id="folder-x")
    await s.load()
    return s
