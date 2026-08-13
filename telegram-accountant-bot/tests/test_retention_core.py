"""تست‌های هسته‌ی ماندگاری (Retention Core): جمع‌بندیِ روزانه‌ی تعاملی،
ترجیحاتِ اعلان، اسنوزِ یادآوری، و رویدادهای سبکِ ماندگاری.
"""
import datetime as dt
from types import SimpleNamespace

from hesabyar.bot import handlers, texts
from hesabyar.config import Settings
from hesabyar.core import jalali
from hesabyar.db.models import Kind, LedgerEntry, RetentionEvent, RetentionEventKind, User
from hesabyar.services import reports as report_service
from hesabyar.services import retention
from hesabyar.services import transactions as tx

UID = 20_001


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

    @property
    def markup(self):
        return self.replies[-1].get("reply_markup") if self.replies else None


class _Query:
    def __init__(self, data, message=None):
        self.data = data
        self.message = message or _Msg()
        self.answers: list = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append({"text": text, "alert": show_alert})


def _ctx(store):
    app = SimpleNamespace(
        bot_data={"store": store, "settings": Settings(bot_token="x")},
        bot=SimpleNamespace(),
    )
    return SimpleNamespace(application=app, bot=app.bot,
                           chat_data={}, user_data={}, args=[])


def _update(message=None, query=None):
    return SimpleNamespace(
        message=message, callback_query=query,
        effective_user=SimpleNamespace(id=UID, full_name="تست", username="t"),
        effective_chat=SimpleNamespace(id=UID, type="private", title=None),
        effective_message=message or (query.message if query else None),
    )


async def _press_daily_close(ctx, action, message=None):
    query = _Query(f"dclose:{action}", message=message)
    await handlers.on_daily_close_action(_update(query=query), ctx)
    return query


async def _type(ctx, text):
    msg = _Msg(text)
    await handlers.on_text(_update(message=msg), ctx)
    return msg


class TestNotificationPreferenceBackwardCompat:
    """رفتارِ فعلی نباید بعد از دیپلوی برای کاربرانِ قدیمی عوض شود."""

    def test_missing_columns_default_to_on(self):
        old_row = {"id": "1", "business_name": "مغازه‌ی قدیمی"}
        user = User.from_row(old_row)
        assert user.notify_daily_close is True
        assert user.notify_due_reminders is True
        assert user.last_daily_close_date is None

    def test_present_but_blank_cell_defaults_to_on(self):
        """بعد از یک flush که فقط هدر را عوض کرده، سلولِ ردیف‌های قدیمی خالی است."""
        row = {
            "id": "1", "notify_daily_close": "", "notify_due_reminders": "",
        }
        user = User.from_row(row)
        assert user.notify_daily_close is True
        assert user.notify_due_reminders is True

    def test_explicit_false_is_respected(self):
        row = {"id": "2", "notify_daily_close": "FALSE", "notify_due_reminders": "FALSE"}
        user = User.from_row(row)
        assert user.notify_daily_close is False
        assert user.notify_due_reminders is False

    def test_explicit_true_round_trips(self):
        user = User(id=3, notify_daily_close=False, notify_due_reminders=True)
        row = dict(zip(User.COLUMNS, user.to_row()))
        again = User.from_row(row)
        assert again.notify_daily_close is False
        assert again.notify_due_reminders is True

    def test_last_daily_close_date_round_trips(self):
        user = User(id=4, last_daily_close_date=dt.date(2026, 8, 13))
        row = dict(zip(User.COLUMNS, user.to_row()))
        assert User.from_row(row).last_daily_close_date == dt.date(2026, 8, 13)


class TestSnoozeFieldBackwardCompat:
    def test_old_rows_without_the_column_are_not_snoozed(self):
        row = {"id": "1", "user_id": "1", "direction": "receivable", "amount": "1000"}
        entry = LedgerEntry.from_row(row)
        assert entry.snooze_until is None

    def test_round_trips(self):
        entry = LedgerEntry(id=1, snooze_until=dt.date(2026, 8, 20))
        row = dict(zip(LedgerEntry.COLUMNS, entry.to_row()))
        assert LedgerEntry.from_row(row).snooze_until == dt.date(2026, 8, 20)

    def test_snoozing_does_not_touch_other_fields_at_the_model_level(self):
        """این تست فقط سطحِ مدل را می‌بیند؛ رفتارِ سرویس در test_ledger.py."""
        entry = LedgerEntry(
            id=1, amount=500_000, direction="payable",
            due_date=dt.date(2026, 8, 1),
        )
        entry.snooze_until = dt.date(2026, 8, 10)
        assert entry.amount == 500_000
        assert entry.direction == "payable"
        assert entry.due_date == dt.date(2026, 8, 1)


