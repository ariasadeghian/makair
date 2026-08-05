"""تست‌های پیش‌نمایش قبل از صدور و باطل‌کردن فاکتور (فاز ۱۶).

قرارداد: تا کاربر تأیید نکند، **نه شماره‌ای می‌سوزد نه رکوردی ساخته
می‌شود** — یعنی فاکتورِ اشتباه اصلاً به‌وجود نمی‌آید. و اگر بعداً لازم شد،
فاکتور حذف نمی‌شود بلکه باطل می‌شود تا پیوستگیِ شماره‌ها نشکند.
"""
import datetime as dt
from types import SimpleNamespace

from hesabyar.bot import handlers, keyboards, texts
from hesabyar.config import Settings
from hesabyar.core import jalali
from hesabyar.db.models import Invoice, InvoiceStatus
from hesabyar.services import customers as customers_service
from hesabyar.services import invoices as invoice_service
from hesabyar.services import subscription as sub_service
from hesabyar.services import transactions as tx

UID = 18_001


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
        self.entities = []
        self.reply_to_message = None

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
        self.edits: list = []

    async def answer(self, text=None, show_alert=False):
        return None

    async def edit_message_text(self, text, **kw):
        self.edits.append({"text": text, **kw})

    async def edit_message_reply_markup(self, reply_markup=None):
        return None


class _Bot:
    def __init__(self):
        self.sent: list = []
        self.photos: list = []
        self.docs: list = []

    async def send_message(self, chat_id, text=None, **kw):
        self.sent.append({"chat_id": chat_id, "text": text, **kw})

    async def send_photo(self, chat_id, photo=None, **kw):
        self.photos.append({"chat_id": chat_id, **kw})

    async def send_document(self, chat_id, document=None, **kw):
        self.docs.append({"chat_id": chat_id, **kw})

    async def edit_message_text(self, **kw):
        return None


