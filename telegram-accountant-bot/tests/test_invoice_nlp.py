"""تست‌های ساختِ فاکتور از یک جمله‌ی فارسیِ آزاد (فاز ۶)."""
from types import SimpleNamespace

import pytest

from hesabyar.bot import handlers, keyboards, texts
from hesabyar.config import Settings
from hesabyar.core import invoice_nlp
from hesabyar.core.invoice_nlp import parse_invoice_text
from hesabyar.services import transactions as tx

UID = 8001


def _one(text):
    """پارس + اطمینان از اینکه دقیقاً یک قلم دارد."""
    parsed = parse_invoice_text(text)
    assert parsed is not None, f"پارس نشد: {text}"
    assert len(parsed.items) == 1, [i.title for i in parsed.items]
    return parsed, parsed.items[0]


# --- سه نمونه‌ای که در مشخصات آمده --------------------------------------------


class TestSpecSamples:
    def test_unit_price_with_counter(self):
        parsed, item = _one(
            "فاکتور به اسم دارا ۳ تا محصول مبل درجه ۲ به قیمت ۲۵ میلیون تومان هر واحد"
        )
        assert parsed.customer_name == "دارا"
        assert item.title == "مبل درجه ۲"
        assert (item.quantity, item.unit_price) == (3, 25_000_000)
        assert parsed.total == 75_000_000

    def test_two_items_separated_by_comma_and_and(self):
        parsed = parse_invoice_text(
            "فاکتور برای علی، ۲ عدد صندلی ۵۰۰ هزار تومانی و ۱ میز ۳ میلیونی"
        )
        assert parsed is not None
        assert parsed.customer_name == "علی"
        assert [(i.title, i.quantity, i.unit_price) for i in parsed.items] == [
            ("صندلی", 2, 500_000),
            ("میز", 1, 3_000_000),
        ]
        assert parsed.total == 4_000_000

    def test_total_price_is_divided_by_quantity(self):
        parsed, item = _one("برای سارا فاکتور بزن: ۱۰ کیلو برنج قیمت کل ۲ میلیون")
        assert parsed.customer_name == "سارا"
        assert item.title == "برنج"
        assert (item.quantity, item.unit_price) == (10, 200_000)
        assert parsed.total == 2_000_000


# --- تنوعِ ورودی‌ها -------------------------------------------------------------


