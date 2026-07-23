"""داشبورد تصویری وضعیت مالی کسب‌وکار.

یک تصویر PNG می‌سازد شامل: شاخص‌های کلیدی (درآمد/هزینه/مانده‌ی ماه جاری)،
نمودار میله‌ای درآمد و هزینه‌ی چند ماه اخیر، و نمودار سهم دسته‌های هزینه.
متن فارسی با :mod:`arabic_reshaper` و :mod:`bidi` شکل داده می‌شود.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
from typing import Optional

import arabic_reshaper
import jdatetime
import matplotlib

matplotlib.use("Agg")  # بدون نیاز به نمایشگر

import matplotlib.pyplot as plt  # noqa: E402
from bidi.algorithm import get_display  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from ..core import jalali, money  # noqa: E402
from . import transactions as tx_service  # noqa: E402

_FONT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "pdf", "fonts", "Vazirmatn-Regular.ttf"
)
_FONT_READY = False

# پالت رنگ
_INCOME = "#2e9e5b"
_EXPENSE = "#e0533d"
_BALANCE = "#2f6fb0"
_MUTED = "#8a8a8a"
_PIE = ["#e0533d", "#e8a33d", "#c65b9c", "#2f6fb0", "#6a7f8c"]


def _ensure_font() -> None:
    global _FONT_READY
    if _FONT_READY:
        return
    if os.path.isfile(_FONT_PATH):
        font_manager.fontManager.addfont(_FONT_PATH)
        plt.rcParams["font.family"] = font_manager.FontProperties(
            fname=_FONT_PATH
        ).get_name()
    plt.rcParams["axes.unicode_minus"] = False
    # وزیرمتن تک‌وزنه است؛ هشدارهای بی‌ضررِ یافتن وزن فونت را ساکت می‌کنیم.
    logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
    _FONT_READY = True


def _fa(text) -> str:
    """شکل‌دهی متن فارسی برای نمایش صحیح در نمودار."""
    return get_display(arabic_reshaper.reshape(str(text)))


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


def _gather(session: Session, user_id: int, now: dt.datetime, months: int):
    monthly = []
    for back in range(months - 1, -1, -1):
        start, end, label = _month_window(now, back)
        s = tx_service.summary(session, user_id, start, end)
        monthly.append(
            {"label": label, "income": s["income"], "expense": s["expense"]}
        )
    c_start, c_end = jalali.month_bounds(now)
    current = tx_service.summary(session, user_id, c_start, c_end)
    return monthly, current


def render_dashboard_png(
    session: Session,
    user_id: int,
    out_path: str,
    now: Optional[dt.datetime] = None,
    business=None,
    months: int = 6,
) -> str:
    """داشبورد مالی کاربر را در یک فایل PNG می‌سازد و مسیرش را برمی‌گرداند."""
    _ensure_font()
    now = now or jalali.now()
    monthly, current = _gather(session, user_id, now, months)
    has_data = any(m["income"] or m["expense"] for m in monthly)

    fig = plt.figure(figsize=(10, 7.2), dpi=110)
    fig.patch.set_facecolor("white")

    title = getattr(business, "business_name", None) or "کسب‌وکار من"
    fig.suptitle(_fa(f"داشبورد مالی — {title}"), fontsize=17, y=0.97)
    fig.text(
        0.5, 0.915, _fa(f"تا {jalali.format_date(now)}"),
        ha="center", fontsize=10, color=_MUTED,
    )

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
        ax_kpi.text(x, 0.78, _fa(label), ha="center", va="center", fontsize=11,
                    color=_MUTED, transform=ax_kpi.transAxes)
        ax_kpi.text(x, 0.28, _fa(money.format_amount(value)), ha="center",
                    va="center", fontsize=16, color=color,
                    transform=ax_kpi.transAxes)

    # --- نمودار میله‌ای ------------------------------------------------------
    ax_bar = fig.add_subplot(gs[1, 0])
    positions = list(range(len(monthly)))
    inc = [m["income"] / 1_000_000 for m in monthly]
    exp = [m["expense"] / 1_000_000 for m in monthly]
    width = 0.4
    ax_bar.bar([p - width / 2 for p in positions], inc, width=width,
               label=_fa("درآمد"), color=_INCOME)
    ax_bar.bar([p + width / 2 for p in positions], exp, width=width,
               label=_fa("هزینه"), color=_EXPENSE)
    ax_bar.set_xticks(positions)
    ax_bar.set_xticklabels([_fa(m["label"]) for m in monthly], fontsize=9)
    ax_bar.set_title(_fa("درآمد و هزینه (میلیون تومان)"), fontsize=11)
    ax_bar.legend(loc="upper left", fontsize=9)
    ax_bar.grid(axis="y", alpha=0.3)

    # --- سهم دسته‌های هزینه --------------------------------------------------
    ax_pie = fig.add_subplot(gs[1, 1])
    cats = current["expense_by_category"]
    if cats:
        items = sorted(cats.items(), key=lambda kv: kv[1], reverse=True)[:5]
        values = [v for _, v in items]
        labels = [_fa(k) for k, _ in items]
        ax_pie.pie(
            values, labels=labels,
            autopct=lambda p: f"{money.to_persian_digits(str(round(p)))}٪",
            colors=_PIE[: len(values)],
            textprops={"fontsize": 9}, wedgeprops=dict(width=0.42),
            startangle=90,
        )
        ax_pie.set_title(_fa("سهم دسته‌های هزینه (این ماه)"), fontsize=11)
    else:
        ax_pie.axis("off")
        ax_pie.text(0.5, 0.5, _fa("هزینه‌ای ثبت نشده"), ha="center",
                    va="center", color=_MUTED, fontsize=11)

    if not has_data:
        fig.text(0.5, 0.45, _fa("هنوز داده‌ای برای نمایش نیست"),
                 ha="center", fontsize=14, color=_MUTED)

    fig.savefig(out_path, facecolor="white")
    plt.close(fig)
    return out_path
