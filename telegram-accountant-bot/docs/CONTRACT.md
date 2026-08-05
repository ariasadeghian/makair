# قرارداد واسط ماژول‌ها (Internal API Contract)

این سند امضای دقیق توابع هر ماژول را مشخص می‌کند تا بخش‌های مختلف کد
کاملاً با هم هماهنگ باشند. **مبالغ همه‌جا عدد صحیح و به «تومان» هستند.**

## پایه (نوشته‌شده و تست‌شده — تغییر ندهید)

### `hesabyar.core.money`
- `to_english_digits(text) -> str`
- `to_persian_digits(text) -> str`
- `normalize(text) -> str`
- `format_amount(toman: int, with_currency=True, currency="تومان") -> str`
- `parse_amount(text: str) -> Optional[int]`  # تومان
- `parse_int(text: str) -> Optional[int]`

### `hesabyar.core.jalali`
- `TEHRAN`  # tzinfo ایران (+03:30)
- `now() -> datetime`  # aware
- `to_jalali(value) -> jdatetime.date`
- `format_date(value) -> str`  # «۱۴۰۳/۰۵/۰۱»
- `format_date_long(value) -> str`  # «۱ مرداد ۱۴۰۳»
- `format_datetime(dt) -> str`
- `month_name(m) -> str`
- `weekday_name(value) -> str`
- `parse_relative_date(text, base=None) -> Optional[date]`  # date میلادی
- `day_bounds/week_bounds/month_bounds(base=None) -> (start_dt, end_dt)`  # aware

### `hesabyar.core.categories`
- `detect_category(text: str, kind: str) -> str`

### `hesabyar.db.models`
- مدل‌ها **دیتاکلاس** ساده‌اند (نه ORM): `User`, `Transaction`, `LedgerEntry`,
  `Invoice`, `InvoiceItem`, `Subscription`, `Payment`, `Product`, `GroupEvent`
  (رویدادهای مالیِ گروه: درخواست پرداخت/پرداخت).
- هر مدل classvarهای `TABLE` (نام تب) و `COLUMNS` (ترتیب ستون‌ها) و متدهای
  `to_row() -> list` و `from_row(cls, dict) -> obj` دارد (سریال‌سازی برای شیت:
  datetime/date به ISO، bool به `"TRUE"`/`"FALSE"`).
- `Kind.INCOME`, `Kind.EXPENSE`
- `Direction.RECEIVABLE` (طلب من)، `Direction.PAYABLE` (بدهی من)
- `Invoice.subtotal`/`Invoice.total` (property؛ با discount/shipping)،
  `InvoiceItem.line_total` (property). `Invoice.items` غیرِ persist است و توسط
  سرویس پر می‌شود.
- `ALL_MODELS` و `TABLE_MODELS = {TABLE: model}`.

### `hesabyar.db.sheets_client`
- `get_gspread_client(settings)` — از `settings.google_service_account_json`
- `open_spreadsheet(client, sheet_id)`
- `ensure_worksheets(spreadsheet)` — تب‌های همه‌ی مدل‌ها را idempotent می‌سازد
- `read_all_records(ws) -> list[dict]`، `overwrite_worksheet(ws, header, rows)`
- `with_retry(fn, ...)` — backoff نمایی روی خطاهای نرخ/سرور (429/5xx)

### `hesabyar.db.store.Store`
- منبعِ حقیقت در حافظه روی یک اسپردشیت. سازنده: `Store(spreadsheet)`.
- `await load()` — همه‌ی تب‌ها را می‌خواند و اشیاء را می‌سازد.
- خواندن (sync): `get(table, id)`، `list(table, predicate=None)`، `next_id(table)`.
- نوشتن (async): `await add(table, obj)`، `await update(table, obj)`،
  `await delete(table, id)` — روی حافظه اعمال و تب را dirty می‌کنند.
- `await flush()` — تب‌های dirty را روی شیت بازنویسی می‌کند.
- `start_background_flush(interval=5)` و `await stop()` (flush قطعی).
- `commit()` — no-op (سازگاری با کد قدیمی).

---

## ماژول‌هایی که باید ساخته شوند

> **به‌روزرسانی (مهاجرت به Google Sheets):** سرویس‌های زیر دیگر `session`
> نمی‌گیرند بلکه `store` (نمونه‌ی `Store`). توابعِ **نوشتن** async شده‌اند و باید
> `await` شوند (مثل `get_or_create_user`, `add_transaction`, `delete_transaction`,
> `add_entry`, `settle`, `create_invoice`, `add_product`, `create_payment`,
> `approve_payment` ...)؛ توابعِ **خواندن** هم‌چنان sync‌اند. در امضاهای پایین
> `session` را ذهناً `store` و نوشتن‌ها را `async`/`await` بخوانید.

### `hesabyar.core.nlp`
```python
@dataclass
class ParsedTransaction:
    kind: str            # Kind.INCOME یا Kind.EXPENSE
    amount: int          # تومان
    category: str
    description: str
    occurred_at: datetime  # aware، منطقه‌ی تهران
    raw: str

def parse_transaction(text: str, base: datetime | None = None) -> ParsedTransaction | None
```
- نوع را با کلیدواژه تشخیص بده: هزینه = {خرید، خریدم، دادم، پرداخت، پرداختم، خرج، هزینه، حساب کردم، رد کردم}؛ درآمد = {فروش، فروختم، گرفتم، دریافت، درآمد، واریز، وصول، فروختیم}. اگر مبهم بود پیش‌فرض «هزینه».
- تاریخ را با `jalali.parse_relative_date` بگیر (پیش‌فرض امروز)، سپس آن را با ساعت `base` ترکیب کن.
- مبلغ را با `money.parse_amount` بگیر؛ اگر `None` بود، خروجی `None`.
- دسته را با `categories.detect_category(text, kind)`.
- `description`: متن پاک‌شده (بدون بخش مبلغ/واحد پول/واژه‌ی تاریخ)، best-effort.

