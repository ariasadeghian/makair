"""سنجه‌های پایلوت: قیف فعال‌سازی، ماندگاری، و استفاده‌ی واقعی از قابلیت‌ها.

همه‌چیز از روی داده‌ی موجود در :class:`Store` محاسبه می‌شود (بدون رویداد/لاگِ
جدا): زمانِ ساختِ کاربر و زمانِ تراکنش‌ها. هدف این است که «حدود» محصول را به‌جای
حدس‌زدن، در میدان اندازه بگیریم (نگاه کنید به ``docs/PILOT.md`` و
``docs/PRODUCT_SCOPE.md``).
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from statistics import median
from typing import Optional

from ..core import industries, jalali, money
from ..db.store import Store

_EPOCH = dt.datetime(1970, 1, 1, tzinfo=jalali.TEHRAN)

#: آستانه‌ی «فعال‌سازیِ سریع» (ثانیه) — از /start تا اولین ثبت.
FAST_ACTIVATION_SECONDS = 120
#: حداقل تعداد ثبت در هفته‌ی دوم برای «کاربرِ چسبنده».
WEEK2_ACTIVE_MIN = 5


def _ts(value: Optional[dt.datetime]) -> dt.datetime:
    return value or _EPOCH


def compute_pilot_metrics(store: Store, now: dt.datetime) -> dict:
    """قیف و سنجه‌های پایلوت را از داده‌ی فعلی محاسبه می‌کند."""
    users = store.list("users", lambda u: True)
    txs = store.list("transactions", lambda t: True)

    tx_by_user: dict[int, list] = defaultdict(list)
    for t in txs:
        tx_by_user[t.user_id].append(t)
    for lst in tx_by_user.values():
        lst.sort(key=lambda t: _ts(t.created_at))

    horizon_7 = now - dt.timedelta(days=7)
    today_start, today_end = jalali.day_bounds(now)
    activated = fast_activation = active_last_7 = active_today = 0
    activation_secs: list[float] = []
    d7_eligible = d7_returned = 0
    w2_eligible = w2_active = 0

    for u in users:
        u_txs = tx_by_user.get(u.id, [])
        if u_txs:
            activated += 1
            first = u_txs[0].created_at
            if u.created_at and first:
                secs = (first - u.created_at).total_seconds()
                if secs >= 0:
                    activation_secs.append(secs)
                    if secs <= FAST_ACTIVATION_SECONDS:
                        fast_activation += 1
            last_tx_at = u_txs[-1].created_at
            if last_tx_at and last_tx_at >= horizon_7:
                active_last_7 += 1
            if last_tx_at and today_start <= last_tx_at <= today_end:
                active_today += 1

        if u.created_at and (now - u.created_at) >= dt.timedelta(days=7):
            d7_eligible += 1
            cutoff = u.created_at + dt.timedelta(days=6)
            if any(t.created_at and t.created_at >= cutoff for t in u_txs):
                d7_returned += 1

        if u.created_at and (now - u.created_at) >= dt.timedelta(days=14):
            w2_eligible += 1
            lo = u.created_at + dt.timedelta(days=7)
            hi = u.created_at + dt.timedelta(days=14)
            count = sum(1 for t in u_txs if t.created_at and lo <= t.created_at < hi)
            if count >= WEEK2_ACTIVE_MIN:
                w2_active += 1

    # توزیعِ صنف: کدام نیچ جذب می‌شود و کدام نه.
    by_industry: dict[str, int] = defaultdict(int)
    for u in users:
        by_industry[getattr(u, "business_type", "") or ""] += 1

    # قیفِ آنبردینگ: شروع → اولین تراکنش (activated) → اولین فاکتور → اولین مخاطب.
    onboarding_started = sum(1 for u in users if getattr(u, "onboarding_started_at", None))
    first_invoice_activated = sum(1 for u in users if getattr(u, "first_invoice_at", None))
    first_contact_activated = sum(1 for u in users if getattr(u, "first_contact_at", None))

    return {
        "total_users": len(users),
        "onboarding_started": onboarding_started,
        "activated": activated,
        "first_invoice_activated": first_invoice_activated,
        "first_contact_activated": first_contact_activated,
        "by_industry": dict(by_industry),
        "fast_activation": fast_activation,
        "median_activation_secs": median(activation_secs) if activation_secs else None,
        "active_today": active_today,
        "active_last_7": active_last_7,
        "d7_eligible": d7_eligible,
        "d7_returned": d7_returned,
        "w2_eligible": w2_eligible,
        "w2_active": w2_active,
        "usage": {
            "transactions": len(txs),
            "invoices": len(store.list("invoices", lambda x: True)),
            "ledger": len(store.list("ledger_entries", lambda x: True)),
            "cheques": len(store.list("ledger_entries", lambda x: x.is_cheque)),
            "products": len(store.list("products", lambda x: True)),
            "group_events": len(store.list("group_events", lambda x: True)),
        },
    }


def _pct(part: int, whole: int) -> str:
    if whole <= 0:
        return "—"
    return money.to_persian_digits(str(round(100 * part / whole))) + "٪"


def _fmt_duration(secs: Optional[float]) -> str:
    if secs is None:
        return "—"
    secs = int(secs)
    fa = money.to_persian_digits
    if secs < 60:
        return f"{fa(str(secs))} ثانیه"
    minutes = secs // 60
    if minutes < 60:
        return f"{fa(str(minutes))} دقیقه"
    hours = minutes // 60
    if hours < 24:
        return f"{fa(str(hours))} ساعت و {fa(str(minutes % 60))} دقیقه"
    return f"{fa(str(hours // 24))} روز"


def _fa(n: int) -> str:
    return money.to_persian_digits(str(n))


def build_pilot_report(metrics: dict) -> str:
    """گزارش متنیِ سنجه‌های پایلوت برای ادمین."""
    m = metrics
    u = m["usage"]
    lines = [
        "🧪 <b>داشبورد پایلوت</b>",
        "",
        f"👤 کاربران: {_fa(m['total_users'])}",
        f"✅ فعال‌شده (≥۱ ثبت): {_fa(m['activated'])} "
        f"({_pct(m['activated'], m['total_users'])})",
        "",
        "🚦 <b>قیفِ آنبردینگ</b>",
        f"۱. شروع کردند: {_fa(m['total_users'])}",
        f"۲. آنبردینگ را دیدند: {_fa(m.get('onboarding_started', 0))} "
        f"({_pct(m.get('onboarding_started', 0), m['total_users'])})",
        f"۳. اولین ثبت: {_fa(m['activated'])} "
        f"({_pct(m['activated'], m['total_users'])})",
        f"۴. اولین فاکتور: {_fa(m.get('first_invoice_activated', 0))} "
        f"({_pct(m.get('first_invoice_activated', 0), m['total_users'])})",
        f"۵. اولین مخاطب: {_fa(m.get('first_contact_activated', 0))} "
        f"({_pct(m.get('first_contact_activated', 0), m['total_users'])})",
        "",
        "🎯 <b>سه سنجه‌ی کلیدی</b>",
        f"۱) فعال‌سازیِ سریع (زیر ۲ دقیقه): {_fa(m['fast_activation'])} "
        f"از {_fa(m['activated'])} — میانه: {_fmt_duration(m['median_activation_secs'])}",
        f"۲) بازگشتِ روز ۷: {_fa(m['d7_returned'])} از {_fa(m['d7_eligible'])} "
        f"({_pct(m['d7_returned'], m['d7_eligible'])})",
        f"۳) فعالِ هفته‌ی دوم (≥۵ ثبت): {_fa(m['w2_active'])} از {_fa(m['w2_eligible'])} "
        f"({_pct(m['w2_active'], m['w2_eligible'])})",
        "",
        f"📅 فعال امروز (DAU): {_fa(m.get('active_today', 0))}",
        f"🔥 فعال در ۷ روز اخیر: {_fa(m['active_last_7'])}",
        "",
        "📊 <b>استفاده از قابلیت‌ها</b> (چه چیزی واقعاً کار می‌کند)",
        f"• تراکنش: {_fa(u['transactions'])}",
        f"• فاکتور: {_fa(u['invoices'])}",
        f"• طلب/بدهی: {_fa(u['ledger'])} (از این تعداد چک: {_fa(u['cheques'])})",
        f"• کالای ذخیره‌شده: {_fa(u['products'])}",
        f"• رویداد گروهی: {_fa(u['group_events'])}",
    ]

    by_ind = m.get("by_industry") or {}
    if by_ind:
        lines.append("")
        lines.append("🏷 <b>صنفِ کاربران</b> (کدام نیچ جذب می‌شود)")
        for key, count in sorted(by_ind.items(), key=lambda kv: -kv[1]):
            lines.append(f"• {industries.label_for(key)}: {_fa(count)}")

    lines.append("")
    lines.append(
        "<i>قانون: قابلیتی که هیچ‌کس استفاده نکرد، از منوی اصلی پنهان می‌شود.</i>"
    )
    return "\n".join(lines)
