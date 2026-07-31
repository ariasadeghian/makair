"""نرخ روزانه‌ی دلار و تبدیل مبالغ تومانی به دلار.

چرا مهم است: در ایران رشدِ تومانیِ درآمد لزوماً یعنی رشدِ واقعی نیست. اگر
درآمد ۳۰٪ بالا رفته باشد ولی دلار ۴۵٪، کسب‌وکار در عمل **کوچک‌تر** شده است.
این ماژول اجازه می‌دهد همان داده‌ی موجود را از پشتِ عینکِ دلار هم ببینیم.

هر تراکنش با نرخِ **روزِ خودش** تبدیل می‌شود (نه نرخِ امروز)، پس خرید در دلارِ
ارزان و فروش در دلارِ گران، خودش را در جمعِ دلاری نشان می‌دهد.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Optional

from ..core import jalali, money
from ..db.models import Rate
from ..db.store import Store

#: بازه‌ی منطقی نرخ دلار به تومان (برای فیلترکردن عددهای بی‌ربطِ پیام‌ها).
MIN_RATE = 5_000
MAX_RATE = 5_000_000

#: واژه‌هایی که نشان می‌دهند پیام درباره‌ی دلار است.
_USD_WORDS = ("دلار", "دلار آزاد", "usd", "USD", "$")

#: اگر پیام صریحاً «ریال» گفته باشد، عدد تقسیم بر ۱۰ می‌شود.
_RIAL_WORDS = ("ریال", "﷼")

_NUM_RE = re.compile(r"\d[\d,٬،\.]*")


def parse_rate_message(text: str) -> Optional[int]:
    """نرخ دلار را از یک پیام (مثلاً پستِ کانال) درمی‌آورد؛ وگرنه ``None``.

    سخت‌گیرانه است تا هر عددی را نرخ نپندارد: پیام باید به دلار اشاره کند و
    عدد باید در بازه‌ی منطقی باشد. اگر واحدِ پیام «ریال» باشد به تومان تبدیل
    می‌شود.
    """
    if not text:
        return None
    lowered = text.replace("‌", " ")
    if not any(w in lowered for w in _USD_WORDS):
        return None

    is_rial = any(w in lowered for w in _RIAL_WORDS)
    normalized = money.to_english_digits(lowered)
    for raw in _NUM_RE.findall(normalized):
        digits = re.sub(r"[^\d]", "", raw)
        if not digits:
            continue
        value = int(digits)
        if is_rial:
            value //= 10
        if MIN_RATE <= value <= MAX_RATE:
            return value
    return None


async def set_rate(
    store: Store,
    value: int,
    on_date: Optional[dt.date] = None,
    source: str = "manual",
) -> Rate:
    """نرخ یک روز را ثبت یا به‌روز می‌کند (برای هر روز فقط یک ردیف)."""
    on_date = on_date or jalali.now().date()
    existing = store.list("rates", lambda r: r.date == on_date)
    if existing:
        row = existing[0]
        row.usd = int(value)
        row.source = source
        await store.update("rates", row)
        return row
    row = Rate(date=on_date, usd=int(value), source=source)
    await store.add("rates", row)
    return row


def rate_for(store: Store, on_date: dt.date) -> Optional[int]:
    """نرخ همان روز؛ اگر نبود، آخرین نرخِ ثبت‌شده **پیش از** آن روز.

    نرخِ روزهای آینده استفاده نمی‌شود تا محاسبه‌ی گذشته با نرخِ بعدی آلوده نشود.
    """
    rows = [r for r in store.list("rates", lambda r: r.date is not None)
            if r.date <= on_date]
    if not rows:
        return None
    return int(max(rows, key=lambda r: r.date).usd)


def latest_rate(store: Store) -> Optional[Rate]:
    """جدیدترین نرخِ ثبت‌شده (برای نمایش وضعیت)."""
    rows = store.list("rates", lambda r: r.date is not None)
    return max(rows, key=lambda r: r.date) if rows else None


def to_usd(amount_toman: int, rate: Optional[int]) -> Optional[float]:
    """تبدیل مبلغ تومانی به دلار با نرخِ داده‌شده."""
    if not rate:
        return None
    return int(amount_toman) / int(rate)


def convert_period(
    store: Store, user_id: int, start: dt.datetime, end: dt.datetime
) -> dict:
    """جمعِ دلاریِ یک بازه، با تبدیلِ هر تراکنش به نرخِ **روزِ خودش**.

    خروجی: ``income_usd``، ``expense_usd``، ``balance_usd``، ``income``،
    ``expense`` (تومانی)، ``covered`` (چند تراکنش نرخ داشت) و ``missing``.
    """
    income = expense = 0
    income_usd = expense_usd = 0.0
    covered = missing = 0

    def _in_range(t) -> bool:
        return (
            t.user_id == user_id
            and t.occurred_at is not None
            and start <= t.occurred_at <= end
        )

    for t in store.list("transactions", _in_range):
        amount = int(t.amount)
        rate = rate_for(store, t.occurred_at.date())
        if rate:
            covered += 1
            usd = amount / rate
        else:
            missing += 1
            usd = 0.0
        if t.kind == "income":
            income += amount
            income_usd += usd
        else:
            expense += amount
            expense_usd += usd

    return {
        "income": income,
        "expense": expense,
        "balance": income - expense,
        "income_usd": income_usd,
        "expense_usd": expense_usd,
        "balance_usd": income_usd - expense_usd,
        "covered": covered,
        "missing": missing,
    }


def _pct_change(now: float, before: float) -> Optional[float]:
    """درصد تغییر؛ ``None`` اگر مبنای مقایسه صفر باشد."""
    if not before:
        return None
    return (now - before) / before * 100


def _fmt_usd(value: float) -> str:
    """قالب‌بندی دلار با ارقام و جداکننده‌ی فارسی (بدون اعشارِ اضافه)."""
    grouped = f"{round(value):,}".replace(",", "٬")
    return "$" + money.to_persian_digits(grouped)


def _fmt_pct(value: Optional[float]) -> str:
    if value is None:
        return "—"
    arrow = "↑" if value >= 0 else "↓"
    return f"{arrow} {money.to_persian_digits(str(abs(round(value))))}٪"


def build_usd_report(
    store: Store, user_id: int, now: Optional[dt.datetime] = None
) -> str:
    """گزارش دلاریِ این ماه + مقایسه‌ی رشدِ تومانی و دلاری با ماه قبل."""
    now = now or jalali.now()
    latest = latest_rate(store)
    if latest is None:
        return (
            "هنوز نرخ دلاری ثبت نشده است. 💵\n"
            "تا وقتی نرخ ثبت نشود نمی‌توانم درآمدت را دلاری حساب کنم."
        )

    start, end = jalali.month_bounds(now)
    cur = convert_period(store, user_id, start, end)
    if cur["income"] == 0 and cur["expense"] == 0:
        return "در این ماه هنوز تراکنشی ثبت نشده است. 📭"

    prev_base = start - dt.timedelta(days=1)
    p_start, p_end = jalali.month_bounds(prev_base)
    prev = convert_period(store, user_id, p_start, p_end)

    lines = [
        "💵 <b>نمای دلاری — این ماه</b>",
        f"نرخ روز: {money.format_amount(latest.usd)} "
        f"({jalali.format_date(latest.date)})",
        "",
        f"🟢 درآمد: {money.format_amount(cur['income'])} "
        f"≈ {_fmt_usd(cur['income_usd'])}",
        f"🔴 هزینه: {money.format_amount(cur['expense'])} "
        f"≈ {_fmt_usd(cur['expense_usd'])}",
        f"💰 مانده: {money.format_amount(cur['balance'])} "
        f"≈ {_fmt_usd(cur['balance_usd'])}",
    ]

    if prev["income"]:
        t_change = _pct_change(cur["income"], prev["income"])
        d_change = _pct_change(cur["income_usd"], prev["income_usd"])
        lines += [
            "",
            "<b>مقایسه‌ی درآمد با ماه قبل</b>",
            f"به تومان: {_fmt_pct(t_change)}",
            f"به دلار: {_fmt_pct(d_change)}",
        ]
        # همان جمله‌ای که واقعیت را می‌گوید
        if t_change is not None and d_change is not None:
            if t_change > 0 and d_change < 0:
                lines.append(
                    "\n⚠️ درآمدت تومانی بالا رفته ولی دلاری کم شده — "
                    "رشدِ اسمی است، نه واقعی."
                )
            elif d_change > 0:
                lines.append("\n✅ رشدت واقعی است؛ دلاری هم جلو رفته‌ای.")

    if cur["missing"]:
        lines.append(
            f"\n<i>برای {money.to_persian_digits(str(cur['missing']))} تراکنش "
            "نرخ روزِ آن روز موجود نبود و در محاسبه نیامد.</i>"
        )
    return "\n".join(lines)
