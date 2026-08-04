"""اتصال خام به Google Sheets و عملیات پایه (با تلاش مجدد).

توابع این ماژول همگی همگام (sync)‌اند؛ لایه‌ی :class:`~hesabyar.db.store.Store`
آن‌ها را با ``asyncio.to_thread`` صدا می‌زند تا حلقه‌ی async بلاک نشود.
"""
from __future__ import annotations

import functools
import json
import logging
import time
from typing import Callable, Optional, Sequence

import gspread
from google.oauth2.service_account import Credentials

from .models import ALL_MODELS

logger = logging.getLogger(__name__)

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_RETRY_STATUS = {429, 500, 502, 503}


def get_gspread_client(settings) -> gspread.Client:
    """کلاینت gspread را از روی رشته‌ی JSON کلید سرویس‌اکانت می‌سازد."""
    info = json.loads(settings.google_service_account_json)
    creds = Credentials.from_service_account_info(info, scopes=_SCOPES)
    return gspread.authorize(creds)


def open_spreadsheet(client: gspread.Client, sheet_id: str):
    return client.open_by_key(sheet_id)


def with_retry(fn: Callable) -> Callable:
    """در برابر خطاهای موقتی گوگل (429/5xx) با backoff نمایی تلاش می‌کند."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        delay = 1.0
        last_exc = None
        for attempt in range(5):
            try:
                return fn(*args, **kwargs)
            except gspread.exceptions.APIError as exc:
                last_exc = exc
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status in _RETRY_STATUS and attempt < 4:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise
        if last_exc:
            raise last_exc

    return wrapper


@with_retry
def create_user_spreadsheet(
    client: gspread.Client, title: str, folder_id: Optional[str] = None
) -> str:
    """یک اسپردشیت تازه برای یک کاربر می‌سازد و شناسه‌اش را برمی‌گرداند.

    اگر ``folder_id`` بدهیم، فایل داخل همان پوشه‌ی Drive ساخته می‌شود. این
    حالت توصیه‌شده است: سرویس‌اکانت به‌تنهایی کوتای Drive ندارد، پس باید در
    پوشه‌ای بسازد که مالکش یک اکانت واقعی است و به سرویس‌اکانت Editor داده.
    """
    if folder_id:
        spreadsheet = client.create(title, folder_id=folder_id)
    else:
        logger.warning(
            "DRIVE_PARENT_FOLDER_ID تنظیم نشده؛ ساخت اسپردشیت ممکن است با "
            "خطای کوتای Drive شکست بخورد."
        )
        spreadsheet = client.create(title)
    return spreadsheet.id


# --- ظاهرِ اسپردشیت ------------------------------------------------------------
#
# فرمت‌بندی فقط ظاهر است و به داده دست نمی‌زند: ``overwrite_worksheet`` مقدارِ
# سلول‌ها را پاک و بازنویسی می‌کند ولی فرمتِ سلول را نگه می‌دارد. پس استایل
# یک‌بار موقعِ ساختِ تب اعمال می‌شود و برای همیشه می‌ماند.

#: قالبِ ردیفِ هدر — یک رنگِ ثابت برای همه‌ی تب‌ها.
HEADER_FORMAT = {
    "backgroundColor": {"red": 0.20, "green": 0.29, "blue": 0.37},
    "horizontalAlignment": "CENTER",
    "textFormat": {
        "bold": True,
        "foregroundColor": {"red": 1, "green": 1, "blue": 1},
    },
}

#: ستون‌های پولی/عددی که جداکننده‌ی هزارگان می‌گیرند.
MONEY_COLUMNS = frozenset({
    "amount", "unit_price", "usd", "price", "discount", "shipping", "total",
})

#: ستون‌های متنیِ بلند که باید پهن‌تر باشند.
WIDE_COLUMNS = frozenset({
    "description", "address", "note", "party_name", "customer_name",
    "customer_address", "title", "business_name", "raw_text",
})

#: پهنای ستونِ متنیِ بلند (پیکسل). پیش‌فرضِ گوگل ۱۰۰ است.
WIDE_COLUMN_PX = 220

_NUMBER_FORMAT = {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}}


def _col_letter(index: int) -> str:
    """۱ → ``A``، ۲۷ → ``AA``."""
    letters = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def _safely(what: str, action: Callable) -> None:
    """استایل نباید هیچ‌وقت جلوی کار کردنِ بات را بگیرد."""
    try:
        action()
    except Exception as exc:  # noqa: BLE001 - ظاهر است، نه داده
        logger.warning("استایلِ «%s» اعمال نشد: %s", what, exc)


def style_worksheet(ws, header: Sequence[str]) -> None:
    """ظاهرِ یک تبِ تازه‌ساخته‌شده را مرتب می‌کند.

    هدرِ بولد و رنگی، ردیفِ اول فریزشده، جداکننده‌ی هزارگان روی ستون‌های
    پولی، و پهنای بیشتر برای ستون‌های متنیِ بلند. ستونی که وجود نداشته
    باشد بی‌سروصدا رد می‌شود، و هر خطای API فقط لاگ می‌شود — هیچ‌کدام از
    این‌ها به مقدارِ سلول‌ها دست نمی‌زنند.
    """
    columns = [str(c) for c in (header or [])]
    if not columns:
        return

    last = _col_letter(len(columns))
    _safely("هدر", lambda: ws.format(f"A1:{last}1", HEADER_FORMAT))
    _safely("فریزِ هدر", lambda: ws.freeze(rows=1))

    for index, name in enumerate(columns, start=1):
        if name in MONEY_COLUMNS:
            letter = _col_letter(index)
            _safely(
                f"عددِ ستون {name}",
                lambda letter=letter: ws.format(f"{letter}2:{letter}", _NUMBER_FORMAT),
            )

    wide = [i for i, name in enumerate(columns) if name in WIDE_COLUMNS]
    if wide:
        _safely("پهنای ستون‌ها", lambda: _widen_columns(ws, wide))


def _widen_columns(ws, indexes: Sequence[int]) -> None:
    requests = [
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": ws.id, "dimension": "COLUMNS",
                    "startIndex": index, "endIndex": index + 1,
                },
                "properties": {"pixelSize": WIDE_COLUMN_PX},
                "fields": "pixelSize",
            }
        }
        for index in indexes
    ]
    ws.spreadsheet.batch_update({"requests": requests})


@with_retry
def ensure_worksheets(spreadsheet, models: Optional[Sequence] = None) -> None:
    """به‌صورت idempotent تب‌های خواسته‌شده را (با سطر هدر) می‌سازد.

    ``models`` را می‌دهیم تا اسپردشیت مرکزی فقط تب‌های رجیستری و اسپردشیت هر
    کاربر فقط تب‌های دفترِ خودش را داشته باشد. پیش‌فرض: همه‌ی مدل‌ها.
    """
    for model in (models if models is not None else ALL_MODELS):
        existing = {ws.title: ws for ws in spreadsheet.worksheets()}
        header = list(model.COLUMNS)
        if model.TABLE not in existing:
            ws = spreadsheet.add_worksheet(
                title=model.TABLE, rows=200, cols=max(len(header), 1)
            )
            ws.append_row(header)
            # فقط همین‌جا — تبِ موجود دوباره استایل نمی‌خورد تا هر بار
            # بالا آمدنِ بات چند ده فراخوانیِ اضافه به API نزند.
            style_worksheet(ws, header)
        elif not existing[model.TABLE].get_all_values():
            existing[model.TABLE].append_row(header)


@with_retry
def read_all_records(ws) -> list[dict]:
    """همه‌ی ردیف‌های داده را به‌صورت فهرست دیکشنری (هدر→مقدار) برمی‌گرداند."""
    return ws.get_all_records()


@with_retry
def overwrite_worksheet(ws, header: list, rows: list) -> None:
    """کلِ یک تب را بازنویسی می‌کند (هدر + ردیف‌ها).

    ساده، idempotent و safe-to-retry: به‌جای به‌روزرسانی ردیف‌به‌ردیف، کل تب
    از روی حافظه دوباره نوشته می‌شود.
    """
    ws.clear()
    ws.update([header] + rows, value_input_option="RAW")
