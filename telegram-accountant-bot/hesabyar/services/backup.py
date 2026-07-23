"""پشتیبان‌گیری داده‌ها.

دو قابلیت:

* :func:`export_full_user_xlsx` — یک فایل اکسل چندشیتی با همه‌ی داده‌های یک
  کاربر (تراکنش‌ها، طلب و بدهی، فاکتورها) برای پشتیبان شخصی.
* :func:`backup_sqlite` — تهیه‌ی نسخه‌ی پشتیبانِ فایل دیتابیس SQLite برای
  عملیات/مدیر.
"""
from __future__ import annotations

import datetime as dt
import os
import shutil
from typing import Optional

from openpyxl import Workbook
from openpyxl.styles import Font
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core import jalali
from ..db.models import Direction, Invoice, Kind, LedgerEntry, Transaction

_HEADER_FONT = Font(bold=True)


def _write_header(ws, headers: list[str]) -> None:
    ws.sheet_view.rightToLeft = True
    ws.append(headers)
    for cell in ws[ws.max_row]:
        cell.font = _HEADER_FONT


def export_full_user_xlsx(
    session: Session, user_id: int, out_path: str, business=None
) -> str:
    """کل داده‌های کاربر را در یک فایل اکسل چندشیتی می‌نویسد و مسیرش را برمی‌گرداند."""
    wb = Workbook()

    # --- شیت تراکنش‌ها -------------------------------------------------------
    ws = wb.active
    ws.title = "تراکنش‌ها"
    _write_header(ws, ["ردیف", "تاریخ", "نوع", "دسته", "شرح", "مبلغ (تومان)"])
    txs = list(
        session.execute(
            select(Transaction)
            .where(Transaction.user_id == user_id)
            .order_by(Transaction.occurred_at.asc(), Transaction.id.asc())
        ).scalars()
    )
    for index, tx in enumerate(txs, start=1):
        kind_label = "درآمد" if tx.kind == Kind.INCOME else "هزینه"
        ws.append(
            [
                index,
                jalali.format_date(tx.occurred_at),
                kind_label,
                tx.category,
                tx.description,
                int(tx.amount),
            ]
        )

    # --- شیت طلب و بدهی ------------------------------------------------------
    ws2 = wb.create_sheet("طلب و بدهی")
    _write_header(ws2, ["ردیف", "نوع", "طرف‌حساب", "مبلغ (تومان)", "سررسید", "وضعیت"])
    entries = list(
        session.execute(
            select(LedgerEntry)
            .where(LedgerEntry.user_id == user_id)
            .order_by(LedgerEntry.id.asc())
        ).scalars()
    )
    for index, entry in enumerate(entries, start=1):
        direction = "طلب" if entry.direction == Direction.RECEIVABLE else "بدهی"
        due = jalali.format_date(entry.due_date) if entry.due_date else "—"
        state = "تسویه‌شده" if entry.is_settled else "باز"
        ws2.append(
            [index, direction, entry.party_name, int(entry.amount), due, state]
        )

    # --- شیت فاکتورها -------------------------------------------------------
    ws3 = wb.create_sheet("فاکتورها")
    _write_header(ws3, ["شماره", "تاریخ", "مشتری", "جمع کل (تومان)"])
    invoices = list(
        session.execute(
            select(Invoice)
            .where(Invoice.user_id == user_id)
            .order_by(Invoice.seq.asc())
        ).scalars()
    )
    for inv in invoices:
        ws3.append(
            [
                inv.number,
                jalali.format_date(inv.issue_date),
                inv.customer_name,
                int(inv.total),
            ]
        )

    for sheet in (ws, ws2, ws3):
        for column_cells in sheet.columns:
            length = max((len(str(c.value)) for c in column_cells if c.value), default=8)
            sheet.column_dimensions[column_cells[0].column_letter].width = min(
                max(length + 2, 10), 40
            )

    wb.save(out_path)
    return out_path


def backup_sqlite(
    database_url: str,
    dest_dir: Optional[str] = None,
    stamp: Optional[str] = None,
) -> Optional[str]:
    """از فایل دیتابیس SQLite یک نسخه‌ی پشتیبان می‌گیرد.

    فقط برای دیتابیس فایلی SQLite کار می‌کند؛ برای دیتابیس در حافظه یا
    موتورهای دیگر ``None`` برمی‌گرداند. مسیر فایل پشتیبان را برمی‌گرداند.
    """
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return None
    src = database_url[len(prefix):]
    if src in ("", ":memory:") or not os.path.isfile(src):
        return None
    if stamp is None:
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    if dest_dir is None:
        dest_dir = os.path.join(os.path.dirname(src) or ".", "backups")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, f"{os.path.basename(src)}.{stamp}.bak")
    shutil.copy2(src, dest)
    return dest
