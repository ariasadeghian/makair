"""تست‌های دکمه‌ی «🔁 تکرار همین ثبت» (فاز ۸)."""
import datetime as dt
from types import SimpleNamespace

from hesabyar.bot import handlers, keyboards, texts
from hesabyar.config import Settings
from hesabyar.core import jalali
from hesabyar.db.models import Kind
from hesabyar.services import branches as branch_service
from hesabyar.services import subscription as sub_service
from hesabyar.services import transactions as tx

UID = 10_001


def _cb(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


# --- کیبورد ---------------------------------------------------------------------


class TestKeyboard:
    def test_both_buttons_in_one_row(self):
        markup = keyboards.transaction_confirmed_actions(7)
        assert len(markup.inline_keyboard) == 1
        row = markup.inline_keyboard[0]
        assert [b.callback_data for b in row] == ["tx:undo:7", "tx:repeat:7"]
        assert [b.text for b in row] == [texts.BTN_UNDO_TX, texts.BTN_REPEAT_TX]

    def test_old_name_still_works(self):
        assert _cb(keyboards.undo_transaction(3)) == _cb(
            keyboards.transaction_confirmed_actions(3)
        )

    def test_id_is_embedded_per_transaction(self):
        assert _cb(keyboards.transaction_confirmed_actions(42)) == [
            "tx:undo:42", "tx:repeat:42"
        ]


# --- ابزار شبیه‌سازی -------------------------------------------------------------


class _Msg:
    def __init__(self, text=""):
        self.text = text
        self.replies: list = []
        self.chat = SimpleNamespace(id=UID, type="private", title=None)
        self.chat_id = UID
        self.message_id = 1
        self.entities = []
        self.reply_to_message = None

    async def reply_text(self, text, **kw):
        self.replies.append({"text": text, **kw})
        return SimpleNamespace(message_id=2, chat_id=UID)


class _Query:
    def __init__(self, data, message=None, user_id=UID):
        self.data = data
        self.message = message or _Msg()
        self.answers: list = []
        self.edits: list = []
        self.user_id = user_id

    async def answer(self, text=None, show_alert=False):
        self.answers.append({"text": text, "alert": show_alert})

    async def edit_message_text(self, text, **kw):
        self.edits.append({"text": text, **kw})

    async def edit_message_reply_markup(self, reply_markup=None):
        return None


class _Bot:
    def __init__(self):
        self.sent: list = []

    async def send_message(self, chat_id, text=None, **kw):
        self.sent.append({"chat_id": chat_id, "text": text, **kw})


def _ctx(store):
    app = SimpleNamespace(
        bot_data={"store": store, "settings": Settings(bot_token="x")}, bot=_Bot()
    )
    return SimpleNamespace(application=app, bot=app.bot,
                           chat_data={}, user_data={}, args=[])


def _update(query, user_id=UID):
    return SimpleNamespace(
        message=None, callback_query=query,
        effective_user=SimpleNamespace(id=user_id, full_name="تست", username="t"),
        effective_chat=SimpleNamespace(id=user_id, type="private", title=None),
        effective_message=query.message,
    )


async def _make_tx(store, user_id=UID, **kw):
    await tx.get_or_create_user(store, user_id)
    await sub_service.get_or_create_subscription(store, user_id)
    fields = {
        "kind": Kind.EXPENSE, "amount": 80_000, "category": "حمل‌ونقل",
        "description": "کرایه پیک", "occurred_at": jalali.now() - dt.timedelta(days=3),
    }
    fields.update(kw)
    return await tx.add_transaction(store, user_id, **fields)


async def _repeat(ctx, tx_id, user_id=UID):
    query = _Query(f"tx:repeat:{tx_id}", user_id=user_id)
    await handlers.on_tx_repeat(_update(query, user_id=user_id), ctx)
    return query


# --- رفتار ----------------------------------------------------------------------


class TestRepeat:
    async def test_creates_a_second_record_with_a_new_id(self, store):
        ctx = _ctx(store)
        original = await _make_tx(store)
        await _repeat(ctx, original.id)

        rows = store.list("transactions")
        assert len(rows) == 2
        copy = next(r for r in rows if r.id != original.id)
        assert copy.id and copy.id != original.id

    async def test_copies_kind_amount_category_and_description(self, store):
        ctx = _ctx(store)
        original = await _make_tx(store)
        await _repeat(ctx, original.id)
        copy = next(r for r in store.list("transactions") if r.id != original.id)
        assert (copy.kind, copy.amount, copy.category, copy.description) == (
            original.kind, original.amount, original.category, original.description
        )

    async def test_uses_today_not_the_original_date(self, store):
        ctx = _ctx(store)
        original = await _make_tx(store)
        await _repeat(ctx, original.id)
        copy = next(r for r in store.list("transactions") if r.id != original.id)
        assert copy.occurred_at.date() == jalali.now().date()
        assert copy.occurred_at.date() != original.occurred_at.date()

    async def test_the_original_is_untouched(self, store):
        ctx = _ctx(store)
        original = await _make_tx(store)
        before = (original.amount, original.occurred_at)
        await _repeat(ctx, original.id)
        again = tx.get_transaction(store, UID, original.id)
        assert (again.amount, again.occurred_at) == before

    async def test_reply_carries_the_new_id_in_its_buttons(self, store):
        ctx = _ctx(store)
        original = await _make_tx(store)
        query = await _repeat(ctx, original.id)
        copy = next(r for r in store.list("transactions") if r.id != original.id)
        reply = query.message.replies[-1]
        assert _cb(reply["reply_markup"]) == [
            f"tx:undo:{copy.id}", f"tx:repeat:{copy.id}"
        ]

    async def test_reply_says_it_was_repeated_and_shows_the_amount(self, store):
        ctx = _ctx(store)
        original = await _make_tx(store)
        query = await _repeat(ctx, original.id)
        body = query.message.replies[-1]["text"]
        assert texts.REPEAT_HEADER in body
        assert "۸۰٬۰۰۰" in body
        assert "حمل‌ونقل" in body

    async def test_repeating_the_copy_works_too(self, store):
        """زنجیره: تکرارِ تکرار هم باید ثبت شود."""
        ctx = _ctx(store)
        original = await _make_tx(store)
        await _repeat(ctx, original.id)
        copy = next(r for r in store.list("transactions") if r.id != original.id)
        await _repeat(ctx, copy.id)
        assert len(store.list("transactions")) == 3

    async def test_income_is_repeated_as_income(self, store):
        ctx = _ctx(store)
        original = await _make_tx(store, kind=Kind.INCOME, amount=1_200_000,
                                  category="فروش", description="فروش روز")
        await _repeat(ctx, original.id)
        copy = next(r for r in store.list("transactions") if r.id != original.id)
        assert copy.kind == Kind.INCOME
        assert copy.amount == 1_200_000


class TestGuards:
    async def test_deleted_transaction_gives_an_alert_not_a_crash(self, store):
        ctx = _ctx(store)
        original = await _make_tx(store)
        await tx.delete_transaction(store, UID, original.id)
        query = await _repeat(ctx, original.id)
        assert query.answers[-1]["alert"] is True
        assert query.answers[-1]["text"] == texts.REPEAT_GONE
        assert store.list("transactions") == []

    async def test_another_users_transaction_cannot_be_repeated(self, store):
        ctx = _ctx(store)
        original = await _make_tx(store, user_id=UID)
        stranger = UID + 999
        await tx.get_or_create_user(store, stranger)
        query = await _repeat(ctx, original.id, user_id=stranger)
        assert query.answers[-1]["text"] == texts.REPEAT_GONE
        assert len(store.list("transactions")) == 1

    async def test_bad_callback_data_is_ignored(self, store):
        ctx = _ctx(store)
        await _make_tx(store)
        query = _Query("tx:repeat:abc")
        await handlers.on_tx_repeat(_update(query), ctx)
        assert len(store.list("transactions")) == 1

    async def test_expired_subscription_hits_the_paywall(self, store):
        ctx = _ctx(store)
        original = await _make_tx(store)
        sub = sub_service._get(store, UID)
        sub.expires_at = jalali.now() - dt.timedelta(days=1)
        await store.update("subscriptions", sub)

        query = await _repeat(ctx, original.id)
        assert len(store.list("transactions")) == 1, "بدون اشتراک ثبت شد!"
        data = _cb(query.message.replies[-1]["reply_markup"])
        assert any(d.startswith("sub:buy:") for d in data)


class TestBranchEmployee:
    async def _branch_setup(self, store):
        owner, staff = UID, UID + 1
        await tx.get_or_create_user(store, owner)
        await sub_service.get_or_create_subscription(store, owner)
        branch = await branch_service.create_branch(store, owner, "شعبه‌ی ونک")
        await branch_service.join_with_code(store, staff, branch.code, name="کارمند")
        return owner, staff, branch

    async def test_staff_can_repeat_a_transaction_from_the_owner_book(self, store):
        ctx = _ctx(store)
        owner, staff, branch = await self._branch_setup(store)
        original = await tx.add_transaction(
            store, owner, kind=Kind.EXPENSE, amount=50_000, category="متفرقه",
            description="", occurred_at=jalali.now() - dt.timedelta(days=1),
            branch_id=branch.id, logged_by=staff,
        )
        await _repeat(ctx, original.id, user_id=staff)

        rows = store.list("transactions")
        assert len(rows) == 2
        copy = next(r for r in rows if r.id != original.id)
        assert copy.user_id == owner, "باید در دفترِ صاحب کسب‌وکار بنشیند"
        assert copy.branch_id == branch.id
        assert copy.logged_by == staff

    async def test_staff_can_undo_a_transaction_from_the_owner_book(self, store):
        ctx = _ctx(store)
        owner, staff, branch = await self._branch_setup(store)
        original = await tx.add_transaction(
            store, owner, kind=Kind.EXPENSE, amount=50_000, category="متفرقه",
            description="", occurred_at=jalali.now(),
            branch_id=branch.id, logged_by=staff,
        )
        query = _Query(f"tx:undo:{original.id}", user_id=staff)
        await handlers.on_undo(_update(query, user_id=staff), ctx)
        assert store.list("transactions") == []


class TestRegistration:
    def test_repeat_has_its_own_handler(self):
        import re
        from telegram.ext import ApplicationBuilder, CallbackQueryHandler
        application = ApplicationBuilder().token("1:AA").build()
        handlers.register(application)
        patterns = [h.pattern.pattern for group in application.handlers.values()
                    for h in group
                    if isinstance(h, CallbackQueryHandler) and h.pattern]
        assert [p for p in patterns if re.match(p, "tx:repeat:5")] == [r"^tx:repeat:"]

    def test_undo_and_repeat_do_not_shadow_each_other(self):
        import re
        assert not re.match(r"^tx:undo:", "tx:repeat:5")
        assert not re.match(r"^tx:repeat:", "tx:undo:5")
