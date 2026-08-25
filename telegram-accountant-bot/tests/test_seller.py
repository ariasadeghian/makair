"""تست‌های سربرگ فاکتور و قفلِ سند (فاز ۱۵).

دو قرارداد اینجا آزموده می‌شوند:
۱. مشخصات یک‌بار وارد می‌شوند و روی هر فاکتور می‌نشینند.
۲. فاکتورِ صادرشده **سند** است — با تغییرِ بعدیِ پروفایل عوض نمی‌شود.
"""
from types import SimpleNamespace

import pytest

from hesabyar.bot import handlers, keyboards, texts
from hesabyar.config import Settings
from hesabyar.core import jalali, seller
from hesabyar.db.models import Invoice, User
from hesabyar.services import invoices as invoice_service
from hesabyar.services import transactions as tx

UID = 17_001


def _cb(markup):
    rows = getattr(markup, "inline_keyboard", None)
    return [b.callback_data for row in rows for b in row] if rows else []


def _labels(markup):
    rows = getattr(markup, "inline_keyboard", None)
    return [b.text for row in rows for b in row] if rows else []


# --- فیلدها و اعتبارسنجی -----------------------------------------------------------


class TestFieldDefinitions:
    def test_every_field_exists_on_the_user_model(self):
        missing = [f.key for f in seller.FIELDS if f.key not in User.COLUMNS]
        assert not missing, f"ستون ندارند: {missing}"

    def test_every_field_has_a_snapshot_column_on_invoice(self):
        missing = [c for c in seller.SNAPSHOT_COLUMNS if c not in Invoice.COLUMNS]
        assert not missing, f"اسنپ‌شات ندارند: {missing}"

    def test_business_name_comes_first(self):
        assert seller.FIELDS[0].key == "business_name"

    def test_every_field_has_a_label_icon_and_hint(self):
        for f in seller.FIELDS:
            assert f.label and f.icon and f.hint, f.key

    def test_keys_are_unique(self):
        keys = [f.key for f in seller.FIELDS]
        assert len(keys) == len(set(keys))


class TestValidation:
    @pytest.mark.parametrize("raw,clean", [
        ("۰۲۱۸۸۱۲۳۴۵۶", "02188123456"),
        ("021-8812-3456", "02188123456"),
        ("۰۹۱۲ ۱۲۳ ۴۵۶۷", "09121234567"),
    ])
    def test_phone_normalises_persian_digits_and_separators(self, raw, clean):
        assert seller.BY_KEY["phone"].clean(raw) == clean

    @pytest.mark.parametrize("bad", ["", "   ", "۱۲۳", "الو"])
    def test_phone_rejects_nonsense(self, bad):
        assert seller.BY_KEY["phone"].clean(bad) is None

    @pytest.mark.parametrize("raw", [
        "@myshop", "myshop", "instagram.com/myshop",
        "https://www.instagram.com/myshop/", "https://instagram.com/myshop?igshid=1",
    ])
    def test_instagram_is_reduced_to_a_handle(self, raw):
        assert seller.BY_KEY["instagram"].clean(raw) == "myshop"

    def test_instagram_rejects_persian(self):
        assert seller.BY_KEY["instagram"].clean("مغازه من") is None

    @pytest.mark.parametrize("raw,clean", [
        ("shop@example.com", "shop@example.com"),
        (" shop@example.com ", "shop@example.com"),
    ])
    def test_email(self, raw, clean):
        assert seller.BY_KEY["email"].clean(raw) == clean

    @pytest.mark.parametrize("bad", ["shop", "shop@", "@example.com", "a@b"])
    def test_email_rejects_broken_addresses(self, bad):
        assert seller.BY_KEY["email"].clean(bad) is None

    def test_website_drops_the_scheme(self):
        assert seller.BY_KEY["website"].clean("https://myshop.ir/") == "myshop.ir"

    def test_postal_code_must_be_ten_digits(self):
        assert seller.BY_KEY["postal_code"].clean("۱۲۳۴۵۶۷۸۹۰") == "1234567890"
        assert seller.BY_KEY["postal_code"].clean("12345") is None

    def test_address_keeps_persian_text_and_squeezes_spaces(self):
        assert seller.BY_KEY["address"].clean("  تهران،  خیابان  آزادی ") == \
            "تهران، خیابان آزادی"

    def test_empty_input_is_rejected_everywhere(self):
        for f in seller.FIELDS:
            assert f.clean("   ") is None, f.key


