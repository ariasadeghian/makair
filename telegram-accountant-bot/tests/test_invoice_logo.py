"""تست‌های لوگو و مهر و امضا روی فاکتور (فاز ۱۷).

سه قرارداد اینجا محافظت می‌شوند:

۱. **باینری روی شیت نمی‌رود.** فقط ``file_id`` تلگرام ذخیره می‌شود.
۲. **هیچ خطایی فاکتور را زمین نمی‌زند.** تلگرامِ قطع، فایلِ خراب، یا نبودِ
   لوگو ⇒ فاکتور بدون لوگو صادر می‌شود، نه اینکه صادر نشود.
۳. **قفلِ سند شاملِ تصویر هم هست.** لوگویی که مشتری روی فاکتورش دیده،
   با عوض‌شدنِ لوگوی مغازه عوض نمی‌شود.
"""
import io
import os
from types import SimpleNamespace

import pytest

from hesabyar.bot import handlers, keyboards, texts
from hesabyar.config import Settings
from hesabyar.core import seller
from hesabyar.db.models import Invoice, User
from hesabyar.pdf import invoice_pdf
from hesabyar.services import images
from hesabyar.services import invoices as invoice_service
from hesabyar.services import subscription as sub_service
from hesabyar.services import transactions as tx

UID = 19_001
LOGO_ID = "AgACAgQAAxkBAAI-logo"
STAMP_ID = "AgACAgQAAxkBAAI-stamp"


# --- ابزار ----------------------------------------------------------------------


def _png(size=(120, 60), mode="RGB", color=(200, 30, 30)) -> bytes:
    from PIL import Image as PILImage

    buf = io.BytesIO()
    PILImage.new(mode, size, color if mode == "RGB" else (*color, 255)).save(
        buf, format="PNG")
    return buf.getvalue()


def _cb(markup):
    rows = getattr(markup, "inline_keyboard", None)
    return [b.callback_data for row in rows for b in row] if rows else []


class _File:
    def __init__(self, data: bytes):
        self._data = data

    async def download_as_bytearray(self):
        return bytearray(self._data)


class _Msg:
    def __init__(self, text="", photo_id="", doc=None):
        self.text = text
        self.replies: list = []
        self.chat = SimpleNamespace(id=UID, type="private", title=None)
        self.chat_id = UID
        self.message_id = 1
        self.entities = []
        self.reply_to_message = None
        self.photo = [SimpleNamespace(file_id=photo_id)] if photo_id else []
        self.document = doc

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
    """باتِ قلابی با ``get_file``؛ می‌شمارد چند بار دانلود خواسته‌ایم."""

    def __init__(self, files=None, fail=False):
        self.files = files or {}
        self.fail = fail
        self.calls: list = []
        self.sent: list = []
        self.photos: list = []
        self.docs: list = []

    async def get_file(self, file_id):
        self.calls.append(file_id)
        if self.fail:
            raise RuntimeError("تلگرام جواب نداد")
        return _File(self.files.get(file_id, _png()))

    async def send_message(self, chat_id, text=None, **kw):
        self.sent.append({"chat_id": chat_id, "text": text, **kw})

    async def send_photo(self, chat_id, photo=None, **kw):
        self.photos.append({"chat_id": chat_id, **kw})

    async def send_document(self, chat_id, document=None, **kw):
        self.docs.append({"chat_id": chat_id, **kw})

    async def edit_message_text(self, **kw):
        return None


def _ctx(store, bot=None, **settings):
    bot = bot or _Bot()
    app = SimpleNamespace(
        bot_data={"store": store, "settings": Settings(bot_token="x", **settings),
                  "bot_username": "hesabyarbot"},
        bot=bot,
    )
    return SimpleNamespace(application=app, bot=bot,
                           chat_data={}, user_data={}, args=[])


def _update(message=None, query=None):
    return SimpleNamespace(
        message=message, callback_query=query,
        effective_user=SimpleNamespace(id=UID, full_name="تست", username="t"),
        effective_chat=SimpleNamespace(id=UID, type="private", title=None),
        effective_message=message or (query.message if query else None),
    )


@pytest.fixture(autouse=True)
def _clean_cache():
    images.clear_cache()
    yield
    images.clear_cache()


# --- ۱) نرمال‌سازی تصویر ---------------------------------------------------------


