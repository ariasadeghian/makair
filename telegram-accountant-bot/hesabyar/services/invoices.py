"""سرویس صدور و مدیریت فاکتور فروش (روی :class:`Store`).

همه‌ی مبالغ عدد صحیح و به «تومان»؛ ``issue_date`` یک :class:`datetime.date`
است و شماره‌ی فاکتور با ارقام فارسی و بر پایه‌ی سال شمسی ساخته می‌شود.
"""
from __future__ import annotations

import datetime as dt
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