class TestVariations:
    def test_english_digits(self):
        _, item = _one("فاکتور برای رضا 4 عدد لیوان 25000 تومان")
        assert (item.quantity, item.unit_price) == (4, 25_000)

    def test_mixed_persian_and_english_digits(self):
        _, item = _one("فاکتور به نام مریم ۲ تا کیف 750000 تومان")
        assert (item.quantity, item.unit_price) == (2, 750_000)

    def test_without_the_word_toman(self):
        _, item = _one("فاکتور برای حسن ۳ عدد دفتر ۸۰ هزار")
        assert (item.quantity, item.unit_price) == (3, 80_000)

    def test_quantity_defaults_to_one(self):
        _, item = _one("فاکتور برای نازنین یک عدد لپ‌تاپ ۴۵ میلیون تومان")
        assert item.quantity == 1
        assert item.unit_price == 45_000_000

    def test_no_quantity_word_at_all(self):
        _, item = _one("فاکتور برای امیر مانیتور ۱۲ میلیون")
        assert (item.quantity, item.unit_price) == (1, 12_000_000)

    def test_hamegi_total_hint(self):
        _, item = _one("فاکتور برای زهرا ۴ عدد شال جمعاً ۸۰۰ هزار تومان")
        assert (item.quantity, item.unit_price) == (4, 200_000)

    def test_har_kodoom_is_unit_price(self):
        _, item = _one("فاکتور برای بابک ۵ تا تیشرت هرکدوم ۳۰۰ هزار")
        assert (item.quantity, item.unit_price) == (5, 300_000)

    def test_unit_hint_wins_over_total_hint(self):
        """اگر هر دو نشانه بود، «هر واحد» صریح‌تر است."""
        _, item = _one("فاکتور برای پویا ۲ عدد صندلی قیمت کل هر واحد ۱ میلیون")
        assert item.unit_price == 1_000_000

    def test_three_items(self):
        parsed = parse_invoice_text(
            "فاکتور برای کیان، ۲ عدد لیوان ۵۰ هزار، ۳ بشقاب ۸۰ هزار، ۱ قوری ۲۰۰ هزار"
        )
        assert parsed is not None
        assert [(i.quantity, i.unit_price) for i in parsed.items] == [
            (2, 50_000), (3, 80_000), (1, 200_000)
        ]

    def test_rial_is_converted_to_toman(self):
        _, item = _one("فاکتور برای سعید ۲ عدد کتاب ۵۰۰۰۰۰ ریال")
        assert item.unit_price == 50_000

    def test_compound_number_with_and_is_not_split(self):
        """«دو میلیون و پانصد هزار» یک عدد است، نه دو قلم."""
        parsed, item = _one("فاکتور برای نیما یک عدد گوشی دو میلیون و پانصد هزار تومان")
        assert item.unit_price == 2_500_000

    def test_digits_inside_the_title_survive(self):
        _, item = _one("فاکتور برای آرش ۲ عدد روغن ۲۰w۵۰ به قیمت ۹۰۰ هزار تومان")
        assert "۲۰" in item.title
        assert (item.quantity, item.unit_price) == (2, 900_000)

    def test_honorific_keeps_the_second_word(self):
        parsed, _ = _one("فاکتور به نام آقای رضایی ۱ عدد میز ۵ میلیون")
        assert parsed.customer_name == "آقای رضایی"

    def test_a_comma_marks_the_end_of_a_two_word_name(self):
        parsed, item = _one("فاکتور برای علی رضایی، ۲ صندلی ۵۰۰ هزار")
        assert parsed.customer_name == "علی رضایی"
        assert item.title == "صندلی"

    def test_without_a_boundary_only_one_word_is_the_name(self):
        """«مانیتور» کالاست، نه فامیلِ امیر — نامِ کوتاه‌تر امن‌تر است."""
        parsed, item = _one("فاکتور برای امیر مانیتور ۱۲ میلیون")
        assert parsed.customer_name == "امیر"
        assert item.title == "مانیتور"

    def test_counter_before_the_price_is_not_part_of_the_title(self):
        _, item = _one("فاکتور برای رضا بزن ۱۲ متر پارچه متری ۳۵۰ هزار")
        assert item.title == "پارچه"
        assert (item.quantity, item.unit_price) == (12, 350_000)

    def test_price_hint_word_is_not_part_of_the_title(self):
        _, item = _one(
            "صورتحساب به نام شرکت پارس، ۵ کارتن کاغذ A4 هرکدوم ۲ میلیون و ۴۰۰ هزار"
        )
        assert item.title == "کاغذ A۴"
        assert (item.quantity, item.unit_price) == (5, 2_400_000)

    def test_business_name_with_ezafe(self):
        parsed = parse_invoice_text(
            "برای مغازه‌ی حسن فاکتور بزن: ۲ دست مبل ۴۵ میلیون، ۱ فرش ۱۲ میلیون و ۵۰۰ هزار"
        )
        assert parsed is not None
        assert parsed.customer_name == "مغازه حسن"
        assert [(i.title, i.unit_price) for i in parsed.items] == [
            ("مبل", 45_000_000), ("فرش", 12_500_000)
        ]

    def test_kilo_counter(self):
        _, item = _one("فاکتور برای مهدی ۲۵ کیلو پسته هر کیلو ۱ میلیون و ۲۰۰ هزار")
        assert item.quantity == 25
        assert item.unit_price == 1_200_000


# --- ورودی‌هایی که باید None برگردند ---------------------------------------------


class TestReturnsNoneInsteadOfGuessing:
    @pytest.mark.parametrize("text", [
        "",
        "   ",
        "سلام خوبی؟",
        "فاکتور",                                  # نه مشتری، نه قلم
        "فاکتور برای علی",                          # مشتری هست، قلم نیست
        "فاکتور برای علی چند تا صندلی",             # قلم بدون قیمت
        "۲ عدد صندلی ۵۰۰ هزار",                    # مشتری ندارد
        "دیروز ۵۰۰ هزار بابت فاکتور برق دادم",      # جمله‌ی تراکنش است
    ])
    def test_returns_none(self, text):
        assert parse_invoice_text(text) is None

    def test_never_raises_on_garbage(self):
        for text in ["؟؟؟", "۰۰۰", "فاکتور ۰ عدد ۰ تومان", "!@#$%^", "فاکتور برای ۱۲۳"]:
            parse_invoice_text(text)   # نباید خطا بدهد

    def test_a_plain_transaction_sentence_is_not_an_invoice(self):
        assert not invoice_nlp.looks_like_invoice("۵۰۰ هزار خرید مواد اولیه")


class TestLooksLikeInvoice:
    @pytest.mark.parametrize("text", [
        "فاکتور برای علی ۲ صندلی ۵۰۰ هزار",
        "صورتحساب به نام رضا ۱ میز ۲ میلیون",
        "برای سارا فاکتور بزن: ۱۰ کیلو برنج ۲ میلیون",
    ])
    def test_yes(self, text):
        assert invoice_nlp.looks_like_invoice(text)

    @pytest.mark.parametrize("text", ["", "۵۰۰ هزار فروختم", "سلام"])
    def test_no(self, text):
        assert not invoice_nlp.looks_like_invoice(text)