def _ctx(store, **settings):
    app = SimpleNamespace(
        bot_data={"store": store, "settings": Settings(bot_token="x", **settings),
                  "bot_username": "hesabyarbot"},
        bot=_Bot(),
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


async def _ready(store, ctx, **items):
    """کاربر با یک فاکتورِ در حالِ ساخت، آماده‌ی زدنِ «صدور»."""
    user = await tx.get_or_create_user(store, UID)
    user.business_name = "قنادی شیرین"
    user.phone = "02188123456"
    await store.update("users", user)
    await sub_service.get_or_create_subscription(store, UID)
    ctx.user_data["flow"] = "invoice_items"
    ctx.user_data["invoice"] = {
        "customer_name": items.get("customer", "رضا"),
        "items": items.get("items", [
            {"title": "شیرینی", "quantity": 2, "unit_price": 450_000}
        ]),
        "discount": 0, "shipping": 0,
    }


async def _press(ctx, data, message=None):
    query = _Query(data, message=message)
    if data.startswith("invdraft:"):
        handler = handlers.on_invoice_draft
    elif data.startswith("invvoid:"):
        handler = handlers.on_invoice_void
    else:                                     # inv:done / inv:pop / inv:add …
        handler = handlers.on_invoice_action
    await handler(_update(query=query), ctx)
    return query


# --- پیش‌نمایش --------------------------------------------------------------------


class TestPreviewBeforeIssuing:
    async def test_nothing_is_saved_until_confirmed(self, store):
        ctx = _ctx(store)
        await _ready(store, ctx)
        await _press(ctx, "inv:done")

        assert store.list("invoices") == [], "شماره‌ی فاکتور بی‌خود سوخت!"
        assert store.list("invoice_items") == []
        assert ctx.bot.photos, "پیش‌نمایشی نیامد"

    async def test_the_preview_offers_confirm_edit_and_cancel(self, store):
        ctx = _ctx(store)
        await _ready(store, ctx)
        await _press(ctx, "inv:done")
        assert _cb(ctx.bot.photos[-1]["reply_markup"]) == [
            "invdraft:issue", "invdraft:edit", keyboards.CANCEL_DATA
        ]

    async def test_the_preview_says_nothing_is_registered_yet(self, store):
        ctx = _ctx(store)
        await _ready(store, ctx)
        await _press(ctx, "inv:done")
        assert "هنوز چیزی ثبت نشده" in ctx.bot.photos[-1]["caption"]

    async def test_confirming_creates_exactly_one_invoice(self, store):
        ctx = _ctx(store)
        await _ready(store, ctx)
        await _press(ctx, "inv:done")
        await _press(ctx, "invdraft:issue")

        invoices = store.list("invoices")
        assert len(invoices) == 1
        assert invoices[0].customer_name == "رضا"
        assert invoices[0].status == InvoiceStatus.ISSUED
        items = store.list("invoice_items", lambda i: i.invoice_id == invoices[0].id)
        assert len(items) == 1 and items[0].unit_price == 450_000

    async def test_double_tapping_confirm_does_not_double_issue(self, store):
        ctx = _ctx(store)
        await _ready(store, ctx)
        await _press(ctx, "inv:done")
        await _press(ctx, "invdraft:issue")
        await _press(ctx, "invdraft:issue")
        assert len(store.list("invoices")) == 1

    async def test_the_draft_carries_the_seller_header(self, store):
        """پیش‌نمایش باید دقیقاً همان سندی باشد که صادر می‌شود."""
        ctx = _ctx(store)
        await _ready(store, ctx)
        user = await tx.get_or_create_user(store, UID)
        draft = handlers._draft_invoice(ctx.user_data["invoice"], user)
        assert draft.seller_business_name == "قنادی شیرین"
        assert draft.seller_phone == "02188123456"
        assert draft.number == texts.INVOICE_DRAFT_NUMBER
        assert draft.total == 900_000

    async def test_the_draft_is_never_stored(self, store):
        ctx = _ctx(store)
        await _ready(store, ctx)
        user = await tx.get_or_create_user(store, UID)
        handlers._draft_invoice(ctx.user_data["invoice"], user)
        assert store.list("invoices") == []

    async def test_discount_and_shipping_show_in_the_draft(self, store):
        ctx = _ctx(store)
        await _ready(store, ctx)
        ctx.user_data["invoice"].update({"discount": 50_000, "shipping": 30_000})
        user = await tx.get_or_create_user(store, UID)
        draft = handlers._draft_invoice(ctx.user_data["invoice"], user)
        assert draft.total == 900_000 - 50_000 + 30_000

    async def test_an_empty_invoice_is_refused_before_preview(self, store):
        ctx = _ctx(store)
        await _ready(store, ctx, items=[])
        await _press(ctx, "inv:done")
        assert ctx.bot.photos == []
        assert ctx.bot.sent[-1]["text"] == texts.INVOICE_NO_ITEMS

    async def test_an_expired_subscription_stops_at_the_paywall(self, store):
        ctx = _ctx(store)
        await _ready(store, ctx)
        sub = sub_service._get(store, UID)
        sub.expires_at = jalali.now() - dt.timedelta(days=1)
        await store.update("subscriptions", sub)

        await _press(ctx, "inv:done")
        assert ctx.bot.photos == [], "بدون اشتراک نباید پیش‌نمایش هم بدهد"
        assert any(d.startswith("sub:buy:")
                   for d in _cb(ctx.bot.sent[-1]["reply_markup"]))


class TestEditFromPreview:
    async def test_edit_returns_to_the_builder(self, store):
        ctx = _ctx(store)
        await _ready(store, ctx)
        await _press(ctx, "inv:done")
        query = await _press(ctx, "invdraft:edit")

        assert ctx.user_data["flow"] == "invoice_items"
        assert store.list("invoices") == []
        assert "inv:done" in _cb(query.message.markup)

    async def test_items_survive_the_round_trip(self, store):
        ctx = _ctx(store)
        await _ready(store, ctx)
        await _press(ctx, "inv:done")
        await _press(ctx, "invdraft:edit")
        assert len(ctx.user_data["invoice"]["items"]) == 1

    async def test_edit_then_change_then_issue(self, store):
        ctx = _ctx(store)
        await _ready(store, ctx)
        await _press(ctx, "inv:done")
        await _press(ctx, "invdraft:edit")
        await _press(ctx, "inv:pop")          # قلم را برداشت
        ctx.user_data["invoice"]["items"].append(
            {"title": "کیک", "quantity": 1, "unit_price": 800_000})
        await _press(ctx, "inv:done")
        await _press(ctx, "invdraft:issue")

        invoice = store.list("invoices")[0]
        items = store.list("invoice_items", lambda i: i.invoice_id == invoice.id)
        assert [(i.title, i.unit_price) for i in items] == [("کیک", 800_000)]

    async def test_cancel_from_the_preview_leaves_nothing(self, store):
        ctx = _ctx(store)
        await _ready(store, ctx)
        await _press(ctx, "inv:done")
        await handlers.on_flow_cancel(
            _update(query=_Query(keyboards.CANCEL_DATA)), ctx)
        assert store.list("invoices") == []
        assert "invoice" not in ctx.user_data

    async def test_a_stale_preview_is_reported(self, store):
        ctx = _ctx(store)
        query = await _press(ctx, "invdraft:issue")   # هیچ پیش‌نویسی نیست
        assert query.edits[-1]["text"] == texts.INVOICE_PREVIEW_GONE
        assert store.list("invoices") == []


# --- باطل‌کردن --------------------------------------------------------------------


async def _issued(store, ctx, customer="رضا"):
    await _ready(store, ctx, customer=customer)
    await _press(ctx, "inv:done")
    await _press(ctx, "invdraft:issue")
    return store.list("invoices")[-1]


class TestVoiding:
    async def test_service_marks_it_void_without_deleting(self, store):
        ctx = _ctx(store)
        invoice = await _issued(store, ctx)
        voided = await invoice_service.void_invoice(store, invoice.id, UID)

        assert voided.status == InvoiceStatus.VOID
        assert voided.is_void is True
        assert len(store.list("invoices")) == 1, "نباید حذف شود"
        assert store.get("invoices", invoice.id).number == invoice.number

    async def test_the_number_is_not_reused(self, store):
        """پیوستگیِ شماره‌گذاری نباید بشکند."""
        ctx = _ctx(store)
        first = await _issued(store, ctx)
        await invoice_service.void_invoice(store, first.id, UID)
        second = await _issued(store, _ctx(store))
        assert second.number != first.number
        assert second.seq == first.seq + 1

    async def test_voiding_twice_returns_none(self, store):
        ctx = _ctx(store)
        invoice = await _issued(store, ctx)
        await invoice_service.void_invoice(store, invoice.id, UID)
        assert await invoice_service.void_invoice(store, invoice.id, UID) is None

    async def test_another_users_invoice_cannot_be_voided(self, store):
        ctx = _ctx(store)
        invoice = await _issued(store, ctx)
        await tx.get_or_create_user(store, UID + 1)
        assert await invoice_service.void_invoice(store, invoice.id, UID + 1) is None
        assert not store.get("invoices", invoice.id).is_void

    async def test_a_void_invoice_is_excluded_from_customer_totals(self, store):
        ctx = _ctx(store)
        first = await _issued(store, ctx)
        await _issued(store, _ctx(store))

        customer = customers_service.find_customer(store, UID, "رضا")
        before = customers_service.customer_totals(store, UID, customer.id)
        assert before["invoiced"] == 1_800_000

        await invoice_service.void_invoice(store, first.id, UID)
        after = customers_service.customer_totals(store, UID, customer.id)
        assert after["invoiced"] == 900_000
        assert len(after["invoices"]) == 1

    async def test_old_rows_without_the_column_are_valid(self, store):
        assert Invoice.from_row({"id": "1"}).status == InvoiceStatus.ISSUED
        assert Invoice.from_row({"id": "1"}).is_void is False

    async def test_the_status_survives_a_round_trip(self, store):
        invoice = Invoice(id=1, status=InvoiceStatus.VOID)
        row = dict(zip(Invoice.COLUMNS, invoice.to_row()))
        assert Invoice.from_row(row).is_void is True


class TestVoidFromTheHistory:
    async def test_history_shows_a_void_button_per_invoice(self, store):
        ctx = _ctx(store)
        invoice = await _issued(store, ctx)
        markup = keyboards.invoice_history([store.get("invoices", invoice.id)])
        assert _cb(markup) == [f"invh:{invoice.id}", f"invvoid:ask:{invoice.id}"]

    async def test_a_voided_invoice_is_marked_and_loses_its_button(self, store):
        ctx = _ctx(store)
        invoice = await _issued(store, ctx)
        await invoice_service.void_invoice(store, invoice.id, UID)

        markup = keyboards.invoice_history([store.get("invoices", invoice.id)])
        assert _cb(markup) == [f"invh:{invoice.id}"], "دکمه‌ی باطل نباید بماند"
        label = markup.inline_keyboard[0][0].text
        assert "⛔" in label and texts.INVOICE_VOID_LABEL in label

    async def test_it_asks_before_voiding(self, store):
        ctx = _ctx(store)
        invoice = await _issued(store, ctx)
        query = await _press(ctx, f"invvoid:ask:{invoice.id}")

        assert not store.get("invoices", invoice.id).is_void, "هنوز نباید باطل شود"
        assert invoice.number in query.edits[-1]["text"]
        assert _cb(query.edits[-1]["reply_markup"]) == [
            f"invvoid:yes:{invoice.id}", "act:invoices"
        ]

    async def test_confirming_voids_it_and_reshows_the_list(self, store):
        ctx = _ctx(store)
        invoice = await _issued(store, ctx)
        query = await _press(ctx, f"invvoid:yes:{invoice.id}")

        assert store.get("invoices", invoice.id).is_void is True
        assert invoice.number in query.edits[-1]["text"]
        assert "invh:" in " ".join(_cb(query.message.markup))

    async def test_asking_about_an_already_void_invoice(self, store):
        ctx = _ctx(store)
        invoice = await _issued(store, ctx)
        await invoice_service.void_invoice(store, invoice.id, UID)
        query = await _press(ctx, f"invvoid:ask:{invoice.id}")
        assert query.edits[-1]["text"] == texts.INVOICE_VOID_GONE

    async def test_bad_callback_data_is_ignored(self, store):
        ctx = _ctx(store)
        query = await _press(ctx, "invvoid:ask:xyz")
        assert query.edits == []


class TestRegistration:
    def test_both_handlers_are_registered(self):
        import re
        from telegram.ext import ApplicationBuilder, CallbackQueryHandler
        application = ApplicationBuilder().token("1:AA").build()
        handlers.register(application)
        patterns = [h.pattern.pattern for group in application.handlers.values()
                    for h in group
                    if isinstance(h, CallbackQueryHandler) and h.pattern]
        for data, expected in (("invdraft:issue", r"^invdraft:"),
                               ("invvoid:ask:1", r"^invvoid:")):
            assert [p for p in patterns if re.match(p, data)] == [expected], data

    def test_the_new_patterns_do_not_collide_with_inv_or_invh(self):
        import re
        for data in ("invdraft:issue", "invvoid:ask:1"):
            assert not re.match(r"^inv:", data)
            assert not re.match(r"^invh:", data)