class TestRetentionEventModel:
    def test_round_trips(self):
        event = RetentionEvent(
            id=1, user_id=UID, kind=RetentionEventKind.DAILY_CLOSE_SENT, meta="x",
        )
        row = dict(zip(RetentionEvent.COLUMNS, event.to_row()))
        again = RetentionEvent.from_row(row)
        assert again.user_id == UID
        assert again.kind == "daily_close_sent"
        assert again.meta == "x"

    def test_old_style_row_missing_meta_is_fine(self):
        row = {"id": "1", "user_id": "1", "kind": "ledger_settled"}
        event = RetentionEvent.from_row(row)
        assert event.meta == ""


class TestRetentionEventService:
    async def test_log_event_persists_and_never_touches_financial_tables(self, store):
        await tx.get_or_create_user(store, UID)
        before_tx = len(store.list("transactions"))
        before_ledger = len(store.list("ledger_entries"))
        await retention.log_event(store, UID, RetentionEventKind.DAILY_CLOSE_SENT)
        assert len(store.list("retention_events", lambda e: e.user_id == UID)) == 1
        assert len(store.list("transactions")) == before_tx
        assert len(store.list("ledger_entries")) == before_ledger

    async def test_events_since_filters_by_kind_and_window(self, store):
        await tx.get_or_create_user(store, UID)
        now = jalali.now()
        e1 = await retention.log_event(store, UID, RetentionEventKind.DAILY_CLOSE_SENT)
        e1.created_at = now - dt.timedelta(days=10)
        e2 = await retention.log_event(store, UID, RetentionEventKind.DAILY_CLOSE_SENT)
        e2.created_at = now - dt.timedelta(days=1)
        await retention.log_event(store, UID, RetentionEventKind.DAILY_CLOSE_COMPLETED)

        recent = retention.events_since(
            store, RetentionEventKind.DAILY_CLOSE_SENT, now - dt.timedelta(days=7)
        )
        assert [e.id for e in recent] == [e2.id]

    async def test_distinct_users(self, store):
        await tx.get_or_create_user(store, UID)
        await tx.get_or_create_user(store, UID + 1)
        e1 = await retention.log_event(store, UID, RetentionEventKind.DAILY_CLOSE_SENT)
        e2 = await retention.log_event(store, UID, RetentionEventKind.DAILY_CLOSE_SENT)
        e3 = await retention.log_event(store, UID + 1, RetentionEventKind.DAILY_CLOSE_SENT)
        assert retention.distinct_users([e1, e2, e3]) == {UID, UID + 1}

    async def test_reminder_driven_settlements_counts_same_or_next_day(self, store):
        await tx.get_or_create_user(store, UID)
        now = jalali.now()

        sent = await retention.log_event(store, UID, RetentionEventKind.DUE_REMINDER_SENT)
        sent.created_at = now - dt.timedelta(days=3)

        settled_next_day = await retention.log_event(
            store, UID, RetentionEventKind.LEDGER_SETTLED
        )
        settled_next_day.created_at = now - dt.timedelta(days=2)  # فردایِ یادآوری

        settled_unrelated = await retention.log_event(
            store, UID, RetentionEventKind.LEDGER_SETTLED
        )
        settled_unrelated.created_at = now - dt.timedelta(days=8)  # ربطی به یادآوری ندارد

        count = retention.reminder_driven_settlements(
            store, now - dt.timedelta(days=30), now
        )
        assert count == 1

    async def test_reminder_driven_settlements_is_zero_with_no_events(self, store):
        assert retention.reminder_driven_settlements(
            store, jalali.now() - dt.timedelta(days=7), jalali.now()
        ) == 0