class TestNormalize:
    def test_valid_png_survives(self):
        out = images.normalize(_png())
        assert out and out.startswith(b"\x89PNG")

    def test_garbage_is_rejected_not_raised(self):
        assert images.normalize("این PNG نیست".encode("utf-8")) is None

    def test_empty_is_rejected(self):
        assert images.normalize(b"") is None

    def test_oversized_is_rejected(self):
        assert images.normalize(b"x" * (images.MAX_BYTES + 1)) is None

    def test_big_image_is_shrunk(self):
        from PIL import Image as PILImage

        out = images.normalize(_png(size=(3000, 1500)))
        with PILImage.open(io.BytesIO(out)) as img:
            assert max(img.size) <= images.MAX_SIDE
            # نسبتِ ابعاد باید حفظ شود (۲:۱)
            assert abs(img.size[0] / img.size[1] - 2) < 0.05

    def test_small_image_is_left_alone(self):
        from PIL import Image as PILImage

        with PILImage.open(io.BytesIO(images.normalize(_png((120, 60))))) as img:
            assert img.size == (120, 60)

    def test_transparency_is_preserved(self):
        """لوگوی شفاف نباید روی کاغذ مربعِ سفید شود."""
        from PIL import Image as PILImage

        out = images.normalize(_png(mode="RGBA"))
        with PILImage.open(io.BytesIO(out)) as img:
            assert img.mode == "RGBA"

    def test_jpeg_becomes_png(self):
        from PIL import Image as PILImage

        buf = io.BytesIO()
        PILImage.new("RGB", (80, 40), (10, 10, 10)).save(buf, format="JPEG")
        out = images.normalize(buf.getvalue())
        assert out.startswith(b"\x89PNG")


# --- ۲) گرفتن فایل از تلگرام و کش ------------------------------------------------


class TestPathFor:
    async def test_empty_file_id_is_no_download(self):
        bot = _Bot()
        assert await images.path_for(bot, "") == ""
        assert bot.calls == []

    async def test_none_bot_is_safe(self):
        assert await images.path_for(None, LOGO_ID) == ""

    async def test_downloads_and_writes_a_real_file(self):
        bot = _Bot({LOGO_ID: _png()})
        path = await images.path_for(bot, LOGO_ID)
        assert path and os.path.isfile(path)
        with open(path, "rb") as fh:
            assert fh.read().startswith(b"\x89PNG")

    async def test_second_call_uses_cache(self):
        bot = _Bot({LOGO_ID: _png()})
        first = await images.path_for(bot, LOGO_ID)
        second = await images.path_for(bot, LOGO_ID)
        assert first == second
        assert bot.calls == [LOGO_ID], "بار دوم نباید دوباره دانلود کند"

    async def test_deleted_cache_file_is_refetched(self):
        bot = _Bot({LOGO_ID: _png()})
        path = await images.path_for(bot, LOGO_ID)
        os.remove(path)
        again = await images.path_for(bot, LOGO_ID)
        assert again == path and os.path.isfile(again)
        assert len(bot.calls) == 2

    async def test_different_ids_get_different_files(self):
        bot = _Bot({LOGO_ID: _png(), STAMP_ID: _png(size=(40, 40))})
        assert await images.path_for(bot, LOGO_ID) != await images.path_for(
            bot, STAMP_ID)

    async def test_telegram_failure_is_swallowed(self):
        assert await images.path_for(_Bot(fail=True), LOGO_ID) == ""

    async def test_broken_bytes_are_swallowed(self):
        bot = _Bot({LOGO_ID: b"nope"})
        assert await images.path_for(bot, LOGO_ID) == ""

    async def test_cache_is_bounded(self):
        bot = _Bot()
        for i in range(images.MAX_ENTRIES + 5):
            await images.path_for(bot, f"id-{i}")
        assert len(images._CACHE) <= images.MAX_ENTRIES