# --- سربرگِ چاپی --------------------------------------------------------------------


def _filled(**kw):
    base = dict(id=UID, business_name="قنادی شیرین", address="تهران، خیابان آزادی",
                phone="02188123456", mobile="09121234567",
                postal_code="1234567890", email="shop@example.com",
                instagram="shirin", website="shirin.ir",
                economic_code="411", national_id="10101")
    base.update(kw)
    return User(**base)


class TestPrintedHeader:
    def test_numbers_print_in_persian_digits(self):
        """رقمِ لاتین وسطِ متنِ راست‌چین جای‌به‌جا می‌شود؛ ذخیره لاتین، چاپ فارسی."""
        user = _filled()
        assert user.phone == "02188123456", "ذخیره باید لاتین بماند"
        assert seller.display(user, "phone") == "۰۲۱۸۸۱۲۳۴۵۶"
        assert seller.display(user, "email") == "shop@example.com", "ایمیل نه"
        assert seller.display(user, "website") == "shirin.ir", "وب‌سایت نه"

    def test_address_and_postal_share_a_line(self):
        lines = seller.header_lines(_filled())
        assert lines[0] == "نشانی: تهران، خیابان آزادی — کد پستی ۱۲۳۴۵۶۷۸۹۰"

    def test_contacts_are_joined_on_one_line(self):
        line = seller.header_lines(_filled())[1]
        for piece in ("۰۲۱۸۸۱۲۳۴۵۶", "۰۹۱۲۱۲۳۴۵۶۷", "shop@example.com",
                      "@shirin", "shirin.ir"):
            assert piece in line

    def test_tax_numbers_get_their_own_line(self):
        assert "شماره اقتصادی: ۴۱۱" in seller.header_lines(_filled())[-1]

    def test_empty_fields_produce_no_line(self):
        assert seller.header_lines(User(id=UID, business_name="فقط اسم")) == []

    def test_postal_alone_still_prints(self):
        lines = seller.header_lines(User(id=UID, postal_code="1234567890"))
        assert lines == ["کد پستی: ۱۲۳۴۵۶۷۸۹۰"]

    def test_nothing_breaks_on_none(self):
        assert seller.header_lines(None) == []

    def test_completeness_check(self):
        assert seller.is_complete_enough(_filled()) is True
        assert seller.is_complete_enough(User(id=UID, business_name="فقط اسم")) is False
        assert seller.is_complete_enough(User(id=UID, phone="02188123456")) is False


# --- قفلِ سند --------------------------------------------------------------------


class TestDocumentLock:
    async def _invoice_for(self, store, **profile):
        user = await tx.get_or_create_user(store, UID)
        for key, value in profile.items():
            setattr(user, key, value)
        await store.update("users", user)
        return await invoice_service.create_invoice(
            store, UID, customer_name="رضا",
            items=[{"title": "شیرینی", "quantity": 1, "unit_price": 500_000}],
            issue_date=jalali.now().date(),
        )

    async def test_the_profile_is_frozen_onto_the_invoice(self, store):
        invoice = await self._invoice_for(
            store, business_name="قنادی شیرین", phone="02188123456",
            address="تهران، آزادی",
        )
        assert invoice.seller_business_name == "قنادی شیرین"
        assert invoice.seller_phone == "02188123456"
        assert invoice.seller_address == "تهران، آزادی"

    async def test_changing_the_profile_does_not_change_an_old_invoice(self, store):
        """همان باگی که سند را با گذشتِ زمان عوض می‌کرد."""
        invoice = await self._invoice_for(
            store, business_name="قنادی شیرین", phone="02188123456")
        old_id = invoice.id

        user = await tx.get_or_create_user(store, UID)
        user.phone = "02199999999"
        user.business_name = "قنادی جدید"
        await store.update("users", user)

        again = store.get("invoices", old_id)
        assert again.seller_phone == "02188123456"
        assert again.seller_business_name == "قنادی شیرین"

    async def test_a_later_invoice_gets_the_new_profile(self, store):
        first = await self._invoice_for(store, business_name="قنادی شیرین")
        second = await self._invoice_for(store, business_name="قنادی جدید")
        assert first.seller_business_name == "قنادی شیرین"
        assert second.seller_business_name == "قنادی جدید"

    async def test_the_snapshot_survives_a_round_trip_through_the_sheet(self, store):
        invoice = await self._invoice_for(
            store, business_name="قنادی شیرین", instagram="shirin")
        row = dict(zip(Invoice.COLUMNS, invoice.to_row()))
        restored = Invoice.from_row(row)
        assert restored.seller_business_name == "قنادی شیرین"
        assert restored.seller_instagram == "shirin"

    def test_old_invoices_without_a_snapshot_fall_back_to_the_user(self):
        """فاکتورهای قبل از این فاز اسنپ‌شات ندارند و نباید سربرگشان خالی شود."""
        old = Invoice.from_row({"id": "1", "number": "۱۴۰۵-۰۰۰۱"})
        assert seller.value_of(old, "business_name") == ""
        user = _filled()
        source = old if seller.value_of(old, "business_name") else user
        assert seller.value_of(source, "business_name") == "قنادی شیرین"

    def test_value_of_prefers_the_snapshot_over_the_live_profile(self):
        invoice = Invoice(id=1, seller_business_name="نامِ قفل‌شده")
        assert seller.value_of(invoice, "business_name") == "نامِ قفل‌شده"


