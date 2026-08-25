"""تست‌های «حلقه‌ی فروش»: تسویه از UI، تاریخچه‌ی فاکتور، هشدار اشتراک، پی‌وال.

این‌ها همان گپ‌هایی‌اند که یک مشتریِ پولی روز اول به‌شان می‌خورد.
"""
import datetime as dt
from types import SimpleNamespace

from hesabyar.bot import handlers, keyboards
from hesabyar.config import Settings
from hesabyar.core import jalali
from hesabyar.db.models import Direction, Kind
from hesabyar.services import invoices as invoice_service
from hesabyar.services import ledger as ledger_service
from hesabyar.services import subscription as sub
from hesabyar.services import transactions as tx

UID = 501


class _Bot:
    def __init__(self):
        self.photos: list = []
        self.documents: list = []
        self.messages: list = []

    async def send_photo(self, chat_id, photo=None, **kw):
        self.photos.append({"chat_id": chat_id, **kw})

    async def send_document(self, chat_id, document=None, **kw):
        self.documents.append({"chat_id": chat_id, **kw})

    async def send_message(self, chat_id, text=None, **kw):
        self.messages.append({"chat_id": chat_id, "text": text, **kw})


class _Query:
    def __init__(self, data):
        self.data = data
        self.answers: list = []
        self.edits: list = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append(text)

    async def edit_message_text(self, text, **kw):
        self.edits.append({"text": text, **kw})


def _ctx(store, bot=None):
    app = SimpleNamespace(
        bot_data={"store": store, "settings": Settings(bot_token="x")}, bot=bot
    )
    return SimpleNamespace(application=app, bot=bot, chat_data={}, user_data={})


def _update(query=None, message=None):
    return SimpleNamespace(
        callback_query=query,
        message=message,
        effective_user=SimpleNamespace(id=UID, full_name="تست"),
        effective_chat=SimpleNamespace(id=UID, type="private"),
        effective_message=message,
    )


# --- تسویه از UI --------------------------------------------------------------


class TestSettleFromUI:
    async def test_settle_button_closes_entry(self, store):
        await tx.get_or_create_user(store, UID)
        e = await ledger_service.add_entry(
            store, UID, direction=Direction.RECEIVABLE, party_name="علی",
            amount=500_000, due_date=jalali.now().date(),
        )
        ctx = _ctx(store)
        query = _Query(f"ledger:settle:{e.id}")
        await handlers.on_ledger_action(_update(query=query), ctx)

        settled = store.get("ledger_entries", e.id)
        assert settled.is_settled and settled.settled_at is not None
        # از فهرست باز و یادآوری‌ها هم خارج شد
        assert ledger_service.list_open(store, UID) == []
        assert ledger_service.entries_due_for_reminder(store, jalali.now()) == []
        assert any("تسویه شد" in (a or "") for a in query.answers)

    async def test_settle_gone_shows_alert(self, store):
        await tx.get_or_create_user(store, UID)
        ctx = _ctx(store)
        query = _Query("ledger:settle:999")
        await handlers.on_ledger_action(_update(query=query), ctx)
        assert any("قبلاً" in (a or "") for a in query.answers)

    async def test_list_includes_settle_buttons(self, store):
        await tx.get_or_create_user(store, UID)
        await ledger_service.add_entry(
            store, UID, direction=Direction.PAYABLE, party_name="رضا", amount=100_000,
        )
        ctx = _ctx(store)
        query = _Query("ledger:list")
        await handlers.on_ledger_action(_update(query=query), ctx)
        markup = query.edits[-1].get("reply_markup")
        assert markup is not None
        flat = [b.callback_data for row in markup.inline_keyboard for b in row]
        assert any(cb.startswith("ledger:settle:") for cb in flat)


class TestSettleKeyboard:
    def test_none_when_empty(self):
        assert keyboards.ledger_settle_list([]) is None

    def test_caps_at_ten_entries(self):
        """هر ردیف دو خط دارد (تسویه + اسنوز) — سقف روی تعدادِ ردیف‌هاست، نه سطر."""
        entries = [
            SimpleNamespace(id=i, party_name=f"ط{i}", amount=1000, is_cheque=False)
            for i in range(15)
        ]
        markup = keyboards.ledger_settle_list(entries)
        assert len(markup.inline_keyboard) == 20

    def test_each_entry_offers_three_snooze_buttons(self):
        entries = [
            SimpleNamespace(id=1, party_name="رضا", amount=1000, is_cheque=False)
        ]
        markup = keyboards.ledger_settle_list(entries)
        flat = [b.callback_data for row in markup.inline_keyboard for b in row]
        assert "snooze:1:tomorrow" in flat
        assert "snooze:1:3days" in flat
        assert "snooze:1:week" in flat


