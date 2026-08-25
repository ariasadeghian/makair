"""تست‌های منطق یادآوری سررسید (بدون شبکه/تلگرام).

منطق دسته‌بندی (معوق/امروز/نزدیک)، پنجره‌ی lead_days و ساخت متن پیام آزموده
می‌شوند.
"""
import datetime as dt
from types import SimpleNamespace

from hesabyar.bot import reminders
from hesabyar.bot.reminders import build_reminder_message
from hesabyar.config import Settings
from hesabyar.core import jalali
from hesabyar.db.models import Direction, RetentionEventKind
from hesabyar.services import ledger as ledger_service
from hesabyar.services import transactions as tx

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


async def test_receivable_reminder_buckets_only_includes_receivables(store):
    """این دسته‌بندی برای «یادآوری به بدهکار» است: فقط طلب، و فقط تا یک هفته."""
    now = jalali.now()
    today = now.date()
    await _seed(store, "بدهیِ من", 100_000, today - dt.timedelta(days=1),
                Direction.PAYABLE)  # بدهی، نه طلب ⇒ نباید بیاید
    over = await _seed(store, "دیروز", 200_000, today - dt.timedelta(days=1),
                        Direction.RECEIVABLE)
    todays = await _seed(store, "امروز", 300_000, today, Direction.RECEIVABLE)
    soon = await _seed(store, "این‌هفته", 400_000, today + dt.timedelta(days=3),
                        Direction.RECEIVABLE)
    far = await _seed(store, "دور", 500_000, today + dt.timedelta(days=20),
                       Direction.RECEIVABLE)  # خارج از پنجره‌ی ۷روزه

    buckets = ledger_service.receivable_reminder_buckets(store, UID, now)
    assert [e.id for e in buckets["overdue"]] == [over.id]
    assert [e.id for e in buckets["today"]] == [todays.id]
    assert [e.id for e in buckets["upcoming"]] == [soon.id]
    all_ids = {e.id for rows in buckets.values() for e in rows}
    assert far.id not in all_ids


async def test_receivable_reminder_buckets_empty_when_nothing_due(store):
    await _seed(store, "دور", 100_000, jalali.now().date() + dt.timedelta(days=30),
                Direction.RECEIVABLE)
    buckets = ledger_service.receivable_reminder_buckets(store, UID, jalali.now())
    assert buckets == {"overdue": [], "today": [], "upcoming": []}


# --- job سراسریِ send_due_reminders (بدون شبکه) -----------------------------------


class _Bot:
    def __init__(self):
        self.sent: list = []

    async def send_message(self, chat_id, text=None, **kw):
        self.sent.append({"chat_id": chat_id, "text": text, **kw})


def _ctx(store, bot=None):
    app = SimpleNamespace(
        bot_data={"store": store, "settings": Settings(bot_token="x")},
        bot=bot or _Bot(),
    )
    return SimpleNamespace(application=app, bot=app.bot)


class TestSendDueRemindersJob:
    async def test_sends_and_logs_an_event_when_something_is_due(self, store):
        await _seed(store, "علی", 500_000, jalali.now().date(), Direction.RECEIVABLE)
        ctx = _ctx(store)
        await reminders.send_due_reminders(ctx)

        assert len(ctx.bot.sent) == 1
        assert ctx.bot.sent[0]["chat_id"] == UID
        events = store.list(
            "retention_events",
            lambda e: e.user_id == UID and e.kind == RetentionEventKind.DUE_REMINDER_SENT,
        )
        assert len(events) == 1

    async def test_nothing_due_sends_nothing(self, store):
        await tx.get_or_create_user(store, UID)
        ctx = _ctx(store)
        await reminders.send_due_reminders(ctx)
        assert ctx.bot.sent == []

    async def test_preference_off_skips_the_message_and_the_event(self, store):
        await _seed(store, "علی", 500_000, jalali.now().date(), Direction.RECEIVABLE)
        user = store.get("users", UID)
        user.notify_due_reminders = False
        await store.update("users", user)

        ctx = _ctx(store)
        await reminders.send_due_reminders(ctx)
        assert ctx.bot.sent == []
        assert store.list(
            "retention_events", lambda e: e.kind == RetentionEventKind.DUE_REMINDER_SENT
        ) == []

    async def test_default_preference_is_on(self, store):
        await _seed(store, "علی", 500_000, jalali.now().date(), Direction.RECEIVABLE)
        ctx = _ctx(store)
        await reminders.send_due_reminders(ctx)
        assert len(ctx.bot.sent) == 1