# --- جمع‌بندیِ تعاملیِ آخر روز (Daily Close) --------------------------------------


class TestDailyCloseQuickEntry:
    async def test_income_button_forces_income_even_with_no_keyword(self, store):
        """متنِ خالی از کلیدواژه معمولاً هزینه فرض می‌شود؛ از دکمه‌ی فروش نه."""
        ctx = _ctx(store)
        await _press_daily_close(ctx, "income")
        assert ctx.user_data["flow"] == "dc_income"

        await _type(ctx, "۵۰۰ هزار")
        txs = store.list("transactions", lambda t: t.user_id == UID)
        assert len(txs) == 1
        assert txs[0].kind == Kind.INCOME
        assert txs[0].amount == 500_000
        assert "flow" not in ctx.user_data

    async def test_expense_button_forces_expense_even_with_a_sale_keyword(self, store):
        """«فروش» معمولاً درآمد تشخیص داده می‌شود؛ از دکمه‌ی هزینه باید هزینه ثبت شود."""
        ctx = _ctx(store)
        await _press_daily_close(ctx, "expense")
        assert ctx.user_data["flow"] == "dc_expense"

        await _type(ctx, "۲۰۰ هزار فروش")
        txs = store.list("transactions", lambda t: t.user_id == UID)
        assert len(txs) == 1
        assert txs[0].kind == Kind.EXPENSE
        assert txs[0].amount == 200_000

    async def test_unparseable_text_does_not_crash_and_clears_the_flow(self, store):
        ctx = _ctx(store)
        await _press_daily_close(ctx, "income")
        msg = await _type(ctx, "سلام چطوری")
        assert store.list("transactions", lambda t: t.user_id == UID) == []
        assert msg.replies, "باید پیامِ «متوجه نشدم» یا مشابه برگردد"


class TestDailyCloseCompletion:
    async def test_first_press_marks_today_done_and_logs_one_event(self, store):
        await tx.get_or_create_user(store, UID)
        ctx = _ctx(store)
        query = await _press_daily_close(ctx, "done")

        user = store.get("users", UID)
        assert user.last_daily_close_date == jalali.now().date()
        events = store.list(
            "retention_events",
            lambda e: e.user_id == UID and e.kind == RetentionEventKind.DAILY_CLOSE_COMPLETED,
        )
        assert len(events) == 1
        assert query.answers[-1]["text"] == texts.DCLOSE_DONE_TOAST

    async def test_pressing_twice_the_same_day_is_idempotent(self, store):
        await tx.get_or_create_user(store, UID)
        ctx = _ctx(store)
        await _press_daily_close(ctx, "done")
        second = await _press_daily_close(ctx, "done")

        events = store.list(
            "retention_events",
            lambda e: e.user_id == UID and e.kind == RetentionEventKind.DAILY_CLOSE_COMPLETED,
        )
        assert len(events) == 1, "نباید رویدادِ دوم ثبت شود"
        assert second.answers[-1]["text"] == texts.DCLOSE_ALREADY_DONE_TOAST

    async def test_completion_creates_no_financial_record(self, store):
        await tx.get_or_create_user(store, UID)
        ctx = _ctx(store)
        await _press_daily_close(ctx, "done")
        assert store.list("transactions") == []
        assert store.list("ledger_entries") == []
        assert store.list("invoices") == []

    async def test_mark_daily_close_done_service_contract(self, store):
        await tx.get_or_create_user(store, UID)
        now = jalali.now()
        first = await report_service.mark_daily_close_done(store, UID, now)
        second = await report_service.mark_daily_close_done(store, UID, now)
        assert first is True
        assert second is False
        assert report_service.daily_close_completed_today(store.get("users", UID), now)

    async def test_a_new_day_can_be_marked_done_again(self, store):
        await tx.get_or_create_user(store, UID)
        now = jalali.now()
        tomorrow = now + dt.timedelta(days=1)
        assert await report_service.mark_daily_close_done(store, UID, now) is True
        assert await report_service.mark_daily_close_done(store, UID, tomorrow) is True


# --- ترجیحاتِ اعلان از رابطِ کاربری --------------------------------------------


