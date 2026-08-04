"""اتصال خام به Google Sheets و عملیات پایه (با تلاش مجدد).

توابع این ماژول همگی همگام (sync)‌اند؛ لایه‌ی :class:`~hesabyar.db.store.Store`
آن‌ها را با ``asyncio.to_thread`` صدا می‌زند تا حلقه‌ی async بلاک نشود.
"""
from __future__ import annotations

import functools
import json
import logging
import time
import zlib
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


# --- تبِ «خلاصه» و رنگِ دسته‌ها ---------------------------------------------------
#
# تبِ خلاصه فقط برای چشمِ کاربر است؛ بات هرگز از آن نمی‌خواند. ``Store`` تب‌ها را
# با نامِ مدل‌ها باز می‌کند (``USER_MODELS``)، پس این تب خودبه‌خود نادیده گرفته
# می‌شود. محتوایش هم همیشه از روی تب‌های اصلی بازتولید می‌شود — منبعِ حقیقت
# همان‌جاست، نه اینجا.

#: نامِ تبِ نمایشی. عمداً مدلی برایش وجود ندارد.
SUMMARY_SHEET_TITLE = "📋 خلاصه"

#: رنگ‌های چرخشیِ دسته‌های کالا (ملایم، تا متنِ مشکی خوانا بماند).
CATEGORY_COLORS = (
    {"red": 0.85, "green": 0.92, "blue": 0.83},
    {"red": 0.85, "green": 0.89, "blue": 0.96},
    {"red": 0.99, "green": 0.90, "blue": 0.80},
    {"red": 0.93, "green": 0.86, "blue": 0.95},
    {"red": 1.00, "green": 0.95, "blue": 0.80},
    {"red": 0.84, "green": 0.94, "blue": 0.94},
)


def color_for_category(name: str) -> dict:
    """رنگِ ثابتِ یک دسته — همیشه همان رنگ برای همان نام."""
    index = zlib.crc32((name or "").encode("utf-8")) % len(CATEGORY_COLORS)
    return CATEGORY_COLORS[index]


def _summary_rows(user, products, subscription) -> list[list]:
    """چیدمانِ عمودیِ تبِ خلاصه."""
    rows: list[list] = [
        ["👤 مشخصات کسب‌وکار", ""],
        ["نام کسب‌وکار", getattr(user, "business_name", "") or "—"],
        ["صنف", getattr(user, "business_type", "") or "—"],
        ["پلن اشتراک", subscription or "—"],
        ["", ""],
        ["📦 کالاها بر اساس دسته", ""],
    ]
    if not products:
        rows.append(["هنوز کالایی ثبت نشده", ""])
        return rows
    for category, items in products.items():
        rows.append([f"-- {category or 'بدون دسته'} --", ""])
        for item in items:
            rows.append([item.title, item.unit_price])
    return rows


def rebuild_summary_sheet(spreadsheet, user, products, subscription: str = "") -> None:
    """تبِ «📋 خلاصه» را از نو می‌سازد.

    ``products`` نگاشتِ «دسته → فهرست کالا» است (خروجیِ
    ``services.products.by_category``). این تب هر بار کامل بازنویسی می‌شود؛
    چون هیچ‌کس از آن نمی‌خواند، پاک‌شدن و دوباره‌نوشتنش بی‌خطر است.
    """
    rows = _summary_rows(user, products or {}, subscription)
    existing = {ws.title: ws for ws in spreadsheet.worksheets()}
    ws = existing.get(SUMMARY_SHEET_TITLE)
    if ws is None:
        ws = spreadsheet.add_worksheet(
            title=SUMMARY_SHEET_TITLE, rows=max(len(rows) + 20, 50), cols=2
        )
    ws.clear()
    ws.update(rows, value_input_option="RAW")
    _safely("هدرِ خلاصه", lambda: ws.format("A1:B1", HEADER_FORMAT))
    _safely("پهنای خلاصه", lambda: _widen_columns(ws, [0]))


def apply_category_colors(spreadsheet, ws, categories: Sequence[str]) -> None:
    """رنگِ پس‌زمینه‌ی هر ردیفِ ``products`` بر اساس دسته‌اش.

    قاعده‌ی شرطی روی خودِ تبِ اصلی می‌نشیند، پس جدول دست‌نخورده و
    قابل‌خواندن‌توسطِ بات می‌ماند و نیازی به ردیفِ جداکننده نیست.
    """
    column = _col_letter(_category_column_index())
    requests = _delete_rule_requests(spreadsheet, ws)
    for order, name in enumerate(dict.fromkeys(c for c in categories if c)):
        requests.append({
            "addConditionalFormatRule": {
                "index": order,
                "rule": {
                    "ranges": [{"sheetId": ws.id, "startRowIndex": 1}],
                    "booleanRule": {
                        "condition": {
                            "type": "CUSTOM_FORMULA",
                            "values": [{
                                "userEnteredValue": f'=${column}2="{name}"'
                            }],
                        },
                        "format": {"backgroundColor": color_for_category(name)},
                    },
                },
            }
        })
    if requests:
        _safely("رنگِ دسته‌ها", lambda: spreadsheet.batch_update({"requests": requests}))


def _category_column_index() -> int:
    from .models import Product
    return list(Product.COLUMNS).index("category") + 1


def _delete_rule_requests(spreadsheet, ws) -> list:
    """حذفِ قاعده‌های قبلی (از آخر به اول تا اندیس‌ها جابه‌جا نشوند)."""
    count = 0
    try:
        meta = spreadsheet.fetch_sheet_metadata(
            params={"fields": "sheets(properties(sheetId),conditionalFormats)"}
        )
        for sheet in meta.get("sheets", []):
            if sheet.get("properties", {}).get("sheetId") == ws.id:
                count = len(sheet.get("conditionalFormats") or [])
                break
    except Exception as exc:  # noqa: BLE001 - بدونِ حذف هم کار می‌کند
        logger.warning("خواندنِ قاعده‌های شرطی ناموفق: %s", exc)
        return []
    return [
        {"deleteConditionalFormatRule": {"sheetId": ws.id, "index": index}}
        for index in range(count - 1, -1, -1)
    ]


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