# --- ابزار شبیه‌سازی -----------------------------------------------------------------


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
    async def send_message(self, chat_id, text=None, **kw):
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


async def _open_profile(ctx):
    query = _Query("act:bizname")
    await handlers.on_menu_action(_update(query=query), ctx)
    return query.message


async def _press(ctx, data, message=None):
    query = _Query(data, message=message)
    await handlers.on_seller_action(_update(query=query), ctx)
    return query


async def _say(ctx, text):
    msg = _Msg(text)
    await handlers.on_text(_update(message=msg), ctx)
    return msg


# --- صفحه‌ی سربرگ ------------------------------------------------------------------


class TestProfileScreen:
    async def test_the_business_menu_opens_it(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        msg = await _open_profile(ctx)
        assert texts.SELLER_HEADER in msg.replies[-1]["text"]

    async def test_one_button_per_field_plus_preview_and_back(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        msg = await _open_profile(ctx)
        data = _cb(msg.markup)
        for f in seller.FIELDS:
            assert f"seller:set:{f.key}" in data, f.key
        assert data[-2:] == ["seller:preview", "menu:main"]

    async def test_buttons_show_the_current_value(self, store):
        ctx = _ctx(store)
        user = await tx.get_or_create_user(store, UID)
        user.business_name = "قنادی شیرین"
        await store.update("users", user)

        msg = await _open_profile(ctx)
        labels = _labels(msg.markup)
        assert any("قنادی شیرین" in label for label in labels)
        assert any(texts.SELLER_EMPTY_VALUE in label for label in labels), \
            "فیلدهای خالی باید «—» نشان بدهند"

    async def test_a_long_value_is_trimmed_on_the_button(self, store):
        ctx = _ctx(store)
        user = await tx.get_or_create_user(store, UID)
        user.address = "الف" * 120
        await store.update("users", user)
        msg = await _open_profile(ctx)
        assert all(len(label) < 60 for label in _labels(msg.markup))

    async def test_an_incomplete_profile_is_nudged(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        msg = await _open_profile(ctx)
        assert texts.SELLER_INCOMPLETE.strip() in msg.replies[-1]["text"]

    async def test_a_complete_profile_is_not_nudged(self, store):
        ctx = _ctx(store)
        user = await tx.get_or_create_user(store, UID)
        user.business_name, user.phone = "قنادی شیرین", "02188123456"
        await store.update("users", user)
        msg = await _open_profile(ctx)
        assert texts.SELLER_INCOMPLETE.strip() not in msg.replies[-1]["text"]


class TestEditingFields:
    async def test_setting_a_field(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        await _open_profile(ctx)

        query = await _press(ctx, "seller:set:phone")
        assert ctx.user_data["flow"] == "seller_field"
        assert ctx.user_data["seller_field"] == "phone"
        assert keyboards.CANCEL_DATA in _cb(query.message.markup)

        msg = await _say(ctx, "۰۲۱۸۸۱۲۳۴۵۶")
        assert (await tx.get_or_create_user(store, UID)).phone == "02188123456"
        assert "flow" not in ctx.user_data
        assert "02188123456" in msg.replies[-1]["text"]
        # بعدش دوباره صفحه‌ی سربرگ می‌آید
        assert "seller:set:phone" in _cb(msg.markup)

    async def test_a_bad_value_is_rejected_and_reasked(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        await _open_profile(ctx)
        await _press(ctx, "seller:set:email")

        msg = await _say(ctx, "این ایمیل نیست")
        assert ctx.user_data["flow"] == "seller_field", "باید منتظر بماند"
        assert "❌" in msg.replies[-1]["text"]
        assert not (await tx.get_or_create_user(store, UID)).email

    async def test_clearing_a_field(self, store):
        ctx = _ctx(store)
        user = await tx.get_or_create_user(store, UID)
        user.instagram = "shirin"
        await store.update("users", user)

        await _open_profile(ctx)
        query = await _press(ctx, "seller:clear:instagram")
        assert (await tx.get_or_create_user(store, UID)).instagram == ""
        assert texts.SELLER_CLEARED.format(label="اینستاگرام") in \
            query.message.replies[-1]["text"]

    async def test_each_field_can_be_set_through_the_bot(self, store):
        """هر ۱۰ فیلد از رابط کاربری قابل ثبت است."""
        samples = {
            "business_name": "قنادی شیرین", "address": "تهران، آزادی",
            "phone": "02188123456", "mobile": "09121234567",
            "postal_code": "1234567890", "email": "shop@example.com",
            "instagram": "@shirin", "website": "shirin.ir",
            "economic_code": "411222", "national_id": "10101010",
        }
        assert set(samples) == {f.key for f in seller.FIELDS}, "نمونه‌ها ناقص‌اند"

        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        for key, value in samples.items():
            await _press(ctx, f"seller:set:{key}")
            await _say(ctx, value)
        user = await tx.get_or_create_user(store, UID)
        for key in samples:
            assert getattr(user, key), key

    async def test_an_unknown_field_is_ignored(self, store):
        ctx = _ctx(store)
        query = await _press(ctx, "seller:set:nope")
        assert query.message.replies == []
        assert "flow" not in ctx.user_data

    async def test_back_to_the_profile_from_a_field(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        await _press(ctx, "seller:set:phone")
        query = await _press(ctx, "seller:open")
        assert "flow" not in ctx.user_data
        assert texts.SELLER_HEADER in query.message.replies[-1]["text"]


class TestPreview:
    async def test_preview_shows_the_printed_header(self, store):
        ctx = _ctx(store)
        user = await tx.get_or_create_user(store, UID)
        user.business_name, user.phone = "قنادی شیرین", "02188123456"
        await store.update("users", user)

        query = await _press(ctx, "seller:preview")
        body = query.message.replies[-1]["text"]
        assert "قنادی شیرین" in body and "۰۲۱۸۸۱۲۳۴۵۶" in body

    async def test_preview_explains_the_document_lock(self, store):
        ctx = _ctx(store)
        user = await tx.get_or_create_user(store, UID)
        user.business_name = "قنادی شیرین"
        await store.update("users", user)
        query = await _press(ctx, "seller:preview")
        assert "قفل" in query.message.replies[-1]["text"]

    async def test_preview_without_a_name_says_so(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        query = await _press(ctx, "seller:preview")
        assert query.message.replies[-1]["text"] == texts.SELLER_PREVIEW_EMPTY


class TestRegistration:
    def test_handler_is_registered(self):
        import re
        from telegram.ext import ApplicationBuilder, CallbackQueryHandler
        application = ApplicationBuilder().token("1:AA").build()
        handlers.register(application)
        patterns = [h.pattern.pattern for group in application.handlers.values()
                    for h in group
                    if isinstance(h, CallbackQueryHandler) and h.pattern]
        for data in ("seller:set:phone", "seller:clear:phone",
                     "seller:preview", "seller:open"):
            assert [p for p in patterns if re.match(p, data)] == [r"^seller:"], data