class TestNotificationPreferencesUI:
    async def test_screen_shows_both_toggles_on_by_default(self, store):
        ctx = _ctx(store)
        msg = _Msg()
        await handlers.notif_prefs_cmd(_update(message=msg), ctx)
        reply = msg.replies[-1]
        labels = [b.text for row in reply["reply_markup"].inline_keyboard for b in row]
        assert any(texts.NOTIF_ON in label for label in labels if "جمع‌بندی" in label)
        assert any(texts.NOTIF_ON in label for label in labels if "یادآوریِ" in label)

    async def test_tapping_daily_close_flips_it_off(self, store):
        await tx.get_or_create_user(store, UID)
        ctx = _ctx(store)
        query = _Query("notif:daily_close")
        await handlers.on_notification_toggle(_update(query=query), ctx)

        user = store.get("users", UID)
        assert user.notify_daily_close is False
        assert user.notify_due_reminders is True, "دیگری نباید دست بخورد"

    async def test_tapping_twice_toggles_back_on(self, store):
        await tx.get_or_create_user(store, UID)
        ctx = _ctx(store)
        await handlers.on_notification_toggle(
            _update(query=_Query("notif:due_reminders")), ctx
        )
        await handlers.on_notification_toggle(
            _update(query=_Query("notif:due_reminders")), ctx
        )
        assert store.get("users", UID).notify_due_reminders is True

    async def test_unknown_key_is_ignored(self, store):
        await tx.get_or_create_user(store, UID)
        ctx = _ctx(store)
        query = _Query("notif:xyz")
        await handlers.on_notification_toggle(_update(query=query), ctx)
        user = store.get("users", UID)
        assert user.notify_daily_close is True and user.notify_due_reminders is True


# --- دکمه‌های اسنوز از دیدِ هندلر -----------------------------------------------


class TestSnoozeHandler:
    async def test_tapping_snoozes_the_entry(self, store):
        from hesabyar.db.models import Direction
        from hesabyar.services import ledger as ledger_service

        entry = await ledger_service.add_entry(
            store, UID, direction=Direction.RECEIVABLE,
            party_name="علی", amount=500_000, due_date=jalali.now().date(),
        )
        ctx = _ctx(store)
        query = _Query(f"snooze:{entry.id}:tomorrow")
        await handlers.on_ledger_snooze(_update(query=query), ctx)

        stored = store.get("ledger_entries", entry.id)
        expected = jalali.now().date() + dt.timedelta(days=1)
        assert stored.snooze_until == expected
        assert query.answers[-1]["text"] == texts.SNOOZE_DONE.format(
            date=jalali.format_date(expected)
        )

    async def test_another_users_entry_is_rejected(self, store):
        from hesabyar.db.models import Direction
        from hesabyar.services import ledger as ledger_service

        entry = await ledger_service.add_entry(
            store, UID, direction=Direction.RECEIVABLE,
            party_name="علی", amount=500_000, due_date=jalali.now().date(),
        )
        other_ctx = _ctx(store)
        other_ctx.user_data = {}
        query = _Query(f"snooze:{entry.id}:tomorrow")
        query_update = _update(query=query)
        query_update.effective_user = SimpleNamespace(id=UID + 999, full_name="x", username="x")
        await handlers.on_ledger_snooze(query_update, other_ctx)

        stored = store.get("ledger_entries", entry.id)
        assert stored.snooze_until is None
        assert query.answers[-1]["alert"] is True

    async def test_bad_callback_data_is_ignored(self, store):
        ctx = _ctx(store)
        query = _Query("snooze:xyz:tomorrow")
        await handlers.on_ledger_snooze(_update(query=query), ctx)
        assert query.answers == [{"text": None, "alert": False}]

    async def test_unknown_duration_key_is_ignored(self, store):
        from hesabyar.db.models import Direction
        from hesabyar.services import ledger as ledger_service

        entry = await ledger_service.add_entry(
            store, UID, direction=Direction.RECEIVABLE,
            party_name="علی", amount=500_000, due_date=jalali.now().date(),
        )
        ctx = _ctx(store)
        query = _Query(f"snooze:{entry.id}:nextcentury")
        await handlers.on_ledger_snooze(_update(query=query), ctx)
        assert store.get("ledger_entries", entry.id).snooze_until is None
