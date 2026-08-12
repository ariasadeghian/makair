"""داشبورد تصویری وضعیت مالی کسب‌وکار.

یک تصویر PNG می‌سازد شامل: شاخص‌های کلیدی (درآمد/هزینه/مانده‌ی ماه جاری)،
نمودار میله‌ای درآمد و هزینه‌ی چند ماه اخیر، و نمودار سهم دسته‌های هزینه.

--- چرا متنِ فارسی این‌جا خودش را رندر می‌کند، نه matplotlib -----------------------

matplotlib روی این محیط، اگر متنِ از‌پیش‌شکل‌داده‌شده (خروجیِ
``arabic_reshaper`` + ``python-bidi``، همان تکنیکی که برای PDF فاکتور در
``hesabyar/pdf/invoice_pdf.py`` جواب می‌دهد) را دریافت کند، آن را **دوباره**
شکل می‌دهد: حروف را به فرمِ پایه برمی‌گرداند و بر اساسِ همسایگیِ نادرست
(چون ترتیب از قبل بصری شده) دوباره می‌چسباند — نتیجه حروفِ جدا و
معکوس است. اگر متنِ خامِ شکل‌نداده به matplotlib داده شود، خودش را درست
نشان می‌دهد — یعنی روی *این* محیط یک لایه‌ی شکل‌دهیِ خودکار (احتمالاً
HarfBuzz از طریقِ FreeType) هست. مشکل اینجاست که **نمی‌شود مطمئن بود این
لایه روی سرورِ production هم هست** — اگر نباشد، متنِ خام دقیقاً همان مشکلِ
کلاسیکِ «حروفِ فارسیِ جدا و برعکس» را نشان می‌دهد که کل دلیلِ وجودِ
``arabic_reshaper`` است.

پس به‌جای تکیه به رفتارِ نامشخصِ فونت/سیستم‌عاملِ سرور، متنِ فارسی این‌جا
با Pillow و ``layout_engine=ImageFont.Layout.BASIC`` روی یک تصویرِ RGBA
جداگانه رندر می‌شود — BASIC یعنی چیدمانِ ساده‌ی حرف‌به‌حرف، دقیقاً مثل
reportlab، بدون هیچ شکل‌دهیِ خودکار، صرف‌نظر از اینکه HarfBuzz/Raqm روی
سیستم نصب باشد یا نه. این تصویر با ``OffsetImage``/``AnnotationBbox`` روی
نمودار می‌نشیند. نتیجه‌اش رفتاری قطعی و یکسان روی هر محیطی است.
"""
from __future__ import annotations

import datetime as dt
import math
import os
from typing import Optional

import arabic_reshaper
import jdatetime
import matplotlib

matplotlib.use("Agg")  # بدون نیاز به نمایشگر

import matplotlib.pyplot as plt  # noqa: E402
from bidi.algorithm import get_display  # noqa: E402
from matplotlib.offsetbox import AnnotationBbox, OffsetImage  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
from PIL import Image as PILImage  # noqa: E402
from PIL import ImageDraw, ImageFont  # noqa: E402

from ..db.store import Store  # noqa: E402

from ..core import jalali, money  # noqa: E402
from . import transactions as tx_service  # noqa: E402

_FONT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "pdf", "fonts", "Vazirmatn-Regular.ttf"
)

# پالت رنگ
_INCOME = "#2e9e5b"
_EXPENSE = "#e0533d"
_BALANCE = "#2f6fb0"
_MUTED = "#8a8a8a"
_PIE = ["#e0533d", "#e8a33d", "#c65b9c", "#2f6fb0", "#6a7f8c"]

#: نمونه‌برداریِ اضافه برای تیزیِ متن (تصویر در ۴برابرِ اندازه رندر می‌شود
#: و با zoom کوچک می‌شود) — وگرنه لبه‌ی حروف در اندازه‌ی چاپی پلکانی می‌شود.
_SS = 4


# --- شکل‌دهیِ متن (بدون تغییر نسبت به نسخه‌ی قبلی) --------------------------------


def _fa(text) -> str:
    """شکل‌دهی متن فارسی: حروف به فرمِ چسبیده + ترتیبِ بصریِ راست‌به‌چپ.

    دقیقاً همان یک‌خطی‌ای که در ``invoice_pdf.shape_fa`` هم هست — منطقِ
    شکل‌دهی درست است؛ باگ جای دیگری بود (رجوع به مستندِ بالای فایل).
    """
    return get_display(arabic_reshaper.reshape(str(text)))


# --- رندرِ متنِ فارسی روی تصویر (به‌جای متنِ نیتیوِ matplotlib) --------------------

_font_cache: dict[int, "ImageFont.FreeTypeFont"] = {}


