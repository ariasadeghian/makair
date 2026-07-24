"""تست‌های منطق یادآوری سررسید (بدون شبکه/تلگرام).

منطق دسته‌بندی (معوق/امروز/نزدیک)، پنجره‌ی lead_days و ساخت متن پیام آزموده
می‌شوند.
"""
import datetime as dt

from hesabyar.bot.reminders import build_reminder_message
from hesabyar.core import jalali
from hesabyar.db.models import Direction
from hesabyar.services import ledger as ledger_service

UID = 707


async def _seed(store, party, amount, due_date, direction=Direction.PAYABLE):
    return await ledger_service.add_entry(
        store, UID, direction=direction, party_name=party,
        amount=amount, due_date=due_date,
    )


async def test_lead_days_window(store):
    now = jalali.now()
    today = now.date()
    await _seed(store, "دیروز", 100_000, today - dt.timedelta(days=1))       # overdue
    await _seed(store, "امروز", 200_000, today)                             # today
    await _seed(store, "دو-روز-بعد", 300_000, today + dt.timedelta(days=2))  # نزدیک
    await _seed(store, "ده-روز-بعد", 400_000, today + dt.timedelta(days=10)) # خارج از پنجره

    due0 = ledger_service.entries_due_for_reminder(store, now, lead_days=0)
    assert {e.party_name for e in due0} == {"دیروز", "امروز"}

    due2 = ledger_service.entries_due_for_reminder(store, now, lead_days=2)
    assert {e.party_name for e in due2} == {"دیروز", "امروز", "دو-روز-بعد"}


async def test_due_bucket(store):
    now = jalali.now()
    today = now.date()
    e_over = await _seed(store, "الف", 1, today - dt.timedelta(days=3))
    e_today = await _seed(store, "ب", 1, today)
    e_up = await _seed(store, "ج", 1, today + dt.timedelta(days=1))
    assert ledger_service.due_bucket(e_over, now) == "overdue"
    assert ledger_service.due_bucket(e_today, now) == "today"
    assert ledger_service.due_bucket(e_up, now) == "upcoming"


async def test_build_message_has_three_sections(store):
    now = jalali.now()
    today = now.date()
    items = [
        await _seed(store, "علی", 500_000, today - dt.timedelta(days=2),
                    Direction.RECEIVABLE),
        await _seed(store, "شرکت پخش", 300_000, today, Direction.PAYABLE),
        await _seed(store, "رضا", 200_000, today + dt.timedelta(days=2),
                    Direction.RECEIVABLE),
    ]
    msg = build_reminder_message(items, now)
    assert "معوق" in msg          # بخش معوق
    assert "امروز سررسید" in msg  # بخش امروز
    assert "نزدیک" in msg         # بخش نزدیک
    # برچسب طلب/بدهی درست است
    assert "طلب از علی" in msg
    assert "بدهی به شرکت پخش" in msg


def test_build_message_empty_is_blank():
    assert build_reminder_message([], jalali.now()) == ""
