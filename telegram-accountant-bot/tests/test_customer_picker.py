"""تست‌های پیشنهادِ «مشتریان اخیر» موقعِ پرسیدنِ نامِ طرف‌حساب (فاز ۹)."""
from types import SimpleNamespace

from hesabyar.bot import handlers, keyboards, texts
from hesabyar.config import Settings
from hesabyar.db.models import Direction
from hesabyar.services import customers as customers_service
from hesabyar.services import ledger as ledger_service
from hesabyar.services import transactions as tx

UID = 11_001


def _cb(markup):
    if markup is None:
        return []
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def _labels(markup):
    return [b.text for row in markup.inline_keyboard for b in row]


# --- کیبورد ---------------------------------------------------------------------


class TestPickerKeyboard:
    def _people(self, n=3):
        return [SimpleNamespace(id=i, name=f"مشتری {i}") for i in range(1, n + 1)]

    def test_one_button_per_customer(self):
        markup = keyboards.recent_customers_picker(self._people(3))
        assert _cb(markup)[:3] == ["cust:pick:1", "cust:pick:2", "cust:pick:3"]

    def test_new_name_button_comes_after_the_people(self):
        markup = keyboards.recent_customers_picker(self._people(2))
        data = _cb(markup)
        assert data[2] == "cust:new"
        assert texts.BTN_CUSTOMER_NEW in _labels(markup)

    def test_cancel_is_the_last_row(self):
        markup = keyboards.recent_customers_picker(self._people(2))
        assert _cb(markup)[-1] == keyboards.CANCEL_DATA

    def test_long_names_are_trimmed(self):
        person = SimpleNamespace(id=9, name="ب" * 120)
        assert len(_labels(keyboards.recent_customers_picker([person]))[0]) <= 40

    def test_works_with_a_single_customer(self):
        assert _cb(keyboards.recent_customers_picker(self._people(1))) == [
            "cust:pick:1", "cust:new", keyboards.CANCEL_DATA
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
    def __init__(self, data, message=None):
        self.data = data
        self.message = message or _Msg()
        self.answers: list = []
        self.edits: list = []
        self.markup_edits: list = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append({"text": text, "alert": show_alert})

    async def edit_message_text(self, text, **kw):
        self.edits.append({"text": text, **kw})

    async def edit_message_reply_markup(self, reply_markup=None):
        self.markup_edits.append(reply_markup)


class _Bot:
    def __init__(self):
        self.sent: list = []

    async def send_message(self, chat_id, text=None, **kw):
        self.sent.append({"chat_id": chat_id, "text": text, **kw})

    async def send_photo(self, chat_id, photo=None, **kw):
        self.sent.append({"chat_id": chat_id, "photo": True, **kw})

    async def send_document(self, chat_id, document=None, **kw):
        self.sent.append({"chat_id": chat_id, "document": True, **kw})

    async def edit_message_text(self, **kw):
        return None


def _ctx(store):
    app = SimpleNamespace(
        bot_data={"store": store, "settings": Settings(bot_token="x")}, bot=_Bot()
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


async def _seed_customers(store, *names):
    await tx.get_or_create_user(store, UID)
    made = []
    for name in names:
        made.append(await customers_service.find_or_create_customer(store, UID, name))
    return made


async def _start_invoice(ctx):
    query = _Query("act:newinvoice")
    await handlers.on_menu_action(_update(query=query), ctx)
    return query


async def _start_ledger(ctx, direction=Direction.RECEIVABLE):
    query = _Query(f"ledger:add:{direction}")
    await handlers.on_ledger_action(_update(query=query), ctx)
    return query


# --- سؤالِ نامِ مشتری --------------------------------------------------------------


class TestPickerAppearsWhereNamesAreAsked:
    async def test_invoice_shows_recent_customers(self, store):
        ctx = _ctx(store)
        await _seed_customers(store, "رضا", "سارا")
        query = await _start_invoice(ctx)
        reply = query.message.replies[-1]
        assert texts.INVOICE_ASK_CUSTOMER in reply["text"]
        assert texts.CUSTOMER_PICK_HINT.strip() in reply["text"]
        assert "cust:new" in _cb(reply["reply_markup"])
        assert sum(1 for d in _cb(reply["reply_markup"])
                   if d.startswith("cust:pick:")) == 2

    async def test_ledger_shows_recent_customers(self, store):
        ctx = _ctx(store)
        await _seed_customers(store, "رضا")
        query = await _start_ledger(ctx)
        edit = query.edits[-1]
        assert texts.LEDGER_ASK_PARTY_RECEIVABLE in edit["text"]
        assert "cust:pick:" in " ".join(_cb(edit["reply_markup"]))

    async def test_no_customers_means_just_the_cancel_button(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        query = await _start_invoice(ctx)
        reply = query.message.replies[-1]
        assert reply["text"] == texts.INVOICE_ASK_CUSTOMER
        assert _cb(reply["reply_markup"]) == [keyboards.CANCEL_DATA]

    async def test_at_most_four_suggestions(self, store):
        ctx = _ctx(store)
        await _seed_customers(store, *[f"مشتری {i}" for i in range(8)])
        query = await _start_invoice(ctx)
        data = _cb(query.message.replies[-1]["reply_markup"])
        assert sum(1 for d in data if d.startswith("cust:pick:")) == 4

    async def test_payable_question_is_used_for_payables(self, store):
        ctx = _ctx(store)
        await _seed_customers(store, "رضا")
        query = await _start_ledger(ctx, Direction.PAYABLE)
        assert texts.LEDGER_ASK_PARTY_PAYABLE in query.edits[-1]["text"]


# --- انتخابِ یک مشتری ------------------------------------------------------------


class TestPickingShortensTheFlow:
    async def test_invoice_jumps_straight_to_the_items_step(self, store):
        ctx = _ctx(store)
        (reza,) = await _seed_customers(store, "رضا")
        await _start_invoice(ctx)

        query = _Query(f"cust:pick:{reza.id}")
        await handlers.on_customer_pick(_update(query=query), ctx)

        assert ctx.user_data["flow"] == "invoice_items"
        assert ctx.user_data["invoice"]["customer_name"] == "رضا"
        # کیبوردِ ساختِ فاکتور آمده است
        assert "inv:done" in _cb(query.message.replies[-1]["reply_markup"])

    async def test_ledger_jumps_straight_to_the_amount_step(self, store):
        ctx = _ctx(store)
        (reza,) = await _seed_customers(store, "رضا")
        await _start_ledger(ctx)

        query = _Query(f"cust:pick:{reza.id}")
        await handlers.on_customer_pick(_update(query=query), ctx)

        assert ctx.user_data["flow"] == "ledger_amount"
        assert ctx.user_data["ledger"]["party_name"] == "رضا"
        assert query.message.replies[-1]["text"] == texts.LEDGER_ASK_AMOUNT

    async def test_the_stale_keyboard_is_removed(self, store):
        ctx = _ctx(store)
        (reza,) = await _seed_customers(store, "رضا")
        await _start_invoice(ctx)
        query = _Query(f"cust:pick:{reza.id}")
        await handlers.on_customer_pick(_update(query=query), ctx)
        assert query.markup_edits == [None]

    async def test_picked_customer_is_reused_not_duplicated(self, store):
        """فاکتورِ ساخته‌شده باید به همان رکوردِ مشتری وصل شود."""
        ctx = _ctx(store)
        (reza,) = await _seed_customers(store, "رضا")
        await _start_invoice(ctx)
        await handlers.on_customer_pick(
            _update(query=_Query(f"cust:pick:{reza.id}")), ctx
        )
        msg = _Msg("صندلی ۱ ۵۰۰ هزار")
        await handlers.on_text(_update(message=msg), ctx)
        await handlers.on_invoice_action(_update(query=_Query("inv:done")), ctx)

        assert len(store.list("customers")) == 1, "مشتری تکراری ساخته شد"
        assert store.list("invoices")[0].customer_id == reza.id

    async def test_ledger_entry_links_to_the_picked_customer(self, store):
        ctx = _ctx(store)
        (reza,) = await _seed_customers(store, "رضا")
        await _start_ledger(ctx)
        await handlers.on_customer_pick(
            _update(query=_Query(f"cust:pick:{reza.id}")), ctx
        )
        for text in ("۲۰۰ هزار", "بدون تاریخ"):
            await handlers.on_text(_update(message=_Msg(text)), ctx)

        entries = store.list("ledger_entries")
        assert len(entries) == 1
        assert entries[0].customer_id == reza.id
        assert len(store.list("customers")) == 1


# --- اسمِ جدید و تایپِ مستقیم ------------------------------------------------------


class TestTypingStillWorks:
    async def test_new_name_button_reasks_and_keeps_the_flow(self, store):
        ctx = _ctx(store)
        await _seed_customers(store, "رضا")
        await _start_invoice(ctx)

        query = _Query("cust:new")
        await handlers.on_customer_pick(_update(query=query), ctx)
        assert ctx.user_data["flow"] == "invoice_customer"
        reply = query.message.replies[-1]
        assert reply["text"] == texts.INVOICE_ASK_CUSTOMER
        assert _cb(reply["reply_markup"]) == [keyboards.CANCEL_DATA]

    async def test_new_name_in_ledger_uses_the_right_question(self, store):
        ctx = _ctx(store)
        await _seed_customers(store, "رضا")
        await _start_ledger(ctx, Direction.PAYABLE)
        query = _Query("cust:new")
        await handlers.on_customer_pick(_update(query=query), ctx)
        assert query.message.replies[-1]["text"] == texts.LEDGER_ASK_PARTY_PAYABLE

    async def test_typing_a_brand_new_name_still_works(self, store):
        ctx = _ctx(store)
        await _seed_customers(store, "رضا")
        await _start_invoice(ctx)
        await handlers.on_text(_update(message=_Msg("مهدی")), ctx)
        assert ctx.user_data["flow"] == "invoice_items"
        assert ctx.user_data["invoice"]["customer_name"] == "مهدی"

    async def test_typing_in_the_ledger_still_works(self, store):
        ctx = _ctx(store)
        await _seed_customers(store, "رضا")
        await _start_ledger(ctx)
        await handlers.on_text(_update(message=_Msg("مهدی")), ctx)
        assert ctx.user_data["flow"] == "ledger_amount"
        assert ctx.user_data["ledger"]["party_name"] == "مهدی"


class TestGuards:
    async def test_pressing_after_the_flow_ended_is_reported(self, store):
        ctx = _ctx(store)
        (reza,) = await _seed_customers(store, "رضا")
        query = _Query(f"cust:pick:{reza.id}")     # هیچ جریانی باز نیست
        await handlers.on_customer_pick(_update(query=query), ctx)
        assert query.answers[-1]["alert"] is True
        assert query.answers[-1]["text"] == texts.CUSTOMER_GONE
        assert "invoice" not in ctx.user_data

    async def test_another_users_customer_cannot_be_picked(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID + 5)
        other = await customers_service.find_or_create_customer(
            store, UID + 5, "غریبه"
        )
        await _seed_customers(store, "رضا")
        await _start_invoice(ctx)
        query = _Query(f"cust:pick:{other.id}")
        await handlers.on_customer_pick(_update(query=query), ctx)
        assert query.answers[-1]["text"] == texts.CUSTOMER_GONE
        assert ctx.user_data["flow"] == "invoice_customer", "جریان نباید جلو برود"

    async def test_bad_callback_data_is_ignored(self, store):
        ctx = _ctx(store)
        await _seed_customers(store, "رضا")
        await _start_invoice(ctx)
        query = _Query("cust:pick:xyz")
        await handlers.on_customer_pick(_update(query=query), ctx)
        assert ctx.user_data["flow"] == "invoice_customer"

    async def test_cancel_still_clears_everything(self, store):
        ctx = _ctx(store)
        await _seed_customers(store, "رضا")
        await _start_invoice(ctx)
        await handlers.on_flow_cancel(
            _update(query=_Query(keyboards.CANCEL_DATA)), ctx
        )
        assert "flow" not in ctx.user_data and "invoice" not in ctx.user_data


class TestOrdering:
    async def test_most_recently_used_customer_comes_first(self, store):
        ctx = _ctx(store)
        old, new = await _seed_customers(store, "قدیمی", "تازه")
        # «تازه» را در دفتر استفاده کن تا جلو بیفتد
        await ledger_service.add_entry(
            store, UID, direction=Direction.RECEIVABLE,
            party_name="تازه", amount=100_000,
        )
        query = await _start_invoice(ctx)
        data = [d for d in _cb(query.message.replies[-1]["reply_markup"])
                if d.startswith("cust:pick:")]
        assert data[0] == f"cust:pick:{new.id}"
        assert f"cust:pick:{old.id}" in data


class TestRegistration:
    def test_handler_is_registered(self):
        import re
        from telegram.ext import ApplicationBuilder, CallbackQueryHandler
        application = ApplicationBuilder().token("1:AA").build()
        handlers.register(application)
        patterns = [h.pattern.pattern for group in application.handlers.values()
                    for h in group
                    if isinstance(h, CallbackQueryHandler) and h.pattern]
        for data in ("cust:pick:1", "cust:new"):
            assert [p for p in patterns if re.match(p, data)] == [r"^cust:"], data