def _pil_font(size_px: int) -> "ImageFont.FreeTypeFont":
    font = _font_cache.get(size_px)
    if font is None:
        font = ImageFont.truetype(
            _FONT_PATH, size_px, layout_engine=ImageFont.Layout.BASIC
        )
        _font_cache[size_px] = font
    return font


def _text_rgba(text: str, size_pt: float, color: str) -> "PILImage.Image":
    """متنِ (از قبل شکل‌داده‌شده‌ی) فارسی را به یک تصویرِ RGBA کراپ‌شده تبدیل می‌کند."""
    px = max(1, round(size_pt * _SS))
    font = _pil_font(px)
    probe = ImageDraw.Draw(PILImage.new("RGBA", (1, 1)))
    bbox = probe.textbbox((0, 0), text, font=font)
    pad = 2
    w = (bbox[2] - bbox[0]) + pad * 2
    h = (bbox[3] - bbox[1]) + pad * 2
    img = PILImage.new("RGBA", (max(w, 1), max(h, 1)), (0, 0, 0, 0))
    ImageDraw.Draw(img).text(
        (pad - bbox[0], pad - bbox[1]), text, font=font, fill=color
    )
    return img


#: تناظرِ ha/va با box_alignment در AnnotationBbox (۰..۱ روی هر محور).
_HA = {"left": 0.0, "center": 0.5, "right": 1.0}
_VA = {"bottom": 0.0, "center": 0.5, "top": 1.0}


def _annotate(
    target,
    xy: tuple,
    text: str,
    size_pt: float,
    color: str,
    *,
    ha: str = "center",
    va: str = "center",
    xycoords="axes fraction",
    zorder: int = 5,
    shape: bool = True,
):
    """جایگزینِ ``ax.text``/``fig.text``: متن را رندر و روی نمودار می‌گذارد.

    ``target`` می‌تواند ``Axes`` یا ``Figure`` باشد (هر دو ``add_artist`` دارند).
    ``shape=False`` برای متنی که از قبل شکل داده شده (یا نیاز به شکل‌دهی ندارد،
    مثل رشته‌ی فقط‌رقمیِ درصد).
    """
    rendered = _fa(text) if shape else text
    img = _text_rgba(rendered, size_pt, color)
    offset = OffsetImage(img, zoom=1.0 / _SS, dpi_cor=True)
    box = AnnotationBbox(
        offset, xy, xycoords=xycoords, frameon=False,
        box_alignment=(_HA[ha], _VA[va]), pad=0, zorder=zorder,
    )
    box.set_clip_on(False)
    target.add_artist(box)
    return box


# --- محاسبات (بدون تغییر) ---------------------------------------------------------


def _month_window(
    now: dt.datetime, back: int
) -> tuple[dt.datetime, dt.datetime, str]:
    """بازه و نام ماهی که ``back`` ماه پیش از ماه جاری شمسی است."""
    j = jalali.to_jalali(now)
    total = j.year * 12 + (j.month - 1) - back
    year, month0 = divmod(total, 12)
    month = month0 + 1
    start_g = jdatetime.date(year, month, 1).togregorian()
    year2, month20 = divmod(total + 1, 12)
    next_g = jdatetime.date(year2, month20 + 1, 1).togregorian()
    tz = now.tzinfo
    start = dt.datetime(start_g.year, start_g.month, start_g.day, tzinfo=tz)
    end = dt.datetime(next_g.year, next_g.month, next_g.day, tzinfo=tz) - dt.timedelta(
        seconds=1
    )
    if end > now:  # ماه جاری هنوز تمام نشده
        end = now
    return start, end, jalali.month_name(month)


def _gather(store: Store, user_id: int, now: dt.datetime, months: int):
    monthly = []
    for back in range(months - 1, -1, -1):
        start, end, label = _month_window(now, back)
        s = tx_service.summary(store, user_id, start, end)
        monthly.append(
            {"label": label, "income": s["income"], "expense": s["expense"]}
        )
    c_start, c_end = jalali.month_bounds(now)
    current = tx_service.summary(store, user_id, c_start, c_end)
    return monthly, current


# --- رندر اصلی ---------------------------------------------------------------------


