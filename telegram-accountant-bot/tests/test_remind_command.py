"""تست‌های دستور /remind — سه‌دسته‌ای (معوق/امروز/نزدیک) با دکمه‌ی یادآوری (فاز ۱۸)."""
import datetime as dt
from types import SimpleNamespace

from hesabyar.bot import handlers, texts
from hesabyar.config import Settings
from hesabyar.core import jalali, money
from hesabyar.db.models import Direction
from hesabyar.services import invoices as invoice_service
from hesabyar.services import ledger as ledger_service
from hesabyar.services import transactions as tx

UID = 19_001
CUSTOMER_TG_ID = 19_002


def _cb(markup):
    rows = getattr(markup, "inline_keyboard", None)
    return [b.callback_data for row in rows for b in row] if rows else []


class _Msg:
    def __init__(self, text=""):
        self.text = text
        self.replies: list = []
        self.chat = SimpleNamespace(id=UID, type="private", title=None)
        self.chat_id = UID
        self.message_id = 1

    async def reply_text(self, text, **kw):
        self.replies.append({"text": text, **kw})
        return SimpleNamespace(message_id=2, chat_id=UID)


def _ctx(store):
    app = SimpleNamespace(
        bot_data={"store": store, "settings": Settings(bot_token="x")},
        bot=SimpleNamespace(),
    )
    return SimpleNamespace(application=app, bot=app.bot,
                           chat_data={}, user_data={}, args=[])


def _update(message):
    return SimpleNamespace(
        message=message, callback_query=None,
        effective_user=SimpleNamespace(id=UID, full_name="تست", username="t"),
        effective_chat=SimpleNamespace(id=UID, type="private", title=None),
        effective_message=message,
    )


async def _remind(store):
    ctx = _ctx(store)
    msg = _Msg("/remind")
    await handlers.remind_cmd(_update(msg), ctx)
    return msg


class TestNoReminders:
    async def test_shows_the_all_clear_message(self, store):
        await tx.get_or_create_user(store, UID)
        msg = await _remind(store)
        assert msg.replies[-1]["text"] == texts.REMIND_NONE

    async def test_a_payable_alone_does_not_count(self, store):
        """بدهیِ خودم (نه طلب) نباید در /remind بیاید — این برای بدهکارهاست."""
        await ledger_service.add_entry(
            store, UID, direction=Direction.PAYABLE, party_name="پخش",
            amount=100_000, due_date=jalali.now().date(),
        )
        msg = await _remind(store)
        assert msg.replies[-1]["text"] == texts.REMIND_NONE


class TestThreeBuckets:
    async def _seed_all_buckets(self, store):
        today = jalali.now().date()
        await ledger_service.add_entry(
            store, UID, direction=Direction.RECEIVABLE, party_name="دیروزی",
            amount=200_000, due_date=today - dt.timedelta(days=2),
        )
        await ledger_service.add_entry(
            store, UID, direction=Direction.RECEIVABLE, party_name="امروزی",
            amount=300_000, due_date=today,
        )
        await ledger_service.add_entry(
            store, UID, direction=Direction.RECEIVABLE, party_name="هفته‌ای",
            amount=400_000, due_date=today + dt.timedelta(days=3),
        )
        await ledger_service.add_entry(  # خارج از پنجره‌ی یک‌هفته‌ای
            store, UID, direction=Direction.RECEIVABLE, party_name="دوردست",
            amount=999_000, due_date=today + dt.timedelta(days=20),
        )

    async def test_shows_all_three_section_titles_in_order(self, store):
        await self._seed_all_buckets(store)
        msg = await _remind(store)
        text = msg.replies[-1]["text"]
        assert text.index(texts.REMINDER_OVERDUE_TITLE) < text.index(texts.REMINDER_TODAY_TITLE)
        assert text.index(texts.REMINDER_TODAY_TITLE) < text.index(texts.REMINDER_UPCOMING_TITLE)

    async def test_each_party_appears_with_its_amount(self, store):
        await self._seed_all_buckets(store)
        msg = await _remind(store)
        text = msg.replies[-1]["text"]
        assert "دیروزی" in text and money.format_amount(200_000) in text
        assert "امروزی" in text and money.format_amount(300_000) in text
        assert "هفته‌ای" in text and money.format_amount(400_000) in text

    async def test_far_future_entries_are_excluded(self, store):
        await self._seed_all_buckets(store)
        msg = await _remind(store)
        assert "دوردست" not in msg.replies[-1]["text"]

    async def test_only_the_relevant_sections_appear(self, store):
        """اگر فقط معوق دارد، عنوانِ «امروز»/«نزدیک» نباید بیاید."""
        await ledger_service.add_entry(
            store, UID, direction=Direction.RECEIVABLE, party_name="فقط-معوق",
            amount=100_000, due_date=jalali.now().date() - dt.timedelta(days=5),
        )
        msg = await _remind(store)
        text = msg.replies[-1]["text"]
        assert texts.REMINDER_OVERDUE_TITLE in text
        assert texts.REMINDER_TODAY_TITLE not in text
        assert texts.REMINDER_UPCOMING_TITLE not in text


class TestReminderButton:
    async def test_a_reachable_debtor_gets_a_reminder_button(self, store):
        invoice = await invoice_service.create_invoice(
            store, UID, customer_name="رضا",
            items=[{"title": "کالا", "quantity": 1, "unit_price": 500_000}],
            issue_date=jalali.now().date(),
        )
        await invoice_service.attach_customer(store, invoice, CUSTOMER_TG_ID)
        await ledger_service.add_entry(
            store, UID, direction=Direction.RECEIVABLE, party_name="رضا",
            amount=500_000, due_date=jalali.now().date(),
        )
        msg = await _remind(store)
        buttons = _cb(msg.replies[-1]["reply_markup"])
        assert any(d.startswith("dremind:") for d in buttons)

    async def test_an_unreachable_debtor_is_marked_but_has_no_button(self, store):
        await ledger_service.add_entry(
            store, UID, direction=Direction.RECEIVABLE, party_name="ناشناس",
            amount=100_000, due_date=jalali.now().date(),
        )
        msg = await _remind(store)
        text = msg.replies[-1]["text"]
        assert "ناشناس" in text and texts.REMIND_NO_CONTACT in text
        markup = msg.replies[-1].get("reply_markup")
        assert markup is None or _cb(markup) == []