### `hesabyar.services.ocr`
```python
class OcrUnavailable(Exception): ...
class OcrProvider(Protocol):
    async def extract_text(self, image_bytes: bytes) -> str: ...
class NullOcrProvider:      # extract_text → raise OcrUnavailable
class VisionLLMOcrProvider: # OpenAI-compatible vision (httpx.AsyncClient)، base_url/api_key/model
def get_ocr_provider(settings) -> OcrProvider   # VisionLLM اگر settings.ocr_enabled وگرنه Null
def parse_receipt_text(text: str, base=None) -> ParsedTransaction | None  # از nlp.parse_transaction
```
- تست‌ها نباید به شبکه وصل شوند (VisionLLM را فقط با mock بیازمایید).

### `hesabyar.services.transactions`
```python
def get_or_create_user(session, user_id, business_name=None) -> User
def add_transaction(session, user_id, *, kind, amount, category, description, occurred_at) -> Transaction
def list_transactions(session, user_id, start, end, kind=None) -> list[Transaction]
def summary(session, user_id, start, end) -> dict
    # {'income': int, 'expense': int, 'balance': int, 'count': int,
    #  'expense_by_category': dict[str,int], 'income_by_category': dict[str,int]}
def delete_last(session, user_id) -> Transaction | None
```

### `hesabyar.services.reports`
```python
def period_label(period: str) -> str          # 'day'|'week'|'month' → «امروز/این هفته/این ماه»
def build_report(session, user_id, base, period) -> str   # متن فارسی چندخطی
```
- از `jalali.*_bounds` و `transactions.summary` استفاده کن. جمع درآمد/هزینه/مانده و چند دسته‌ی برتر هزینه.

### `hesabyar.services.ledger`
```python
def add_entry(session, user_id, *, direction, party_name, amount, due_date=None, description="") -> LedgerEntry
def list_open(session, user_id, direction=None) -> list[LedgerEntry]
def settle(session, entry_id, user_id, when) -> LedgerEntry | None
def totals(session, user_id) -> dict          # {'receivable': int, 'payable': int, 'net': int}
def due_within(session, user_id, days, base) -> list[LedgerEntry]   # باز، due_date <= base+days (شامل معوق)
def entries_due_for_reminder(session, base) -> list[LedgerEntry]    # همه‌ی کاربران، باز، due_date <= امروز
def build_ledger_report(session, user_id) -> str
```

### `hesabyar.services.invoices`
```python
def next_invoice_number(session, user_id, base) -> tuple[str, int]   # (شماره‌ی نمایشی، seq)
def create_invoice(session, user_id, *, customer_name, items, issue_date,
                   customer_phone="", customer_address="", note="", base=None) -> Invoice
    # items: list[dict(title:str, quantity:int, unit_price:int)]
def get_invoice(session, invoice_id, user_id) -> Invoice | None
def list_invoices(session, user_id, limit=10) -> list[Invoice]
```
- شماره: seq = بیشترین seq کاربر + ۱؛ نمایش = «{سال‌شمسی}-{seq:04d}» با ارقام فارسی.

### `hesabyar.pdf.invoice_pdf`
```python
def register_font() -> str    # ثبت Vazirmatn، برگرداندن نام فونت
def render_invoice_pdf(invoice, business, out_path: str, payment_note="",
                       watermark="", logo_path="", stamp_path="") -> str
```
- با `reportlab` + `arabic_reshaper` + `python-bidi` متن فارسی راست‌به‌چپ را شکل بده.
- فونت از `hesabyar/pdf/fonts/Vazirmatn-Regular.ttf` (کنار همین ماژول). اگر نبود، متغیر محیطی `HESABYAR_PDF_FONT`.
- سربرگ (نام کسب‌وکار/تلفن)، شماره و تاریخ فاکتور، مشخصات مشتری، جدول اقلام (ردیف، شرح، تعداد، قیمت واحد، جمع)، جمع کل.
- **شکستنِ خطِ متنِ بلند با `_fit_lines`/`_paras`، نه با خودِ reportlab.** چون
  `shape_fa` متن را به ترتیبِ *دیداری* درمی‌آورد، سپردنِ شکستن به reportlab
  ابتدای جمله را می‌اندازد خطِ آخر («تلفن:» یک خط پایین‌تر از شماره‌اش).
  اول بشکن، بعد هر خط را جدا شکل بده.
- `logo_path`/`stamp_path`: فایلِ روی دیسک؛ خالی یا خراب ⇒ سند بدون تصویر
  ساخته می‌شود، هرگز خطا نمی‌دهد. مسیرها را
  `hesabyar.services.images.seller_images(bot, source)` می‌سازد.
- تست: یک `Invoice` جدا (بدون session) با چند `InvoiceItem` بساز، PDF تولید کن و بررسی کن فایل ساخته شده، با `%PDF` شروع می‌شود و اندازه‌اش > ۱۰۰۰ بایت است.

## قواعد مشترک
- همه‌ی رشته‌های نمایشی فارسی؛ مبالغ با `money.format_amount`؛ تاریخ‌ها با `jalali`.
- تست‌ها با یک اسپردشیتِ ساختگی در حافظه (`tests/fakes.py`) و بدون شبکه؛
  fixtureی `store` در `tests/conftest.py`. حالت async با `asyncio_mode=auto`.
- هر ماژول تست خودش را دارد؛ فقط تست خودتان را اجرا کنید:
  `cd telegram-accountant-bot && python -m pytest tests/<file> -q`