class TestSellerImages:
    async def test_reads_from_user_profile(self):
        bot = _Bot({LOGO_ID: _png()})
        user = User(id=UID, logo_file_id=LOGO_ID)
        art = await images.seller_images(bot, user)
        assert art["logo_path"] and art["stamp_path"] == ""

    async def test_reads_from_invoice_snapshot(self):
        bot = _Bot({STAMP_ID: _png()})
        inv = Invoice(user_id=UID, seller_stamp_file_id=STAMP_ID)
        art = await images.seller_images(bot, inv)
        assert art["stamp_path"] and art["logo_path"] == ""

    async def test_keys_match_renderer_arguments(self):
        """کلیدها مستقیم به رندرکننده پاس می‌شوند؛ نامشان قرارداد است."""
        art = await images.seller_images(_Bot(), User(id=UID))
        assert set(art) == {"logo_path", "stamp_path"}


# --- ۳) رندر روی سند --------------------------------------------------------------


class TestRender:
    def test_missing_file_is_not_an_error(self):
        assert invoice_pdf._fitted_image("/no/such/file.png", 50, 20) is None
        assert invoice_pdf._fitted_image("", 50, 20) is None

    def test_broken_file_is_not_an_error(self, tmp_path):
        bad = tmp_path / "bad.png"
        bad.write_bytes(b"not an image")
        assert invoice_pdf._fitted_image(str(bad), 50, 20) is None

    def test_aspect_ratio_is_kept(self, tmp_path):
        wide = tmp_path / "wide.png"
        wide.write_bytes(_png(size=(400, 100)))          # ۴:۱
        flowable = invoice_pdf._fitted_image(str(wide), 50, 20)
        assert abs(flowable.drawWidth / flowable.drawHeight - 4) < 0.01

    def test_image_is_never_enlarged_past_the_box(self, tmp_path):
        from reportlab.lib.units import mm

        tall = tmp_path / "tall.png"
        tall.write_bytes(_png(size=(100, 400)))          # بلند و باریک
        flowable = invoice_pdf._fitted_image(str(tall), 50, 20)
        assert flowable.drawHeight <= 20 * mm + 0.01
        assert flowable.drawWidth <= 50 * mm + 0.01

    def _invoice(self, **kw):
        from hesabyar.db.models import InvoiceItem

        inv = Invoice(user_id=UID, number="۱۴۰۵-۰۰۰۱",
                      customer_name="رضا", seller_business_name="قنادی", **kw)
        inv.items = [InvoiceItem(title="شیرینی", quantity=2, unit_price=450_000)]
        return inv

    def test_pdf_renders_with_logo_and_stamp(self, tmp_path):
        logo = tmp_path / "logo.png"
        logo.write_bytes(_png(mode="RGBA"))
        stamp = tmp_path / "stamp.png"
        stamp.write_bytes(_png(size=(200, 200)))
        out = tmp_path / "f.pdf"
        invoice_pdf.render_invoice_pdf(
            self._invoice(), None, str(out),
            logo_path=str(logo), stamp_path=str(stamp))
        assert out.stat().st_size > 1000

    def test_pdf_renders_without_them(self, tmp_path):
        out = tmp_path / "plain.pdf"
        invoice_pdf.render_invoice_pdf(self._invoice(), None, str(out))
        assert out.stat().st_size > 1000

    def test_bad_paths_do_not_break_the_invoice(self, tmp_path):
        out = tmp_path / "f.pdf"
        invoice_pdf.render_invoice_pdf(
            self._invoice(), None, str(out),
            logo_path="/gone.png", stamp_path="/gone2.png")
        assert out.stat().st_size > 1000

    def test_stamp_adds_its_caption(self, tmp_path):
        """پای سند باید بگوید این مهرِ کیست."""
        import fitz

        stamp = tmp_path / "stamp.png"
        stamp.write_bytes(_png(size=(200, 200)))
        with_stamp = tmp_path / "s.pdf"
        without = tmp_path / "n.pdf"
        invoice_pdf.render_invoice_pdf(
            self._invoice(), None, str(with_stamp), stamp_path=str(stamp))
        invoice_pdf.render_invoice_pdf(self._invoice(), None, str(without))
        with fitz.open(with_stamp) as a, fitz.open(without) as b:
            assert len(a[0].get_images()) == len(b[0].get_images()) + 1
            assert a[0].get_text().strip() != b[0].get_text().strip()

    def test_image_render_passes_paths_through(self, tmp_path):
        logo = tmp_path / "logo.png"
        logo.write_bytes(_png())
        out = tmp_path / "f.png"
        invoice_pdf.render_invoice_image(
            self._invoice(), None, str(out), logo_path=str(logo), dpi=72)
        assert out.stat().st_size > 500


