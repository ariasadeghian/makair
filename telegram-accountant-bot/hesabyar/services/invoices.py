"""سرویس صدور و مدیریت فاکتور فروش.

این ماژول منطق تجاری ساخت فاکتور (:class:`~hesabyar.db.models.Invoice`) و
اقلام آن (:class:`~hesabyar.db.models.InvoiceItem`) را فراهم می‌کند.

قواعد مشترک پروژه:

* همه‌ی مبالغ عدد صحیح و به «تومان» هستند.
* زمان‌ها aware و در منطقه‌ی تهران‌اند (``jalali.now()`` / ``jalali.TEHRAN``).
* ``issue_date`` یک :class:`datetime.date` (بدون زمان) است.
* شماره‌ی نمایشی فاکتور با ارقام فارسی و بر پایه‌ی سال شمسی ساخته می‌شود.
"""
from __future__ import annotations

import datetime as dt
from typing import Sequence, TypedDict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core import jalali, money
from ..db.models import Invoice, InvoiceItem
from .transactions import get_or_create_user


class InvoiceItemInput(TypedDict):
    """ساختار یک قلم ورودی برای ساخت فاکتور.

    ``title`` شرح کالا/خدمت، ``quantity`` تعداد (عدد صحیح) و ``unit_price``
    قیمت واحد به تومان (عدد صحیح) است.
    """

    title: str
    quantity: int
    unit_price: int


def next_invoice_number(
    session: Session, user_id: int, base: dt.datetime
) -> tuple[str, int]:
    """شماره‌ی فاکتور بعدی کاربر را می‌سازد.

    ``seq`` برابر «بیشترین ``seq`` ثبت‌شده‌ی کاربر + ۱» است و از ۱ شروع
    می‌شود. رشته‌ی نمایشی به شکل «{سال شمسیِ ``base``}-{seq با چهار رقم}»
    و کاملاً با ارقام فارسی برگردانده می‌شود، مثلاً «۱۴۰۳-۰۰۰۱».
    خروجی یک دوتایی ``(display, seq)`` است.
    """
    max_seq = session.execute(
        select(func.max(Invoice.seq)).where(Invoice.user_id == user_id)
    ).scalar_one()
    seq = int(max_seq or 0) + 1
    year = jalali.to_jalali(base).year
    display = money.to_persian_digits(f"{year}-{seq:04d}")
    return display, seq


def create_invoice(
    session: Session,
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
    """یک فاکتور تازه با اقلامش می‌سازد و ذخیره می‌کند.

    ``customer_name`` نام مشتری، ``items`` فهرستی از دیکشنری‌ها با کلیدهای
    ``title``/``quantity``/``unit_price`` و ``issue_date`` تاریخ صدور
    (:class:`datetime.date`) است. اگر ``base`` داده نشود، از ``jalali.now()``
    برای تعیین سال شمسیِ شماره استفاده می‌شود. شماره‌ی یکتای فاکتور با
    :func:`next_invoice_number` گرفته می‌شود. شیء :class:`Invoice` ذخیره‌شده
    برگردانده می‌شود.
    """
    if base is None:
        base = jalali.now()

    # اطمینان از وجود کاربر برای رعایت کلید خارجی.
    get_or_create_user(session, user_id)

    number, seq = next_invoice_number(session, user_id, base)
    invoice = Invoice(
        user_id=user_id,
        number=number,
        seq=seq,
        customer_name=customer_name,
        customer_phone=customer_phone,
        customer_address=customer_address,
        issue_date=issue_date,
        note=note,
        discount=int(discount or 0),
        shipping=int(shipping or 0),
    )
    for item in items:
        invoice.items.append(
            InvoiceItem(
                title=item["title"],
                quantity=int(item["quantity"]),
                unit_price=int(item["unit_price"]),
            )
        )
    session.add(invoice)
    session.commit()
    return invoice


def get_invoice(
    session: Session, invoice_id: int, user_id: int
) -> Invoice | None:
    """یک فاکتور را با شناسه برمی‌گرداند، فقط اگر متعلق به همین کاربر باشد.

    اگر فاکتور موجود نبود یا کاربرِ مالکش نبود، ``None`` برگردانده می‌شود.
    """
    invoice = session.get(Invoice, invoice_id)
    if invoice is None or invoice.user_id != user_id:
        return None
    return invoice


def list_invoices(
    session: Session, user_id: int, limit: int = 10
) -> list[Invoice]:
    """فهرست آخرین فاکتورهای کاربر، مرتب نزولی بر اساس ``seq``.

    ``limit`` بیشترین تعداد فاکتور برگشتی است (پیش‌فرض ۱۰).
    """
    stmt = (
        select(Invoice)
        .where(Invoice.user_id == user_id)
        .order_by(Invoice.seq.desc())
        .limit(limit)
    )
    return list(session.execute(stmt).scalars().all())