def render_dashboard_png(
    store: Store,
    user_id: int,
    out_path: str,
    now: Optional[dt.datetime] = None,
    business=None,
    months: int = 6,
) -> str:
    """داشبورد مالی کاربر را در یک فایل PNG می‌سازد و مسیرش را برمی‌گرداند."""
    now = now or jalali.now()
    monthly, current = _gather(store, user_id, now, months)
    has_data = any(m["income"] or m["expense"] for m in monthly)

    fig = plt.figure(figsize=(10, 7.2), dpi=110)
    fig.patch.set_facecolor("white")

    title = getattr(business, "business_name", None) or "کسب‌وکار من"
    _annotate(fig, (0.5, 0.97), f"داشبورد مالی — {title}", 17, "black",
             xycoords="figure fraction", va="top", zorder=10)
    _annotate(fig, (0.5, 0.915), f"تا {jalali.format_date(now)}", 10, _MUTED,
             xycoords="figure fraction", va="top", zorder=10)

    gs = fig.add_gridspec(
        2, 2, height_ratios=[0.8, 3], hspace=0.35, wspace=0.25,
        left=0.07, right=0.95, top=0.87, bottom=0.08,
    )

    # --- شاخص‌های کلیدی ------------------------------------------------------
    ax_kpi = fig.add_subplot(gs[0, :])
    ax_kpi.axis("off")
    kpis = [
        ("درآمد این ماه", current["income"], _INCOME),
        ("هزینه این ماه", current["expense"], _EXPENSE),
        ("مانده", current["balance"], _BALANCE),
    ]
    for i, (label, value, color) in enumerate(kpis):
        x = 0.17 + i * 0.33
        _annotate(ax_kpi, (x, 0.78), label, 11, _MUTED, va="center")
        _annotate(ax_kpi, (x, 0.28), money.format_amount(value), 16, color,
                 va="center")

    # --- نمودار میله‌ای ------------------------------------------------------
    ax_bar = fig.add_subplot(gs[1, 0])
    positions = list(range(len(monthly)))
    inc = [m["income"] / 1_000_000 for m in monthly]
    exp = [m["expense"] / 1_000_000 for m in monthly]
    width = 0.4
    ax_bar.bar([p - width / 2 for p in positions], inc, width=width, color=_INCOME)
    ax_bar.bar([p + width / 2 for p in positions], exp, width=width, color=_EXPENSE)
    ax_bar.set_xticks(positions)
    ax_bar.set_xticklabels([""] * len(positions))  # برچسبِ نیتیو خاموش؛ خودمان می‌کشیم
    ax_bar.grid(axis="y", alpha=0.3)

    month_axis = ax_bar.get_xaxis_transform()  # x: داده، y: کسرِ محور
    for pos, m in zip(positions, monthly):
        _annotate(ax_bar, (pos, -0.03), m["label"], 9, "black",
                 xycoords=month_axis, va="top")
    _annotate(ax_bar, (0.5, 1.05), "درآمد و هزینه (میلیون تومان)", 11, "black",
             va="bottom")

    # legend دستی — همان دو سری، بدون تکیه به legend()ِ نیتیو
    lx, ly = 0.04, 0.95
    for i, (label, color) in enumerate((("درآمد", _INCOME), ("هزینه", _EXPENSE))):
        y = ly - i * 0.09
        ax_bar.add_patch(Rectangle(
            (lx, y - 0.02), 0.05, 0.04, transform=ax_bar.transAxes,
            facecolor=color, edgecolor="none", zorder=6, clip_on=False,
        ))
        _annotate(ax_bar, (lx + 0.07, y), label, 9, "black", ha="left", zorder=6)

    # --- سهم دسته‌های هزینه --------------------------------------------------
    ax_pie = fig.add_subplot(gs[1, 1])
    cats = current["expense_by_category"]
    if cats:
        items = sorted(cats.items(), key=lambda kv: kv[1], reverse=True)[:5]
        values = [v for _, v in items]
        total = sum(values) or 1
        wedges = ax_pie.pie(
            values, colors=_PIE[: len(values)],
            wedgeprops=dict(width=0.42), startangle=90,
        )[0]
        for wedge, (name, value) in zip(wedges, items):
            mid = math.radians((wedge.theta1 + wedge.theta2) / 2)
            pct = money.to_persian_digits(str(round(value / total * 100))) + "٪"
            _annotate(ax_pie, (0.79 * math.cos(mid), 0.79 * math.sin(mid)),
                     pct, 9, "white", xycoords="data", shape=False)
            _annotate(ax_pie, (1.22 * math.cos(mid), 1.22 * math.sin(mid)),
                     name, 9, "black", xycoords="data")
        _annotate(ax_pie, (0.5, 1.05), "سهم دسته‌های هزینه (این ماه)", 11, "black",
                 va="bottom")
    else:
        ax_pie.axis("off")
        _annotate(ax_pie, (0.5, 0.5), "هزینه‌ای ثبت نشده", 11, _MUTED)

    if not has_data:
        _annotate(fig, (0.5, 0.45), "هنوز داده‌ای برای نمایش نیست", 14, _MUTED,
                 xycoords="figure fraction", zorder=20)

    fig.savefig(out_path, facecolor="white")
    plt.close(fig)
    return out_path
