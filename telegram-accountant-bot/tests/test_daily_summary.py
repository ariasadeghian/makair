"""تست‌های خلاصه‌ی خودکارِ آخر روز (فاز ۱۱)."""
import datetime as dt
from types import SimpleNamespace

from hesabyar.bot import handlers, keyboards, reminders, texts
from hesabyar.config import Settings, load_settings
from hesabyar.core import jalali
from hesabyar.db.models import Direction, Kind
from hesabyar.services import invoices as invoice_service
from hesabyar.services import ledger as ledger_service
from hesabyar.services import reports as report_service
from hesabyar.services import transactions as tx

ACTIVE = 13_001
QUIET = 13_002


def _cb(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


class _Bot:
    def __init__(self):
        self.sent: list = []

    async def send_message(self, chat_id, text=None, **kw):
        self.sent.append({"chat_id": chat_id, "text": text, **kw})


class _BrokenBot(_Bot):
    async def send_message(self, chat_id, text=None, **kw):
        raise RuntimeError("کاربر بات را بلاک کرده")


def _ctx(store, bot=None):
    app = SimpleNamespace(
        bot_data={"store": store, "settings": Settings(bot_token="x")},
        bot=bot or _Bot(),
    )
    return SimpleNamespace(application=app, bot=app.bot)


async def _spend(store, user_id, amount, when=None, category="متفرقه"):
    await tx.get_or_create_user(store, user_id)
    return await tx.add_transaction(
        store, user_id, kind=Kind.EXPENSE, amount=amount, category=category,
        description="", occurred_at=when or jalali.now(),
    )


async def _earn(store, user_id, amount, when=None):
    await tx.get_or_create_user(store, user_id)
    return await tx.add_transaction(
        store, user_id, kind=Kind.INCOME, amount=amount, category="فروش کالا",
        description="", occurred_at=when or jalali.now(),
    )


# --- محتوای خلاصه ---------------------------------------------------------------


class TestDigestNumbers:
    async def test_none_when_nothing_happened(self, store):
        await tx.get_or_create_user(store, QUIET)
        assert report_service.build_daily_digest(store, QUIET, jalali.now()) is None

    async def test_yesterdays_activity_does_not_count(self, store):
        yesterday = jalali.now() - dt.timedelta(days=1)
        await _spend(store, QUIET, 500_000, when=yesterday)
        assert report_service.build_daily_digest(store, QUIET, jalali.now()) is None

    async def test_income_expense_and_net(self, store):
        await _earn(store, ACTIVE, 2_000_000)
        await _spend(store, ACTIVE, 800_000)
        digest = report_service.build_daily_digest(store, ACTIVE, jalali.now())
        assert "۲٬۰۰۰٬۰۰۰" in digest       # درآمد
        assert "۸۰۰٬۰۰۰" in digest          # هزینه
        assert "۱٬۲۰۰٬۰۰۰" in digest        # خالص
        assert "۲ تراکنش" in digest

    async def test_negative_net_is_marked(self, store):
        await _spend(store, ACTIVE, 900_000)
        digest = report_service.build_daily_digest(store, ACTIVE, jalali.now())
        assert "🔴" in digest and "🟢" not in digest

    async def test_positive_net_is_marked(self, store):
        await _earn(store, ACTIVE, 900_000)
        digest = report_service.build_daily_digest(store, ACTIVE, jalali.now())
        assert "🟢" in digest

    async def test_upcoming_due_entries_are_counted(self, store):
        await _spend(store, ACTIVE, 100_000)
        today = jalali.now().date()
        for offset in (0, 1, 2):
            await ledger_service.add_entry(
                store, ACTIVE, direction=Direction.PAYABLE,
                party_name=f"طرف {offset}", amount=300_000,
                due_date=today + dt.timedelta(days=offset),
            )
        # این یکی خارج از پنجره‌ی ۲روزه است و نباید شمرده شود
        await ledger_service.add_entry(
            store, ACTIVE, direction=Direction.PAYABLE, party_name="دور",
            amount=1_000, due_date=today + dt.timedelta(days=10),
        )
        digest = report_service.build_daily_digest(store, ACTIVE, jalali.now())
        assert "⏰" in digest
        assert "۳ مورد نزدیکِ سررسید" in digest

    async def test_no_due_line_when_nothing_is_close(self, store):
        await _spend(store, ACTIVE, 100_000)
        digest = report_service.build_daily_digest(store, ACTIVE, jalali.now())
        assert "⏰" not in digest

    async def test_settled_entries_are_not_counted_as_due(self, store):
        await _spend(store, ACTIVE, 100_000)
        entry = await ledger_service.add_entry(
            store, ACTIVE, direction=Direction.PAYABLE, party_name="رضا",
            amount=200_000, due_date=jalali.now().date(),
        )
        await ledger_service.settle(store, entry.id, ACTIVE, jalali.now())
        digest = report_service.build_daily_digest(store, ACTIVE, jalali.now())
        assert "⏰" not in digest

    async def test_another_users_numbers_do_not_leak(self, store):
        await _earn(store, ACTIVE, 1_000_000)
        await _earn(store, QUIET, 7_777_777)
        digest = report_service.build_daily_digest(store, ACTIVE, jalali.now())
        assert "۷٬۷۷۷٬۷۷۷" not in digest


class TestActivityIsMoreThanTransactions:
    async def test_an_invoice_alone_triggers_a_summary(self, store):
        """کسی که امروز فقط فاکتور زده هم باید خلاصه بگیرد."""
        await tx.get_or_create_user(store, ACTIVE)
        await invoice_service.create_invoice(
            store, ACTIVE, customer_name="رضا",
            items=[{"title": "مبل", "quantity": 1, "unit_price": 5_000_000}],
            issue_date=jalali.now().date(),
        )
        digest = report_service.build_daily_digest(store, ACTIVE, jalali.now())
        assert digest is not None
        assert "۱ فاکتور صادر شد" in digest

    async def test_a_ledger_entry_alone_triggers_a_summary(self, store):
        await tx.get_or_create_user(store, ACTIVE)
        await ledger_service.add_entry(
            store, ACTIVE, direction=Direction.RECEIVABLE,
            party_name="سارا", amount=400_000,
        )
        digest = report_service.build_daily_digest(store, ACTIVE, jalali.now())
        assert digest is not None
        assert "۱ ثبت در دفتر" in digest

    async def test_stats_shape(self, store):
        await _earn(store, ACTIVE, 1_000_000)
        stats = report_service.daily_activity(store, ACTIVE, jalali.now())
        assert stats["active"] is True
        assert stats["count"] == 1
        assert stats["invoices"] == 0
        assert stats["ledger_entries"] == 0
        assert stats["due_soon"] == 0


# --- خودِ job -------------------------------------------------------------------


class TestJob:
    async def test_active_user_gets_it_quiet_user_does_not(self, store):
        await _earn(store, ACTIVE, 1_500_000)
        await tx.get_or_create_user(store, QUIET)
        ctx = _ctx(store)
        await reminders.daily_summary_job(ctx)

        recipients = [m["chat_id"] for m in ctx.bot.sent]
        assert recipients == [ACTIVE]
        assert "۱٬۵۰۰٬۰۰۰" in ctx.bot.sent[0]["text"]

    async def test_nobody_is_messaged_on_a_quiet_day(self, store):
        await tx.get_or_create_user(store, QUIET)
        ctx = _ctx(store)
        await reminders.daily_summary_job(ctx)
        assert ctx.bot.sent == []

    async def test_message_carries_the_daily_close_buttons(self, store):
        """جمع‌بندیِ آخر روز تعاملی است: ثبتِ سریع + تأییدِ تمام‌شدن + گزارشِ کامل."""
        await _earn(store, ACTIVE, 1_000_000)
        ctx = _ctx(store)
        await reminders.daily_summary_job(ctx)
        markup = ctx.bot.sent[0]["reply_markup"]
        assert _cb(markup) == ["dclose:income", "dclose:expense", "dclose:done", "menu:report"]

    async def test_message_ends_with_the_daily_close_question(self, store):
        await _earn(store, ACTIVE, 1_000_000)
        ctx = _ctx(store)
        await reminders.daily_summary_job(ctx)
        assert "چیزی امروز جا مانده؟" in ctx.bot.sent[0]["text"]

    async def test_html_mode_is_used(self, store):
        await _earn(store, ACTIVE, 1_000_000)
        ctx = _ctx(store)
        await reminders.daily_summary_job(ctx)
        assert ctx.bot.sent[0]["parse_mode"] == "HTML"

    async def test_one_blocked_user_does_not_stop_the_rest(self, store):
        await _earn(store, ACTIVE, 1_000_000)
        ctx = _ctx(store, bot=_BrokenBot())
        await reminders.daily_summary_job(ctx)   # نباید خطا بدهد

    async def test_each_active_user_gets_their_own_numbers(self, store):
        await _earn(store, ACTIVE, 1_000_000)
        await _earn(store, QUIET, 2_500_000)
        ctx = _ctx(store)
        await reminders.daily_summary_job(ctx)
        by_user = {m["chat_id"]: m["text"] for m in ctx.bot.sent}
        assert set(by_user) == {ACTIVE, QUIET}
        assert "۱٬۰۰۰٬۰۰۰" in by_user[ACTIVE]
        assert "۲٬۵۰۰٬۰۰۰" in by_user[QUIET]

    def test_old_name_still_points_at_the_job(self):
        assert reminders.send_nightly_summary is reminders.daily_summary_job


class TestDailyCloseEventsAndPreference:
    async def test_sending_logs_a_daily_close_sent_event(self, store):
        from hesabyar.db.models import RetentionEventKind
        await _earn(store, ACTIVE, 1_000_000)
        ctx = _ctx(store)
        await reminders.daily_summary_job(ctx)
        events = store.list(
            "retention_events",
            lambda e: e.user_id == ACTIVE and e.kind == RetentionEventKind.DAILY_CLOSE_SENT,
        )
        assert len(events) == 1

    async def test_a_quiet_user_gets_no_event(self, store):
        from hesabyar.db.models import RetentionEventKind
        await tx.get_or_create_user(store, QUIET)
        ctx = _ctx(store)
        await reminders.daily_summary_job(ctx)
        assert store.list(
            "retention_events", lambda e: e.kind == RetentionEventKind.DAILY_CLOSE_SENT
        ) == []

    async def test_user_with_the_preference_off_gets_no_message_or_event(self, store):
        from hesabyar.db.models import RetentionEventKind
        await _earn(store, ACTIVE, 1_000_000)
        user = store.get("users", ACTIVE)
        user.notify_daily_close = False
        await store.update("users", user)

        ctx = _ctx(store)
        await reminders.daily_summary_job(ctx)
        assert ctx.bot.sent == []
        assert store.list(
            "retention_events", lambda e: e.kind == RetentionEventKind.DAILY_CLOSE_SENT
        ) == []

    async def test_default_preference_is_on_for_a_fresh_user(self, store):
        await _earn(store, ACTIVE, 1_000_000)
        ctx = _ctx(store)
        await reminders.daily_summary_job(ctx)
        assert ctx.bot.sent, "با ترجیحِ پیش‌فرض باید پیام برود"


# --- دکمه‌ی «گزارش کامل» ---------------------------------------------------------


class _Msg:
    def __init__(self):
        self.replies: list = []
        self.chat = SimpleNamespace(id=ACTIVE, type="private", title=None)
        self.chat_id = ACTIVE
        self.message_id = 1

    async def reply_text(self, text, **kw):
        self.replies.append({"text": text, **kw})
        return SimpleNamespace(message_id=2, chat_id=ACTIVE)


class _Query:
    def __init__(self, data):
        self.data = data
        self.message = _Msg()

    async def answer(self, text=None, show_alert=False):
        return None

    async def edit_message_text(self, text, **kw):
        return None


class TestFullReportButton:
    async def test_opens_the_report_submenu(self, store):
        ctx = SimpleNamespace(
            application=SimpleNamespace(
                bot_data={"store": store, "settings": Settings(bot_token="x")},
                bot=_Bot(),
            ),
            bot=_Bot(), user_data={}, chat_data={}, args=[],
        )
        query = _Query("menu:report")
        update = SimpleNamespace(
            message=None, callback_query=query,
            effective_user=SimpleNamespace(id=ACTIVE, full_name="ت", username="t"),
            effective_chat=SimpleNamespace(id=ACTIVE, type="private", title=None),
            effective_message=query.message,
        )
        await handlers.on_menu(update, ctx)
        reply = query.message.replies[-1]
        assert reply["text"] == texts.MENU_REPORT
        assert _cb(reply["reply_markup"]) == _cb(keyboards.report_menu())

    def test_every_submenu_key_is_reachable(self):
        assert set(handlers._SUBMENUS) == {
            "report", "transactions", "ledger", "invoice", "business", "account"
        }

    def test_submenu_map_matches_the_main_menu(self):
        assert (sorted(t for t, _ in handlers._SUBMENUS.values())
                == sorted(t for t, _ in handlers._MAIN_MENU.values()))


# --- تنظیمات -------------------------------------------------------------------


class TestSettings:
    def test_default_hour_is_ten_pm(self, monkeypatch):
        for name in ("DAILY_SUMMARY_HOUR", "NIGHTLY_SUMMARY_HOUR"):
            monkeypatch.delenv(name, raising=False)
        assert load_settings(require_token=False).nightly_summary_hour == 22

    def test_daily_summary_hour_wins(self, monkeypatch):
        monkeypatch.setenv("DAILY_SUMMARY_HOUR", "20")
        monkeypatch.setenv("NIGHTLY_SUMMARY_HOUR", "21")
        assert load_settings(require_token=False).nightly_summary_hour == 20

    def test_the_old_env_name_still_works(self, monkeypatch):
        monkeypatch.delenv("DAILY_SUMMARY_HOUR", raising=False)
        monkeypatch.setenv("NIGHTLY_SUMMARY_HOUR", "19")
        assert load_settings(require_token=False).nightly_summary_hour == 19

    def test_it_can_be_switched_off(self, monkeypatch):
        monkeypatch.setenv("DAILY_SUMMARY", "false")
        assert load_settings(require_token=False).nightly_summary is False
