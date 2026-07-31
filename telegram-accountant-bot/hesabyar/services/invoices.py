"""سرویس صدور و مدیریت فاکتور فروش (روی :class:`Store`).

همه‌ی مبالغ عدد صحیح و به «تومان»؛ ``issue_date`` یک :class:`datetime.date`
است و شماره‌ی فاکتور با ارقام فارسی و بر پایه‌ی سال شمسی ساخته می‌شود.
"""
from __future__ import annotations

import datetime as dt
import secrets
from typing import Optional, Sequence, TypedDict

from ..core import jalali, money
from ..db.models import Invoice, InvoiceItem
from ..db.store import Store
from .transactions import get_or_create_user


class InvoiceItemInput(TypedDict):
    title: str
    quantity: int
    unit_price: int


def _items_for(store: Store, invoice_id: int) -> list[InvoiceItem]:
    rows = store.list("invoice_items", lambda it: it.invoice_id == invoice_id)
    return sorted(rows, key=lambda it: it.id)


def next_invoice_number(
    store: Store, user_id: int, base: dt.datetime
) -> tuple[str, int]:
    """شماره‌ی فاکتور بعدی: «{سال شمسی}-{seq:04d}» با ارقام فارسی."""
    seqs = [inv.seq for inv in store.list("invoices", lambda i: i.user_id == user_id)]
    seq = (max(seqs) + 1) if seqs else 1
    year = jalali.to_jalali(base).year
    display = money.to_persian_digits(f"{year}-{seq:04d}")
    return display, seq


async def create_invoice(
    store: Store,
    user_id: int,
    *,
    customer_name: str,
    items: Sequence[InvoiceItemInput],
    issue_date: dt.date,
    customer_phone: str = "",
    customer_address: str = "",
    note: str = "",
    discount: int = 0,
    shipping: int = 0,
    base: dt.datetime | None = None,
) -> Invoice:
    if base is None:
        base = jalali.now()
    await get_or_create_user(store, user_id)
    number, seq = next_invoice_number(store, user_id, base)
    invoice = Invoice(
        user_id=user_id, number=number, seq=seq, customer_name=customer_name,
        customer_phone=customer_phone, customer_address=customer_address,
        issue_date=issue_date, note=note,
        discount=int(discount or 0), shipping=int(shipping or 0),
        share_token=new_share_token(),
    )
    await store.add("invoices", invoice)
    for item in items:
        row = InvoiceItem(
            invoice_id=invoice.id, title=item["title"],
            quantity=int(item["quantity"]), unit_price=int(item["unit_price"]),
        )
        await store.add("invoice_items", row)
        invoice.items.append(row)
    return invoice


def get_invoice(store: Store, invoice_id: int, user_id: int) -> Optional[Invoice]:
    invoice = store.get("invoices", invoice_id)
    if invoice is None or invoice.user_id != user_id:
        return None
    invoice.items = _items_for(store, invoice.id)
    return invoice


def list_invoices(store: Store, user_id: int, limit: int = 10) -> list[Invoice]:
    rows = sorted(
        store.list("invoices", lambda i: i.user_id == user_id),
        key=lambda i: i.seq, reverse=True,
    )[:limit]
    for invoice in rows:
        invoice.items = _items_for(store, invoice.id)
    return rows


# --- اشتراک‌گذاری با مشتری ------------------------------------------------------


def new_share_token() -> str:
    """توکن تصادفیِ لینک فاکتور.

    تصادفی است تا کسی نتواند با شماره‌گذاریِ پشت‌سرهم فاکتورهای بقیه را ببیند.
    فقط حروف/رقم است تا در deep-link تلگرام معتبر بماند.
    """
    return secrets.token_hex(8)


def get_by_token(store: Store, token: str) -> Optional[Invoice]:
    """فاکتور را با توکنِ لینک پیدا می‌کند (بدون نیاز به مالکیت)."""
    if not token:
        return None
    rows = store.list("invoices", lambda i: i.share_token == token)
    if not rows:
        return None
    invoice = rows[0]
    invoice.items = _items_for(store, invoice.id)
    return invoice


def share_link(bot_username: str, invoice: Invoice) -> str:
    """لینکِ باز کردن فاکتور در تلگرام برای مشتری."""
    if not bot_username or not invoice.share_token:
        return ""
    return f"https://t.me/{bot_username}?start=fac_{invoice.share_token}"


async def attach_customer(store: Store, invoice: Invoice, tg_id: int) -> None:
    """آیدی تلگرامِ مشتری را روی فاکتور ثبت می‌کند (اولین بازکننده‌ی لینک)."""
    if invoice.customer_tg_id == tg_id:
        return
    invoice.customer_tg_id = tg_id
    await store.update("invoices", invoice)


async def set_rating(store: Store, invoice: Invoice, stars: int) -> Invoice:
    """امتیاز مشتری به این خرید (۱ تا ۵)."""
    invoice.rating = max(1, min(5, int(stars)))
    await store.update("invoices", invoice)
    return invoice


def rating_summary(store: Store, user_id: int) -> Optional[dict]:
    """میانگین و تعداد امتیازهای یک کسب‌وکار؛ ``None`` اگر امتیازی نباشد."""
    rated = store.list(
        "invoices", lambda i: i.user_id == user_id and int(i.rating or 0) > 0
    )
    if not rated:
        return None
    total = sum(int(i.rating) for i in rated)
    return {"count": len(rated), "average": total / len(rated)}