class TestParsedShape:
    def test_fields_and_helpers(self):
        parsed, item = _one("فاکتور برای دارا ۲ عدد مبل ۱۰ میلیون تومان")
        assert parsed.raw_text.startswith("فاکتور")
        assert 0.0 <= parsed.confidence <= 1.0
        assert item.total == 20_000_000
        assert parsed.as_items() == [
            {"title": "مبل", "quantity": 2, "unit_price": 10_000_000}
        ]

    def test_as_items_matches_what_create_invoice_expects(self):
        """کلیدها باید دقیقاً همان‌هایی باشند که سرویسِ فاکتور می‌خواند."""
        parsed = parse_invoice_text("فاکتور برای دارا ۲ عدد مبل ۱۰ میلیون")
        for row in parsed.as_items():
            assert set(row) == {"title", "quantity", "unit_price"}
            assert isinstance(row["quantity"], int)
            assert isinstance(row["unit_price"], int)

    def test_confidence_is_lower_when_signals_are_weak(self):
        strong = parse_invoice_text(
            "فاکتور به اسم دارا ۳ تا مبل به قیمت ۲۵ میلیون تومان هر واحد"
        )
        weak = parse_invoice_text("فاکتور برای دارا مبل ۲۵۰۰۰۰۰۰")
        assert strong.confidence > weak.confidence


# --- ابزار شبیه‌سازی برای تست‌های هندلر -------------------------------------------


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
        self.photos: list = []
        self.docs: list = []

    async def send_message(self, chat_id, text=None, **kw):
        self.sent.append({"chat_id": chat_id, "text": text, **kw})

    async def send_photo(self, chat_id, photo=None, **kw):
        self.photos.append(kw)

    async def send_document(self, chat_id, document=None, **kw):
        self.docs.append(kw)

    async def edit_message_text(self, **kw):
        return None