# --- ۴) جریانِ کاربر ---------------------------------------------------------------


class TestSellerImageFlow:
    async def test_profile_screen_offers_both_images(self, store):
        user = await tx.get_or_create_user(store, UID)
        data = _cb(keyboards.seller_profile(user))
        assert "seller:img:logo_file_id" in data
        assert "seller:img:stamp_file_id" in data

    async def test_button_shows_whether_it_is_set(self, store):
        user = await tx.get_or_create_user(store, UID)
        rows = keyboards.seller_profile(user).inline_keyboard
        empty = [b.text for row in rows for b in row if "لوگو" in b.text][0]
        assert texts.SELLER_EMPTY_VALUE in empty
        user.logo_file_id = LOGO_ID
        rows = keyboards.seller_profile(user).inline_keyboard
        filled = [b.text for row in rows for b in row if "لوگو" in b.text][0]
        assert texts.SELLER_IMAGE_SET in filled
        assert LOGO_ID not in filled, "file_id به درد کاربر نمی‌خورد"

    async def test_pressing_the_button_asks_for_a_photo(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        query = _Query("seller:img:logo_file_id")
        await handlers.on_seller_action(_update(query=query), ctx)
        assert ctx.user_data["flow"] == "seller_image"
        assert ctx.user_data["seller_field"] == "logo_file_id"

    async def test_photo_is_stored_as_file_id(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        ctx.user_data.update(flow="seller_image", seller_field="logo_file_id")
        msg = _Msg(photo_id=LOGO_ID)
        await handlers.on_photo(_update(message=msg), ctx)
        assert (await tx.get_or_create_user(store, UID)).logo_file_id == LOGO_ID
        assert "flow" not in ctx.user_data
        assert "لوگو" in msg.replies[-1]["text"]

    async def test_photo_as_document_also_works(self, store):
        """لوگو را معمولاً «فایل» می‌فرستند تا فشرده نشود."""
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        ctx.user_data.update(flow="seller_image", seller_field="stamp_file_id")
        doc = SimpleNamespace(file_id=STAMP_ID, mime_type="image/png",
                              file_name="stamp.png")
        await handlers.on_document(_update(message=_Msg(doc=doc)), ctx)
        assert (await tx.get_or_create_user(store, UID)).stamp_file_id == STAMP_ID

    async def test_pdf_during_the_flow_is_refused(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        ctx.user_data.update(flow="seller_image", seller_field="logo_file_id")
        doc = SimpleNamespace(file_id="x", mime_type="application/pdf",
                              file_name="a.pdf")
        msg = _Msg(doc=doc)
        await handlers.on_document(_update(message=msg), ctx)
        assert "عکس" in msg.replies[-1]["text"]
        assert not (await tx.get_or_create_user(store, UID)).logo_file_id
        assert ctx.user_data["flow"] == "seller_image", "جریان نباید بپرد"

    async def test_text_during_the_flow_is_refused(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        ctx.user_data.update(flow="seller_image", seller_field="logo_file_id")
        msg = _Msg("لوگوم قرمزه")
        await handlers.on_text(_update(message=msg), ctx)
        assert "عکس" in msg.replies[-1]["text"]
        assert ctx.user_data["flow"] == "seller_image"

    async def test_receipt_ocr_is_not_triggered_by_the_logo(self, store):
        """عکسِ لوگو نباید به‌عنوان رسید خوانده شود."""
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        ctx.user_data.update(flow="seller_image", seller_field="logo_file_id")
        await handlers.on_photo(_update(message=_Msg(photo_id=LOGO_ID)), ctx)
        assert store.list("transactions") == []

    async def test_clearing_an_image(self, store):
        ctx = _ctx(store)
        user = await tx.get_or_create_user(store, UID)
        user.logo_file_id = LOGO_ID
        await store.update("users", user)
        await handlers.on_seller_action(
            _update(query=_Query("seller:clear:logo_file_id")), ctx)
        assert not (await tx.get_or_create_user(store, UID)).logo_file_id

    async def test_unknown_image_key_is_ignored(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        await handlers.on_seller_action(
            _update(query=_Query("seller:img:not_a_field")), ctx)
        assert "flow" not in ctx.user_data


# --- ۵) قفلِ سند --------------------------------------------------------------------


class TestDocumentLock:
    async def _user_with_art(self, store):
        user = await tx.get_or_create_user(store, UID)
        user.business_name = "قنادی شیرین"
        user.logo_file_id = LOGO_ID
        user.stamp_file_id = STAMP_ID
        await store.update("users", user)
        return user

    async def _issue(self, store):
        from hesabyar.core import jalali

        return await invoice_service.create_invoice(
            store, UID, customer_name="رضا",
            items=[{"title": "شیرینی", "quantity": 1, "unit_price": 100}],
            issue_date=jalali.now().date(),
        )

    async def test_issue_freezes_both_images(self, store):
        await self._user_with_art(store)
        inv = await self._issue(store)
        assert inv.seller_logo_file_id == LOGO_ID
        assert inv.seller_stamp_file_id == STAMP_ID

    async def test_changing_the_logo_does_not_touch_old_invoices(self, store):
        user = await self._user_with_art(store)
        inv = await self._issue(store)
        user.logo_file_id = "AgACAgQ-brand-new"
        await store.update("users", user)
        fresh = store.get("invoices", inv.id)
        assert fresh.seller_logo_file_id == LOGO_ID
        assert seller.image_of(fresh, "logo_file_id") == LOGO_ID

    async def test_old_invoices_fall_back_to_the_profile(self, store):
        """فاکتورهای پیش از اسنپ‌شات نباید بی‌سربرگ و بی‌لوگو بمانند."""
        user = await self._user_with_art(store)
        legacy = Invoice(user_id=UID, number="۱۴۰۴-۰۰۰۹", customer_name="رضا")
        assert seller.source_for(legacy, user) is user
        assert seller.image_of(seller.source_for(legacy, user),
                               "logo_file_id") == LOGO_ID

    async def test_snapshot_wins_over_the_profile(self, store):
        user = await self._user_with_art(store)
        inv = Invoice(user_id=UID, seller_business_name="نامِ قدیم",
                      seller_logo_file_id="AgACAgQ-old")
        assert seller.source_for(inv, user) is inv
        assert seller.image_of(inv, "logo_file_id") == "AgACAgQ-old"

    async def test_resend_downloads_the_frozen_logo(self, store):
        """ارسالِ دوباره‌ی فاکتور باید همان لوگوی روی سند را بیاورد."""
        bot = _Bot({LOGO_ID: _png(), STAMP_ID: _png()})
        ctx = _ctx(store, bot=bot)
        user = await self._user_with_art(store)
        await sub_service.get_or_create_subscription(store, UID)
        inv = await self._issue(store)
        user.logo_file_id = "AgACAgQ-brand-new"
        await store.update("users", user)
        await handlers._send_invoice_files(ctx, UID, inv, user, caption="ok")
        assert LOGO_ID in bot.calls
        assert "AgACAgQ-brand-new" not in bot.calls
        assert bot.photos and bot.docs

    async def test_preview_shows_the_logo_before_anything_is_issued(self, store):
        """پیش‌نمایش باید همان چیزی باشد که صادر می‌شود — با لوگو و مهر."""
        bot = _Bot({LOGO_ID: _png(), STAMP_ID: _png()})
        ctx = _ctx(store, bot=bot)
        await self._user_with_art(store)
        await sub_service.get_or_create_subscription(store, UID)
        ctx.user_data["invoice"] = {
            "customer_name": "رضا", "discount": 0, "shipping": 0,
            "items": [{"title": "شیرینی", "quantity": 1, "unit_price": 100}],
        }
        await handlers._preview_invoice(_update(message=_Msg()), ctx)
        assert sorted(bot.calls) == sorted([LOGO_ID, STAMP_ID])
        assert bot.photos, "پیش‌نمایشی نیامد"
        assert store.list("invoices") == [], "پیش‌نمایش نباید رکورد بسازد"

    async def test_a_dead_telegram_still_sends_the_invoice(self, store):
        """قرارداد: نبودِ لوگو نباید فاکتور را زمین بزند."""
        bot = _Bot(fail=True)
        ctx = _ctx(store, bot=bot)
        user = await self._user_with_art(store)
        inv = await self._issue(store)
        await handlers._send_invoice_files(ctx, UID, inv, user, caption="ok")
        assert bot.photos and bot.docs, "فاکتور باید صادر شود، فقط بدون لوگو"