# --- تاریخچه‌ی فاکتور ----------------------------------------------------------


class TestInvoiceHistory:
    async def _mk_invoice(self, store):
        user = await tx.get_or_create_user(store, UID)
        user.business_name = "بوتیک آرا"
        return await invoice_service.create_invoice(
            store, UID, customer_name="رضا",
            items=[{"title": "کالا", "quantity": 2, "unit_price": 250_000}],
            issue_date=jalali.now().date(),
        )

    async def test_resend_sends_photo_and_pdf(self, store):
        invoice = await self._mk_invoice(store)
        bot = _Bot()
        ctx = _ctx(store, bot=bot)
        query = _Query(f"invh:{invoice.id}")
        await handlers.on_invoice_history(_update(query=query), ctx)
        assert len(bot.photos) == 1
        assert len(bot.documents) == 1
        assert "ارسال دوباره" in bot.photos[0]["caption"]

    async def test_other_users_invoice_is_denied(self, store):
        invoice = await self._mk_invoice(store)
        bot = _Bot()
        ctx = _ctx(store, bot=bot)
        query = _Query(f"invh:{invoice.id}")
        update = _update(query=query)
        update.effective_user = SimpleNamespace(id=999, full_name="غریبه")
        await handlers.on_invoice_history(update, ctx)
        assert bot.photos == [] and bot.documents == []

    def test_history_keyboard(self, ):
        invs = [
            SimpleNamespace(id=1, number="۱۴۰۵-۰۰۰۱", customer_name="رضا", total=500),
        ]
        markup = keyboards.invoice_history(invs)
        assert markup.inline_keyboard[0][0].callback_data == "invh:1"
        assert keyboards.invoice_history([]) is None


# --- هشدار و انقضای اشتراک -----------------------------------------------------


class TestSubscriptionNotices:
    async def _sub_with_expiry(self, store, uid, delta_days):
        s = await sub.get_or_create_subscription(store, uid)
        s.expires_at = jalali.now() + dt.timedelta(days=delta_days)
        await store.update("subscriptions", s)
        return s

    async def test_warn_days_and_expiry(self, store):
        now = jalali.now()
        await self._sub_with_expiry(store, 1, 3)      # warn3
        await self._sub_with_expiry(store, 2, 1)      # warn1
        await self._sub_with_expiry(store, 3, 10)     # ساکت
        s4 = await sub.get_or_create_subscription(store, 4)   # منقضیِ تازه
        s4.expires_at = now - dt.timedelta(hours=2)
        await store.update("subscriptions", s4)
        s5 = await sub.get_or_create_subscription(store, 5)   # منقضیِ قدیمی ⇒ ساکت
        s5.expires_at = now - dt.timedelta(days=5)
        await store.update("subscriptions", s5)

        notices = dict(sub.subs_needing_notice(store, now))
        assert notices.get(1) == "warn3"
        assert notices.get(2) == "warn1"
        assert notices.get(4) == "expired"
        assert 3 not in notices and 5 not in notices

    async def test_value_recap(self, store):
        assert sub.build_value_recap(store, UID) == ""
        await tx.get_or_create_user(store, UID)
        await tx.add_transaction(
            store, UID, kind=Kind.INCOME, amount=100, category="x",
            description="", occurred_at=jalali.now(),
        )
        recap = sub.build_value_recap(store, UID)
        assert "تراکنش" in recap and "۱" in recap


# --- پی‌وال شخصی‌شده ------------------------------------------------------------


class TestPaywall:
    async def test_paywall_mentions_data_and_value(self, store):
        await tx.get_or_create_user(store, UID)
        await tx.add_transaction(
            store, UID, kind=Kind.EXPENSE, amount=100, category="x",
            description="", occurred_at=jalali.now(),
        )
        text = handlers._paywall_text(store, UID)
        assert "اشتراک" in text
        assert "تراکنش" in text          # خلاصه‌ی ارزش
        assert "محفوظ" in text           # اطمینان از داده


# --- هندلر سراسری خطا ----------------------------------------------------------


class TestErrorHandler:
    async def test_replies_politely(self, store):
        replies = []

        class _Msg:
            async def reply_text(self, text, **kw):
                replies.append(text)

        ctx = _ctx(store)
        ctx.error = RuntimeError("boom")
        update = SimpleNamespace(effective_message=_Msg())
        await handlers.on_error(update, ctx)
        assert replies and "خطا" in replies[0]

    async def test_survives_when_reply_fails(self, store):
        class _Msg:
            async def reply_text(self, text, **kw):
                raise RuntimeError("blocked")

        ctx = _ctx(store)
        ctx.error = RuntimeError("boom")
        await handlers.on_error(SimpleNamespace(effective_message=_Msg()), ctx)
        await handlers.on_error(SimpleNamespace(effective_message=None), ctx)