def _ctx(store):
    app = SimpleNamespace(
        bot_data={"store": store, "settings": Settings(bot_token="x"),
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


async def _say(ctx, text):
    msg = _Msg(text)
    await handlers.on_text(_update(message=msg), ctx)
    return msg


def _cb(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


SENTENCE = "فاکتور برای علی، ۲ عدد صندلی ۵۰۰ هزار تومانی و ۱ میز ۳ میلیونی"


# --- رفتار در بات ----------------------------------------------------------------


class TestNothingIsSavedWithoutConfirmation:
    async def test_sentence_produces_a_draft_not_an_invoice(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        msg = await _say(ctx, SENTENCE)
        assert store.list("invoices") == [], "بدون تأیید ثبت شد!"
        assert store.list("transactions") == [], "به‌اشتباه تراکنش ثبت شد"
        assert ctx.user_data["invnlp"]["customer_name"] == "علی"
        assert _cb(msg.replies[-1]["reply_markup"]) == [
            "invnlp:confirm", "invnlp:edit", keyboards.CANCEL_DATA
        ]

    async def test_the_draft_message_shows_what_was_understood(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        msg = await _say(ctx, SENTENCE)
        body = msg.replies[-1]["text"]
        assert "علی" in body and "صندلی" in body and "میز" in body
        assert "۵۰۰٬۰۰۰" in body and "۳٬۰۰۰٬۰۰۰" in body
        assert "۴٬۰۰۰٬۰۰۰" in body            # جمع کل
        assert texts.INVNLP_ASK in body

    async def test_cancel_button_leaves_nothing_behind(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        await _say(ctx, SENTENCE)
        query = _Query(keyboards.CANCEL_DATA)
        await handlers.on_flow_cancel(_update(query=query), ctx)
        assert "invnlp" not in ctx.user_data
        assert store.list("invoices") == []

    async def test_confirm_creates_the_invoice_through_the_normal_path(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        await _say(ctx, SENTENCE)
        await handlers.on_invoice_nlp(_update(query=_Query("invnlp:confirm")), ctx)

        invoices = store.list("invoices")
        assert len(invoices) == 1
        invoice = invoices[0]
        assert invoice.customer_name == "علی"
        items = store.list("invoice_items", lambda i: i.invoice_id == invoice.id)
        assert sorted((i.title, i.quantity, i.unit_price) for i in items) == [
            ("صندلی", 2, 500_000), ("میز", 1, 3_000_000)
        ]
        # فاز ۲: باید به رکورد مشتری وصل شده باشد
        assert invoice.customer_id
        assert store.get("customers", invoice.customer_id).name == "علی"
        # پیش‌نویس پاک شده و PDF/عکس رفته است
        assert "invnlp" not in ctx.user_data
        assert ctx.bot.photos and ctx.bot.docs

    async def test_confirm_twice_does_not_create_two_invoices(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        await _say(ctx, SENTENCE)
        update = _update(query=_Query("invnlp:confirm"))
        await handlers.on_invoice_nlp(update, ctx)
        await handlers.on_invoice_nlp(_update(query=_Query("invnlp:confirm")), ctx)
        assert len(store.list("invoices")) == 1

    async def test_stale_draft_is_reported_not_crashed(self, store):
        ctx = _ctx(store)
        query = _Query("invnlp:confirm")
        await handlers.on_invoice_nlp(_update(query=query), ctx)
        assert query.edits[-1]["text"] == texts.INVNLP_GONE
        assert store.list("invoices") == []


class TestManualEdit:
    async def test_edit_moves_into_the_builder_with_the_parsed_items(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        await _say(ctx, SENTENCE)
        query = _Query("invnlp:edit")
        await handlers.on_invoice_nlp(_update(query=query), ctx)

        assert ctx.user_data["flow"] == "invoice_items"
        assert ctx.user_data["invoice"]["customer_name"] == "علی"
        assert len(ctx.user_data["invoice"]["items"]) == 2
        assert "invnlp" not in ctx.user_data
        assert store.list("invoices") == [], "ویرایش نباید چیزی ثبت کند"
        assert keyboards.CANCEL_DATA in _cb(query.message.replies[-1]["reply_markup"])

    async def test_user_can_add_an_item_after_editing(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        await _say(ctx, SENTENCE)
        await handlers.on_invoice_nlp(_update(query=_Query("invnlp:edit")), ctx)
        await _say(ctx, "پرده ۱ ۹۰۰ هزار")
        assert len(ctx.user_data["invoice"]["items"]) == 3

    async def test_finalising_after_edit_uses_the_edited_items(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        await _say(ctx, SENTENCE)
        await handlers.on_invoice_nlp(_update(query=_Query("invnlp:edit")), ctx)
        await handlers.on_invoice_action(_update(query=_Query("inv:pop")), ctx)
        await handlers.on_invoice_action(_update(query=_Query("inv:done")), ctx)
        await handlers.on_invoice_draft(_update(query=_Query("invdraft:issue")), ctx)
        invoice = store.list("invoices")[0]
        items = store.list("invoice_items", lambda i: i.invoice_id == invoice.id)
        assert len(items) == 1


class TestFallbacks:
    async def test_a_transaction_sentence_still_becomes_a_transaction(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        await _say(ctx, "۵۰۰ هزار بابت فاکتور برق دادم")
        assert store.list("invoices") == []
        assert len(store.list("transactions")) == 1

    async def test_unparsable_invoice_sentence_falls_through(self, store):
        """«فاکتور» دارد ولی پارس نمی‌شود ⇒ نباید پیش‌نویس بسازد."""
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        await _say(ctx, "فاکتور دیروز چی شد؟")
        assert "invnlp" not in ctx.user_data
        assert store.list("invoices") == []

    async def test_the_manual_button_flow_is_untouched(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        await handlers.on_menu_action(_update(query=_Query("act:newinvoice")), ctx)
        assert ctx.user_data["flow"] == "invoice_customer"
        await _say(ctx, "رضا")
        assert ctx.user_data["flow"] == "invoice_items"

    async def test_a_sentence_while_inside_a_flow_is_not_hijacked(self, store):
        """وقتی کاربر وسطِ جریانِ دیگری است، جمله به همان جریان می‌رود."""
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        ctx.user_data["flow"] = "invoice_customer"
        ctx.user_data["invoice"] = {"items": [], "discount": 0, "shipping": 0}
        await _say(ctx, "فاکتور برای علی ۲ صندلی ۵۰۰ هزار")
        assert "invnlp" not in ctx.user_data
        assert ctx.user_data["invoice"]["customer_name"].startswith("فاکتور")


class TestRegistration:
    def test_handler_is_registered_and_does_not_collide_with_inv(self):
        import re
        from telegram.ext import ApplicationBuilder, CallbackQueryHandler
        application = ApplicationBuilder().token("1:AA").build()
        handlers.register(application)
        patterns = [h.pattern.pattern for group in application.handlers.values()
                    for h in group
                    if isinstance(h, CallbackQueryHandler) and h.pattern]
        matching = [p for p in patterns if re.match(p, "invnlp:confirm")]
        assert matching == [r"^invnlp:"], matching
