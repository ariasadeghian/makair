"""طرف‌حساب‌ها (مشتری/تأمین‌کننده): یک‌بار ذخیره، بارها استفاده.

پیش از این، نام مشتری فقط یک رشته روی فاکتور و ردیف دفتر بود؛ هر بار دوباره
تایپ می‌شد و «رضا محمدی» در دو فاکتور، دو چیزِ بی‌ربط بودند. حالا یک رکورد
:class:`Customer` ساخته می‌شود و فاکتور/دفتر با ``customer_id`` به آن لینک
می‌شوند. فیلدهای متنیِ قدیمی (``customer_name``/``party_name``) برای نمایش و
سازگاری با داده‌های قبلی پر می‌مانند.

تطبیقِ نام عمداً **دقیق** است (بدون حساسیت به فاصله/بزرگی حروف). تطبیقِ تقریبیِ
:mod:`hesabyar.core.fuzzy` روی دسته‌ها و کالاها اجرا می‌شود ولی اینجا نه —
یکی‌کردنِ «رضا» و «رضایی» دو آدمِ واقعی و دو حسابِ جدا را در هم می‌کند، و
اشتباهش خیلی گران‌تر از یک کالای تکراری است.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from ..core import jalali
from ..db.models import Customer
from ..db.store import Store

_EPOCH = dt.datetime(1970, 1, 1, tzinfo=jalali.TEHRAN)


def normalize_name(name: str) -> str:
    """نامِ نرمال‌شده برای تطبیق: بدون فاصله‌ی اضافه، ZWNJ و بزرگی/کوچکی."""
    return " ".join((name or "").replace("‌", " ").split()).casefold()


def find_customer(store: Store, user_id: int, name: str) -> Optional[Customer]:
    """مشتری را با نامِ نرمال‌شده پیدا می‌کند؛ ``None`` اگر نبود."""
    target = normalize_name(name)
    if not target:
        return None
    for c in store.list("customers", lambda c: c.user_id == user_id):
        if normalize_name(c.name) == target:
            return c
    return None


def get_customer(store: Store, user_id: int, customer_id: int) -> Optional[Customer]:
    """مشتری را با شناسه می‌گیرد (فقط اگر متعلق به همین کاربر باشد)."""
    customer = store.get("customers", customer_id)
    if customer is None or customer.user_id != user_id:
        return None
    return customer


async def find_or_create_customer(
    store: Store,
    user_id: int,
    name: str,
    phone: str = "",
    address: str = "",
) -> Optional[Customer]:
    """مشتری را پیدا یا می‌سازد؛ ``None`` اگر نام خالی باشد.

    اگر مشتری از قبل بود و اطلاعات تازه‌ای (تلفن/نشانی) دادیم که قبلاً نداشت،
    همان رکورد تکمیل می‌شود — نه رکورد تکراری.
    """
    clean = " ".join((name or "").split())
    if not clean:
        return None

    existing = find_customer(store, user_id, clean)
    if existing is not None:
        changed = False
        if phone and not existing.phone:
            existing.phone, changed = phone[:50], True
        if address and not existing.address:
            existing.address, changed = address[:300], True
        if changed:
            await store.update("customers", existing)
        return existing

    customer = Customer(
        user_id=user_id, name=clean[:200],
        phone=phone[:50], address=address[:300],
    )
    await store.add("customers", customer)
    return customer


def list_customers(store: Store, user_id: int) -> list[Customer]:
    """همه‌ی مشتریان یک کاربر (بر اساس نام)."""
    rows = store.list("customers", lambda c: c.user_id == user_id)
    return sorted(rows, key=lambda c: normalize_name(c.name))


def last_used_at(store: Store, customer: Customer) -> dt.datetime:
    """آخرین باری که این مشتری در فاکتور یا دفتر استفاده شده است."""
    stamps = [customer.created_at or _EPOCH]
    for inv in store.list("invoices", lambda i: i.customer_id == customer.id):
        stamps.append(inv.created_at or _EPOCH)
    for e in store.list("ledger_entries", lambda e: e.customer_id == customer.id):
        stamps.append(e.created_at or _EPOCH)
    return max(stamps)


def recent_customers(store: Store, user_id: int, limit: int = 5) -> list[Customer]:
    """مشتریانِ اخیر بر اساس آخرین استفاده در فاکتور یا دفتر (جدیدترین اول)."""
    rows = store.list("customers", lambda c: c.user_id == user_id)
    return sorted(rows, key=lambda c: last_used_at(store, c), reverse=True)[:limit]


def customer_totals(store: Store, user_id: int, customer_id: int) -> dict:
    """جمعِ فاکتورها و دفترِ یک مشتری.

    خروجی: ``invoices`` (فهرست)، ``invoiced`` (جمع مبلغ فاکتورها)،
    ``entries`` (ردیف‌های بازِ دفتر)، ``receivable``/``payable``/``net``.
    """
    from ..db.models import Direction

    invoices = sorted(
        store.list(
            "invoices",
            # فاکتورِ باطل‌شده پولی نیست که کسی بدهکار باشد
            lambda i: (i.user_id == user_id and i.customer_id == customer_id
                       and not i.is_void),
        ),
        key=lambda i: i.seq,
    )
    for inv in invoices:  # اقلام لازم است تا total محاسبه شود
        inv.items = store.list(
            "invoice_items", lambda it, _id=inv.id: it.invoice_id == _id
        )

    entries = store.list(
        "ledger_entries",
        lambda e: e.user_id == user_id
        and e.customer_id == customer_id
        and not e.is_settled,
    )
    receivable = sum(
        int(e.amount) for e in entries if e.direction == Direction.RECEIVABLE
    )
    payable = sum(int(e.amount) for e in entries if e.direction == Direction.PAYABLE)
    return {
        "invoices": invoices,
        "invoiced": sum(int(i.total) for i in invoices),
        "entries": entries,
        "receivable": receivable,
        "payable": payable,
        "net": receivable - payable,
    }
