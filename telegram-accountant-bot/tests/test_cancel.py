"""تست‌های دکمه‌ی «لغو عملیات» در جریان‌های چندمرحله‌ای (فاز ۴)."""
import inspect
import re
from types import SimpleNamespace

import pytest

from hesabyar.bot import handlers, keyboards, texts
from hesabyar.config import Settings
from hesabyar.core import jalali
from hesabyar.db.models import Direction, Kind
from hesabyar.services import products as products_service
from hesabyar.services import transactions as tx

UID = 7001
CANCEL = keyboards.CANCEL_DATA


def _cb(markup):
    if markup is None:
        return []
    return [b.callback_data for row in markup.inline_keyboard for b in row]


# --- کیبورد کمکی ---------------------------------------------------------------


class TestWithCancel:
    def test_appends_a_row(self):
        base = keyboards.report_periods()
        out = keyboards.with_cancel(base)
        assert len(out.inline_keyboard) == len(base.inline_keyboard) + 1
        assert _cb(out)[: len(_cb(base))] == _cb(base)

    def test_cancel_is_the_last_row_alone(self):
        last = keyboards.with_cancel(keyboards.report_periods()).inline_keyboard[-1]
        assert len(last) == 1
        assert last[0].callback_data == CANCEL
        assert last[0].text == texts.BTN_FLOW_CANCEL

    def test_is_idempotent(self):
        once = keyboards.with_cancel(keyboards.report_periods())
        assert _cb(keyboards.with_cancel(once)) == _cb(once)

    def test_cancel_only_is_a_single_button(self):
        assert _cb(keyboards.cancel_only()) == [CANCEL]

    def test_does_not_mutate_the_input(self):
        base = keyboards.report_periods()
        before = len(base.inline_keyboard)
        keyboards.with_cancel(base)
        assert len(base.inline_keyboard) == before


class TestFlowKeyboardsCarryCancel:
    def test_invoice_builder(self):
        products = [SimpleNamespace(id=1, title="کالا", unit_price=1000)]
        assert CANCEL in _cb(keyboards.invoice_builder(products, True))
        assert CANCEL in _cb(keyboards.invoice_builder([], False))

    def test_category_picker(self):
        assert CANCEL in _cb(keyboards.category_picker(1, Kind.EXPENSE))

    def test_industry_picker(self):
        assert CANCEL in _cb(keyboards.industry_picker())

    def test_plain_menus_do_not_get_a_cancel(self):
        """منوها جریان نیستند؛ دکمه‌ی «بازگشت» دارند نه «لغو»."""
        for fn in (keyboards.report_menu, keyboards.transactions_menu,
                   keyboards.ledger_menu, keyboards.invoice_menu,
                   keyboards.business_menu, keyboards.account_menu):
            assert CANCEL not in _cb(fn()), fn.__name__


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

    @property
    def markup(self):
        return self.replies[-1].get("reply_markup") if self.replies else None


class _Query:
    def __init__(self, data, message=None):
        self.data = data
        self.message = message or _Msg()
        self.edits: list = []
        self.markup_edits: list = []

    async def answer(self, text=None, show_alert=False):
        return None

    async def edit_message_text(self, text, **kw):
        self.edits.append({"text": text, **kw})

    async def edit_message_reply_markup(self, reply_markup=None):
        self.markup_edits.append(reply_markup)


class _Bot:
    def __init__(self):
        self.sent: list = []

    async def send_message(self, chat_id, text=None, **kw):
        self.sent.append({"chat_id": chat_id, "text": text, **kw})

    async def edit_message_text(self, **kw):
        return None


def _ctx(store, **settings):
    app = SimpleNamespace(
        bot_data={"store": store, "settings": Settings(bot_token="x", **settings)},
        bot=_Bot(),
    )
    return SimpleNamespace(application=app, bot=app.bot,
                           chat_data={}, user_data={}, args=[])


def _update(message=None, query=None):
    msg = message or (query.message if query else None)
    return SimpleNamespace(
        message=message, callback_query=query,
        effective_user=SimpleNamespace(id=UID, full_name="تست", username="t"),
        effective_chat=SimpleNamespace(id=UID, type="private", title=None),
        effective_message=msg,
    )


async def _type(ctx, text):
    """کاربر یک پیام متنی می‌فرستد؛ پیامِ جوابِ بات برگردانده می‌شود."""
    msg = _Msg(text)
    await handlers.on_text(_update(message=msg), ctx)
    return msg


