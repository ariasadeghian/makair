import os

from PIL import ImageFont

from hesabyar.core import jalali
from hesabyar.db.models import Kind
from hesabyar.pdf.invoice_pdf import shape_fa
from hesabyar.services import dashboard
from hesabyar.services import transactions as tx

UID = 88

_PNG = b"\x89PNG\r\n\x1a\n"


async def test_dashboard_with_data(store, tmp_path):
    user = await tx.get_or_create_user(store, UID)
    user.business_name = "کسب‌وکار تست"
    now = jalali.now()
    await tx.add_transaction(store, UID, kind=Kind.INCOME, amount=2_000_000,
                             category="فروش کالا", description="فروش", occurred_at=now)
    await tx.add_transaction(store, UID, kind=Kind.EXPENSE, amount=800_000,
                             category="اجاره", description="اجاره", occurred_at=now)
    await tx.add_transaction(store, UID, kind=Kind.EXPENSE, amount=300_000,
                             category="قبوض", description="برق", occurred_at=now)

    out = str(tmp_path / "dash.png")
    dashboard.render_dashboard_png(store, UID, out, now=now, business=user)
    with open(out, "rb") as fh:
        head = fh.read(8)
    assert head == _PNG
    assert os.path.getsize(out) > 5000


async def test_dashboard_no_data(store, tmp_path):
    await tx.get_or_create_user(store, UID)
    out = str(tmp_path / "empty.png")
    dashboard.render_dashboard_png(store, UID, out, now=jalali.now())
    with open(out, "rb") as fh:
        assert fh.read(8) == _PNG


async def test_dashboard_long_business_name(store, tmp_path):
    """نامِ خیلی بلند نباید رندر را بترکاند."""
    user = await tx.get_or_create_user(store, UID)
    user.business_name = "فروشگاه لوازم خانگی و آشپزخانه و دکوراسیون داخلی مدرن " * 2
    now = jalali.now()
    await tx.add_transaction(store, UID, kind=Kind.INCOME, amount=1_000_000,
                             category="فروش کالا", description="", occurred_at=now)
    out = str(tmp_path / "long.png")
    dashboard.render_dashboard_png(store, UID, out, now=now, business=user)
    with open(out, "rb") as fh:
        assert fh.read(8) == _PNG


async def test_dashboard_mixed_persian_latin_name(store, tmp_path):
    """نامِ کسب‌وکارِ ترکیبیِ فارسی/لاتین (مثلاً برند خارجی) نباید بشکند."""
    user = await tx.get_or_create_user(store, UID)
    user.business_name = "کافه Roasters تهران"
    now = jalali.now()
    await tx.add_transaction(store, UID, kind=Kind.INCOME, amount=500_000,
                             category="فروش", description="", occurred_at=now)
    out = str(tmp_path / "mixed.png")
    dashboard.render_dashboard_png(store, UID, out, now=now, business=user)
    with open(out, "rb") as fh:
        assert fh.read(8) == _PNG


async def test_dashboard_single_expense_category(store, tmp_path):
    """یک‌دسته یعنی پایِ ۱۰۰٪ — نباید تقسیم‌بر‌صفر یا زاویه‌ی نامعتبر بدهد."""
    user = await tx.get_or_create_user(store, UID)
    now = jalali.now()
    await tx.add_transaction(store, UID, kind=Kind.EXPENSE, amount=500_000,
                             category="خرید آرد", description="", occurred_at=now)
    out = str(tmp_path / "single.png")
    dashboard.render_dashboard_png(store, UID, out, now=now, business=user)
    with open(out, "rb") as fh:
        assert fh.read(8) == _PNG


# --- شکل‌دهیِ متنِ فارسی: نگهبانِ رگرسیون -----------------------------------------
#
# باگِ اصلی این بود: matplotlib روی برخی محیط‌ها متنِ از‌پیش‌شکل‌داده‌شده
# (خروجیِ arabic_reshaper + python-bidi) را دوباره شکل می‌داد — نتیجه حروفِ
# جدا و معکوس بود. راه‌حل: متنِ فارسی با Pillow و
# ``layout_engine=ImageFont.Layout.BASIC`` (چیدمانِ ساده، بدون شکل‌دهیِ
# خودکار) روی یک تصویر رندر و بعد وارد نمودار می‌شود. این تست‌ها دقیقاً
# همین مکانیزم را قفل می‌کنند تا کسی سهواً برنگرداندش.


def test_fa_matches_the_proven_pdf_shaping():
    """شکل‌دهیِ داشبورد باید با شکل‌دهیِ اثبات‌شده‌ی PDF فاکتور یکی باشد."""
    for text in ("داشبورد مالی", "درآمد این ماه", "سهم دسته‌های هزینه (این ماه)",
                 "۱٬۴۴۴٬۰۰۰ تومان"):
        assert dashboard._fa(text) == shape_fa(text)


def test_pil_font_uses_basic_layout_engine():
    """هسته‌ی رفعِ باگ: بدونِ شکل‌دهیِ خودکار، صرف‌نظر از اینکه HarfBuzz/Raqm
    روی سیستم نصب باشد یا نه — وگرنه متنِ از‌پیش‌شکل‌داده‌شده دوباره شکل
    می‌گیرد و به‌هم می‌ریزد."""
    font = dashboard._pil_font(40)
    assert font.layout_engine == ImageFont.Layout.BASIC


def test_shaped_text_renders_narrower_than_unshaped():
    """اگر شکل‌دهی واقعاً کار کند، حروفِ چسبیده باید از حروفِ جدا باریک‌تر
    دربیایند — این تفاوتِ عرض یعنی حروف واقعاً به هم چسبیده‌اند، نه اینکه
    هرکدام به‌صورتِ مجزا (فرمِ isolated) کنار هم افتاده باشند."""
    word = "سلام"
    joined = dashboard._text_rgba(dashboard._fa(word), 24, "black")
    isolated = dashboard._text_rgba(word, 24, "black")
    assert joined.width < isolated.width


def test_text_rgba_produces_a_real_image():
    img = dashboard._text_rgba(dashboard._fa("مانده"), 20, "black")
    assert img.mode == "RGBA"
    assert img.width > 4 and img.height > 4
    # حداقل یک پیکسلِ غیرشفاف باید باشد، وگرنه یعنی چیزی رسم نشده
    alpha = img.getchannel("A")
    assert alpha.getextrema()[1] > 0


def test_text_rgba_handles_empty_string():
    img = dashboard._text_rgba("", 20, "black")
    assert img.width >= 1 and img.height >= 1


def test_persian_digits_and_mixed_content_render():
    """رقمِ فارسی کنارِ کلمه‌ی فارسی، و ترکیبِ فارسی+لاتین — نباید خطا بدهد."""
    for text in ("۱٬۴۴۴٬۰۰۰ تومان", "کافه Roasters", "۳۳٪", "-۵۰۰٬۰۰۰ تومان"):
        img = dashboard._text_rgba(dashboard._fa(text), 16, "black")
        assert img.width > 0 and img.height > 0