async def _press_cancel(ctx, message=None):
    query = _Query(CANCEL, message=message)
    await handlers.on_flow_cancel(_update(query=query), ctx)
    return query


# --- پاک‌شدنِ حالت ---------------------------------------------------------------


class TestCancelClearsState:
    async def test_removes_every_flow_key(self, store):
        ctx = _ctx(store)
        for key in handlers._FLOW_KEYS:
            ctx.user_data[key] = "زباله"
        ctx.user_data["keep_me"] = 1
        await _press_cancel(ctx)
        assert not (set(handlers._FLOW_KEYS) & set(ctx.user_data))
        assert ctx.user_data["keep_me"] == 1, "کلیدهای بی‌ربط نباید پاک شوند"

    async def test_strips_the_inline_keyboard(self, store):
        ctx = _ctx(store)
        query = await _press_cancel(ctx)
        assert query.markup_edits == [None]

    async def test_restores_the_main_reply_keyboard(self, store):
        ctx = _ctx(store)
        query = await _press_cancel(ctx)
        reply = query.message.replies[-1]
        assert reply["text"] == texts.CANCELLED
        labels = [b.text for r in reply["reply_markup"].keyboard for b in r]
        assert labels[0] == texts.BTN_REPORT

    async def test_survives_a_message_that_cannot_be_edited(self, store):
        """اگر ویرایش کیبورد شکست بخورد، لغو نباید بترکد."""
        ctx = _ctx(store)

        class _Stubborn(_Query):
            async def edit_message_reply_markup(self, reply_markup=None):
                raise RuntimeError("message is not modified")

        query = _Stubborn(CANCEL)
        await handlers.on_flow_cancel(_update(query=query), ctx)
        assert query.message.replies[-1]["text"] == texts.CANCELLED

    async def test_after_cancel_text_is_a_normal_transaction(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        ctx.user_data["flow"] = "ledger_amount"
        ctx.user_data["ledger"] = {"direction": Direction.RECEIVABLE}
        await _press_cancel(ctx)
        await _type(ctx, "۵۰ هزار تومان فروختم")
        assert len(store.list("transactions")) == 1


# --- هر جریان: ورود، دکمه‌ی لغو، و نبودِ دیتای نیمه‌کاره -----------------------------


def _flows_declared_in_source() -> set:
    """همه‌ی مقدارهایی که در ``handlers.py`` روی ``user_data['flow']`` می‌نشیند."""
    source = inspect.getsource(handlers)
    return set(re.findall(r'user_data\["flow"\]\s*=\s*"([a-z_]+)"', source))


class TestEveryFlowIsCancellable:
    async def _start_ledger(self, ctx):
        query = _Query("ledger:add:receivable")
        await handlers.on_ledger_action(_update(query=query), ctx)
        return query.edits[-1]

    async def test_no_flow_is_left_uncovered(self):
        """اگر جریانِ تازه‌ای اضافه شود، این تست مجبورش می‌کند اینجا هم بیاید."""
        assert _flows_declared_in_source() == COVERED_FLOWS

    async def test_onboarding(self, store):
        ctx = _ctx(store)
        msg = _Msg("/start")
        await handlers.start(_update(message=msg), ctx)
        assert ctx.user_data["flow"] == "onboarding"
        assert CANCEL in _cb(msg.markup)
        await _press_cancel(ctx, message=msg)
        assert "flow" not in ctx.user_data
        user = await tx.get_or_create_user(store, UID)
        assert not user.business_name, "نامِ نصفه‌کاره نباید ذخیره شود"

    async def test_ledger_at_every_step(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        # مرحله‌ی ۱ — نام طرف‌حساب
        prompt = await self._start_ledger(ctx)
        assert ctx.user_data["flow"] == "ledger_party"
        assert CANCEL in _cb(prompt.get("reply_markup"))
        # مرحله‌ی ۲ — مبلغ
        msg = await _type(ctx, "رضا")
        assert ctx.user_data["flow"] == "ledger_amount"
        assert CANCEL in _cb(msg.markup)
        # مرحله‌ی ۳ — سررسید
        msg = await _type(ctx, "۲۰۰ هزار")
        assert ctx.user_data["flow"] == "ledger_due"
        assert CANCEL in _cb(msg.markup)
        # لغو در آخرین مرحله ⇒ هیچ ردیفی در دفتر ثبت نشده باشد
        await _press_cancel(ctx)
        assert "ledger" not in ctx.user_data
        assert store.list("ledger_entries") == []

    async def test_ledger_amount_retry_keeps_the_cancel_button(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        await self._start_ledger(ctx)
        await _type(ctx, "رضا")
        msg = await _type(ctx, "قابلِ عدد نیست")   # ورودی بد ⇒ دوباره می‌پرسد
        assert ctx.user_data["flow"] == "ledger_amount"
        assert CANCEL in _cb(msg.markup)

    async def test_seller_field(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        # «🏪 سربرگ فاکتور» ⇒ صفحه‌ی فیلدها ⇒ یکی از آن‌ها
        await handlers.on_menu_action(_update(query=_Query("act:bizname")), ctx)
        query = _Query("seller:set:business_name")
        await handlers.on_seller_action(_update(query=query), ctx)
        assert ctx.user_data["flow"] == "seller_field"
        assert CANCEL in _cb(query.message.markup)
        await _press_cancel(ctx)
        assert "flow" not in ctx.user_data and "seller_field" not in ctx.user_data
        assert not (await tx.get_or_create_user(store, UID)).business_name

    async def test_seller_image(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        await handlers.on_menu_action(_update(query=_Query("act:bizname")), ctx)
        query = _Query("seller:img:logo_file_id")
        await handlers.on_seller_action(_update(query=query), ctx)
        assert ctx.user_data["flow"] == "seller_image"
        assert CANCEL in _cb(query.message.markup)
        await _press_cancel(ctx)
        assert "flow" not in ctx.user_data and "seller_field" not in ctx.user_data
        assert not (await tx.get_or_create_user(store, UID)).logo_file_id

    async def test_statement_party(self, store):
        ctx = _ctx(store)
        query = _Query("ledger:statement")
        await handlers.on_ledger_action(_update(query=query), ctx)
        assert ctx.user_data["flow"] == "statement_party"
        assert CANCEL in _cb(query.edits[-1].get("reply_markup"))
        await _press_cancel(ctx)
        assert "flow" not in ctx.user_data

    async def test_branch_name(self, store):
        ctx = _ctx(store)
        query = _Query("branch:add")
        await handlers.on_branch_action(_update(query=query), ctx)
        assert ctx.user_data["flow"] == "branch_name"
        assert CANCEL in _cb(query.message.markup)
        await _press_cancel(ctx)
        assert "flow" not in ctx.user_data
        assert store.list("branches") == []

    async def test_invoice_from_customer_to_items(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        query = _Query("act:newinvoice")
        await handlers.on_menu_action(_update(query=query), ctx)
        assert CANCEL in _cb(query.message.markup)
        # نامِ مشتری ⇒ کیبوردِ ساختِ فاکتور که خودش دکمه‌ی لغو دارد
        msg = await _type(ctx, "آقای رضایی")
        assert ctx.user_data["flow"] == "invoice_items"
        assert CANCEL in _cb(msg.markup)
        # یک قلم اضافه می‌کنیم و بعد لغو می‌زنیم
        await _type(ctx, "پیراهن ۲ ۳۰۰ هزار")
        assert ctx.user_data["invoice"]["items"]
        await _press_cancel(ctx)
        assert "invoice" not in ctx.user_data
        assert store.list("invoices") == []
        assert store.list("invoice_items") == []

    async def test_invoice_discount_and_shipping(self, store):
        ctx = _ctx(store)
        ctx.user_data["flow"] = "invoice_items"
        ctx.user_data["invoice"] = {"items": [], "discount": 0, "shipping": 0}
        query = _Query("inv:extra")
        await handlers.on_invoice_action(_update(query=query), ctx)
        assert ctx.user_data["flow"] == "inv_discount"
        assert CANCEL in _cb(query.message.markup)
        msg = await _type(ctx, "۱۰ هزار")
        assert ctx.user_data["flow"] == "inv_shipping"
        assert CANCEL in _cb(msg.markup)
        await _press_cancel(ctx)
        assert "invoice" not in ctx.user_data

    async def test_invoice_bad_item_retry(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        ctx.user_data["flow"] = "invoice_items"
        ctx.user_data["invoice"] = {"items": [], "discount": 0, "shipping": 0}
        msg = await _type(ctx, "؟؟؟")
        assert CANCEL in _cb(msg.markup)

    async def test_product_name_and_price(self, store):
        ctx = _ctx(store)
        query = _Query("prod:add")
        await handlers.on_product_action(_update(query=query), ctx)
        assert ctx.user_data["flow"] == "prod_name"
        assert CANCEL in _cb(query.message.markup)
        msg = await _type(ctx, "پیراهن")
        assert ctx.user_data["flow"] == "prod_category"
        assert CANCEL in _cb(msg.markup)
        # «دسته‌ی جدید» ⇒ یک مرحله‌ی متنیِ دیگر، آن هم با دکمه‌ی لغو
        cat = _Query("pcat:new")
        await handlers.on_product_category(_update(query=cat), ctx)
        assert ctx.user_data["flow"] == "prod_newcat"
        assert CANCEL in _cb(cat.message.markup)
        msg = await _type(ctx, "پوشاک")
        assert ctx.user_data["flow"] == "prod_price"
        assert CANCEL in _cb(msg.markup)
        await _press_cancel(ctx)
        assert "product_tmp" not in ctx.user_data
        assert products_service.list_products(store, UID) == []

    async def test_payment_reference(self, store):
        ctx = _ctx(store, card_number="6037-0000-0000-0000", card_holder="آریا")
        query = _Query("sub:buy:silver_monthly")
        await handlers.on_subscription(_update(query=query), ctx)
        assert ctx.user_data["flow"] == "payment_reference"
        assert CANCEL in _cb(query.edits[-1].get("reply_markup"))
        await _press_cancel(ctx)
        assert "payment" not in ctx.user_data
        assert store.list("payments") == []

    async def test_edit_amount(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        created = await tx.add_transaction(
            store, UID, kind=Kind.EXPENSE, amount=50_000, category="متفرقه",
            description="", occurred_at=jalali.now(),
        )
        query = _Query(f"tx:eamt:{created.id}")
        await handlers.on_tx_action(_update(query=query), ctx)
        assert ctx.user_data["flow"] == "edit_amount"
        assert CANCEL in _cb(query.message.markup)
        await _press_cancel(ctx)
        assert "edit_tx" not in ctx.user_data
        assert tx.get_transaction(store, UID, created.id).amount == 50_000

    async def test_edit_amount_retry(self, store):
        ctx = _ctx(store)
        ctx.user_data["flow"] = "edit_amount"
        ctx.user_data["edit_tx"] = 1
        msg = await _type(ctx, "بدونِ عدد")
        assert CANCEL in _cb(msg.markup)

    async def test_search_query(self, store):
        ctx = _ctx(store)
        query = _Query("act:search")
        await handlers.on_menu_action(_update(query=query), ctx)
        assert ctx.user_data["flow"] == "search_query"
        assert CANCEL in _cb(query.message.markup)
        await _press_cancel(ctx)
        assert "flow" not in ctx.user_data

    async def test_join_code(self, store):
        ctx = _ctx(store)
        query = _Query("act:join")
        await handlers.on_menu_action(_update(query=query), ctx)
        assert ctx.user_data["flow"] == "join_code"
        assert CANCEL in _cb(query.message.markup)
        await _press_cancel(ctx)
        assert "flow" not in ctx.user_data
        assert store.list("branch_members") == []


#: جریان‌هایی که تست‌های بالا پوشش می‌دهند — با منبع مقایسه می‌شود.
COVERED_FLOWS = {
    "onboarding",
    "ledger_party", "ledger_amount", "ledger_due", "statement_party",
    "branch_name", "seller_field", "seller_image",
    "invoice_customer", "invoice_items", "inv_discount", "inv_shipping",
    "prod_name", "prod_category", "prod_newcat", "prod_price",
    "payment_reference", "edit_amount",
    "search_query", "join_code",
}


# --- ثبت هندلر ------------------------------------------------------------------


class TestRegistration:
    def test_flow_cancel_handler_is_registered(self):
        source = inspect.getsource(handlers.register)
        assert "on_flow_cancel" in source
        assert r"^flow:cancel$" in source

    def test_pattern_matches_the_keyboard_data(self):
        assert re.match(r"^flow:cancel$", CANCEL)


@pytest.mark.parametrize("data", ["menu:main", "flow:cancel"])
def test_exit_routes_are_distinct(data):
    """«بازگشت» و «لغو» دو مسیر جدا هستند و با هم قاطی نمی‌شوند."""
    assert bool(re.match(r"^menu:", data)) != bool(re.match(r"^flow:cancel$", data))
