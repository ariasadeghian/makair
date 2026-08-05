"""مدل‌های داده به‌صورت دیتاکلاس (منبع اصلی: Google Sheets).

هر جدول یک تب در اسپردشیت است. هر دیتاکلاس ``COLUMNS`` (ترتیب ستون‌ها)،
``TABLE`` (نام تب) و دو متد ``to_row``/``from_row`` برای تبدیل به/از ردیف شیت
دارد. همه‌ی مبالغ به «تومان» و عدد صحیح‌اند.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Optional


# --- ثابت‌ها -----------------------------------------------------------------


class Kind:
    INCOME = "income"
    EXPENSE = "expense"
    ALL = (INCOME, EXPENSE)


class Direction:
    RECEIVABLE = "receivable"  # طلب من از دیگران
    PAYABLE = "payable"  # بدهی من به دیگران
    ALL = (RECEIVABLE, PAYABLE)


class Instrument:
    CASH = "cash"      # نقدی/معمولی
    CHEQUE = "cheque"  # چک (سررسیدِ پاس‌شدن مهم است)
    ALL = (CASH, CHEQUE)


class PaymentStatus:
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ALL = (PENDING, APPROVED, REJECTED)


class GroupEventKind:
    REQUEST = "request"  # درخواست پرداخت (الف از ب می‌خواهد بپردازد)
    PAYMENT = "payment"  # پرداخت انجام‌شده
    ALL = (REQUEST, PAYMENT)


class GroupEventStatus:
    OPEN = "open"        # درخواستِ بازِ پرداخت‌نشده
    SETTLED = "settled"  # درخواستِ پرداخت‌شده
    LOGGED = "logged"    # پرداختِ مستقل (بدون درخواست قبلی)
    ALL = (OPEN, SETTLED, LOGGED)


# --- کمک‌توابع تبدیل مقدار ↔ سلولِ شیت --------------------------------------


def _s(value) -> str:
    """سریال‌سازی یک مقدار پایتون به رشته‌ی سلول."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    return str(value)


def _pint(value) -> Optional[int]:
    if value is None or value == "":
        return None
    return int(float(value))


def _pstr(value) -> str:
    return "" if value is None else str(value)


def _pbool(value) -> bool:
    return value is True or str(value).strip().upper() == "TRUE"


def _pdt(value) -> Optional[dt.datetime]:
    if value is None or value == "":
        return None
    return dt.datetime.fromisoformat(str(value))


def _pdate(value) -> Optional[dt.date]:
    if value is None or value == "":
        return None
    return dt.date.fromisoformat(str(value)[:10])


# --- دیتاکلاس‌ها --------------------------------------------------------------


@dataclass
class User:
    TABLE = "users"
    COLUMNS = (
        "id", "business_name", "phone", "address", "currency", "created_at",
        "business_type", "sheet_id", "onboarded",
        # سربرگِ فاکتور — فهرست و اعتبارسنجی‌شان در hesabyar/core/seller.py
        "mobile", "postal_code", "email", "instagram", "website",
        "economic_code", "national_id",
    )

    id: Optional[int] = None
    business_name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    currency: str = "تومان"
    created_at: Optional[dt.datetime] = None
    #: کلیدِ صنفِ کسب‌وکار (hesabyar.core.industries)؛ خالی = نامشخص.
    business_type: str = ""
    #: شناسه‌ی اسپردشیتِ اختصاصیِ همین کاربر (دفترِ خودش).
    sheet_id: Optional[str] = None
    #: ویزاردِ شروع یک‌بار اجرا شده است؟ (حتی اگر کاربر مرحله‌ها را رد کرده
    #: باشد) — تا با هر ``/start`` دوباره نپرسیم.
    onboarded: bool = False
    #: --- سربرگِ فاکتور: یک‌بار پر می‌شود، روی هر سند می‌نشیند ---
    mobile: str = ""
    postal_code: str = ""
    email: str = ""
    instagram: str = ""
    website: str = ""
    economic_code: str = ""
    national_id: str = ""

    def to_row(self) -> list:
        return [
            _s(self.id), _s(self.business_name), _s(self.phone),
            _s(self.address), _s(self.currency), _s(self.created_at),
            _s(self.business_type), _s(self.sheet_id), _s(self.onboarded),
            _s(self.mobile), _s(self.postal_code), _s(self.email),
            _s(self.instagram), _s(self.website), _s(self.economic_code),
            _s(self.national_id),
        ]

    @classmethod
    def from_row(cls, d: dict) -> "User":
        return cls(
            id=_pint(d.get("id")),
            business_name=(d.get("business_name") or None),
            phone=(d.get("phone") or None),
            address=(d.get("address") or None),
            currency=(d.get("currency") or "تومان"),
            created_at=_pdt(d.get("created_at")),
            business_type=_pstr(d.get("business_type")),
            sheet_id=(d.get("sheet_id") or None),
            # ردیف‌های قدیمی این ستون را ندارند؛ اگر نامِ کسب‌وکار دارند یعنی
            # از قبل راه افتاده‌اند و نباید دوباره ویزارد ببینند.
            onboarded=_pbool(d.get("onboarded")) or bool(d.get("business_name")),
            mobile=_pstr(d.get("mobile")),
            postal_code=_pstr(d.get("postal_code")),
            email=_pstr(d.get("email")),
            instagram=_pstr(d.get("instagram")),
            website=_pstr(d.get("website")),
            economic_code=_pstr(d.get("economic_code")),
            national_id=_pstr(d.get("national_id")),
        )


@dataclass
class Transaction:
    TABLE = "transactions"
    COLUMNS = (
        "id", "user_id", "kind", "amount", "category",
        "description", "occurred_at", "created_at", "branch_id", "logged_by",
    )

    id: Optional[int] = None
    user_id: int = 0
    kind: str = Kind.EXPENSE
    amount: int = 0
    category: str = "متفرقه"
    description: str = ""
    occurred_at: Optional[dt.datetime] = None
    created_at: Optional[dt.datetime] = None
    #: شعبه‌ی ثبت‌کننده (۰ = خودِ صاحب کسب‌وکار، بدون شعبه)
    branch_id: int = 0
    #: آیدی تلگرامِ کسی که ثبت کرده (اگر کارمندِ شعبه باشد)
    logged_by: Optional[int] = None

    def to_row(self) -> list:
        return [
            _s(self.id), _s(self.user_id), _s(self.kind), _s(self.amount),
            _s(self.category), _s(self.description), _s(self.occurred_at),
            _s(self.created_at), _s(self.branch_id), _s(self.logged_by),
        ]

    @classmethod
    def from_row(cls, d: dict) -> "Transaction":
        return cls(
            id=_pint(d.get("id")),
            user_id=_pint(d.get("user_id")) or 0,
            kind=_pstr(d.get("kind")),
            amount=_pint(d.get("amount")) or 0,
            category=_pstr(d.get("category")),
            description=_pstr(d.get("description")),
            occurred_at=_pdt(d.get("occurred_at")),
            created_at=_pdt(d.get("created_at")),
            branch_id=_pint(d.get("branch_id")) or 0,
            logged_by=_pint(d.get("logged_by")),
        )


@dataclass
class LedgerEntry:
    TABLE = "ledger_entries"
    COLUMNS = (
        "id", "user_id", "direction", "party_name", "amount",
        "description", "due_date", "is_settled", "settled_at", "created_at",
        "instrument", "cheque_no", "party_tg_id", "customer_id",
    )

    id: Optional[int] = None
    user_id: int = 0
    direction: str = Direction.RECEIVABLE
    party_name: str = ""
    amount: int = 0
    description: str = ""
    due_date: Optional[dt.date] = None
    is_settled: bool = False
    settled_at: Optional[dt.datetime] = None
    created_at: Optional[dt.datetime] = None
    instrument: str = Instrument.CASH
    cheque_no: str = ""
    #: آیدی تلگرامِ طرف‌حساب (اگر لینک فاکتوری را باز کرده باشد) — برای
    #: فرستادنِ یادآوریِ بدهی مستقیم به خودش.
    party_tg_id: Optional[int] = None
    #: لینک به رکورد مشتری (party_name برای نمایش/سازگاری می‌ماند)
    customer_id: Optional[int] = None

    @property
    def is_cheque(self) -> bool:
        return self.instrument == Instrument.CHEQUE

    def to_row(self) -> list:
        return [
            _s(self.id), _s(self.user_id), _s(self.direction), _s(self.party_name),
            _s(self.amount), _s(self.description), _s(self.due_date),
            _s(self.is_settled), _s(self.settled_at), _s(self.created_at),
            _s(self.instrument), _s(self.cheque_no), _s(self.party_tg_id),
            _s(self.customer_id),
        ]

    @classmethod
    def from_row(cls, d: dict) -> "LedgerEntry":
        return cls(
            id=_pint(d.get("id")),
            user_id=_pint(d.get("user_id")) or 0,
            direction=_pstr(d.get("direction")),
            party_name=_pstr(d.get("party_name")),
            amount=_pint(d.get("amount")) or 0,
            description=_pstr(d.get("description")),
            due_date=_pdate(d.get("due_date")),
            is_settled=_pbool(d.get("is_settled")),
            settled_at=_pdt(d.get("settled_at")),
            created_at=_pdt(d.get("created_at")),
            instrument=_pstr(d.get("instrument")) or Instrument.CASH,
            cheque_no=_pstr(d.get("cheque_no")),
            party_tg_id=_pint(d.get("party_tg_id")),
            customer_id=_pint(d.get("customer_id")),
        )


@dataclass
class InvoiceItem:
    TABLE = "invoice_items"
    COLUMNS = ("id", "invoice_id", "title", "quantity", "unit_price")

    id: Optional[int] = None
    invoice_id: int = 0
    title: str = ""
    quantity: int = 1
    unit_price: int = 0

    @property
    def line_total(self) -> int:
        return int(self.quantity) * int(self.unit_price)

    def to_row(self) -> list:
        return [
            _s(self.id), _s(self.invoice_id), _s(self.title),
            _s(self.quantity), _s(self.unit_price),
        ]

    @classmethod
    def from_row(cls, d: dict) -> "InvoiceItem":
        return cls(
            id=_pint(d.get("id")),
            invoice_id=_pint(d.get("invoice_id")) or 0,
            title=_pstr(d.get("title")),
            quantity=_pint(d.get("quantity")) or 0,
            unit_price=_pint(d.get("unit_price")) or 0,
        )


@dataclass
class Invoice:
    TABLE = "invoices"
    COLUMNS = (
        "id", "user_id", "number", "seq", "customer_name", "customer_phone",
        "customer_address", "issue_date", "note", "discount", "shipping",
        "created_at", "share_token", "customer_tg_id", "rating", "customer_id",
        # اسنپ‌شاتِ فروشنده در لحظه‌ی صدور — سند نباید با تغییرِ پروفایل عوض شود
        "seller_business_name", "seller_address", "seller_phone", "seller_mobile",
        "seller_postal_code", "seller_email", "seller_instagram", "seller_website",
        "seller_economic_code", "seller_national_id",
    )

    id: Optional[int] = None
    user_id: int = 0
    number: str = ""
    seq: int = 0
    customer_name: str = ""
    customer_phone: str = ""
    customer_address: str = ""
    issue_date: Optional[dt.date] = None
    note: str = ""
    discount: int = 0
    shipping: int = 0
    created_at: Optional[dt.datetime] = None
    #: شناسه‌ی تصادفیِ لینک اشتراک‌گذاری (تا شماره‌ها قابل حدس‌زدن نباشند)
    share_token: str = ""
    #: آیدی تلگرامِ مشتری، وقتی لینک فاکتور را باز کرد
    customer_tg_id: Optional[int] = None
    #: امتیاز مشتری به این خرید (۱ تا ۵؛ ۰ = بدون امتیاز)
    rating: int = 0
    #: لینک به رکورد مشتری (customer_name برای نمایش/سازگاری می‌ماند)
    customer_id: Optional[int] = None
    #: --- اسنپ‌شاتِ فروشنده: از پروفایل کپی می‌شود و دیگر تغییر نمی‌کند ---
    seller_business_name: str = ""
    seller_address: str = ""
    seller_phone: str = ""
    seller_mobile: str = ""
    seller_postal_code: str = ""
    seller_email: str = ""
    seller_instagram: str = ""
    seller_website: str = ""
    seller_economic_code: str = ""
    seller_national_id: str = ""
    #: اقلام فاکتور — از جدول invoice_items پر می‌شود (در شیت ذخیره نمی‌شود).
    items: list = field(default_factory=list)

    @property
    def subtotal(self) -> int:
        return sum(item.line_total for item in self.items)

    @property
    def total(self) -> int:
        return self.subtotal - int(self.discount or 0) + int(self.shipping or 0)

    def to_row(self) -> list:
        return [
            _s(self.id), _s(self.user_id), _s(self.number), _s(self.seq),
            _s(self.customer_name), _s(self.customer_phone),
            _s(self.customer_address), _s(self.issue_date), _s(self.note),
            _s(self.discount), _s(self.shipping), _s(self.created_at),
            _s(self.share_token), _s(self.customer_tg_id), _s(self.rating),
            _s(self.customer_id),
            _s(self.seller_business_name), _s(self.seller_address),
            _s(self.seller_phone), _s(self.seller_mobile),
            _s(self.seller_postal_code), _s(self.seller_email),
            _s(self.seller_instagram), _s(self.seller_website),
            _s(self.seller_economic_code), _s(self.seller_national_id),
        ]

    @classmethod
    def from_row(cls, d: dict) -> "Invoice":
        return cls(
            id=_pint(d.get("id")),
            user_id=_pint(d.get("user_id")) or 0,
            number=_pstr(d.get("number")),
            seq=_pint(d.get("seq")) or 0,
            customer_name=_pstr(d.get("customer_name")),
            customer_phone=_pstr(d.get("customer_phone")),
            customer_address=_pstr(d.get("customer_address")),
            issue_date=_pdate(d.get("issue_date")),
            note=_pstr(d.get("note")),
            discount=_pint(d.get("discount")) or 0,
            shipping=_pint(d.get("shipping")) or 0,
            created_at=_pdt(d.get("created_at")),
            share_token=_pstr(d.get("share_token")),
            customer_tg_id=_pint(d.get("customer_tg_id")),
            rating=_pint(d.get("rating")) or 0,
            customer_id=_pint(d.get("customer_id")),
            seller_business_name=_pstr(d.get("seller_business_name")),
            seller_address=_pstr(d.get("seller_address")),
            seller_phone=_pstr(d.get("seller_phone")),
            seller_mobile=_pstr(d.get("seller_mobile")),
            seller_postal_code=_pstr(d.get("seller_postal_code")),
            seller_email=_pstr(d.get("seller_email")),
            seller_instagram=_pstr(d.get("seller_instagram")),
            seller_website=_pstr(d.get("seller_website")),
            seller_economic_code=_pstr(d.get("seller_economic_code")),
            seller_national_id=_pstr(d.get("seller_national_id")),
        )


@dataclass
class Subscription:
    TABLE = "subscriptions"
    COLUMNS = (
        "id", "user_id", "plan", "is_trial", "expires_at",
        "created_at", "updated_at",
    )

    id: Optional[int] = None
    user_id: int = 0
    plan: str = "trial"
    is_trial: bool = True
    expires_at: Optional[dt.datetime] = None
    created_at: Optional[dt.datetime] = None
    updated_at: Optional[dt.datetime] = None

    def to_row(self) -> list:
        return [
            _s(self.id), _s(self.user_id), _s(self.plan), _s(self.is_trial),
            _s(self.expires_at), _s(self.created_at), _s(self.updated_at),
        ]

    @classmethod
    def from_row(cls, d: dict) -> "Subscription":
        return cls(
            id=_pint(d.get("id")),
            user_id=_pint(d.get("user_id")) or 0,
            plan=_pstr(d.get("plan")) or "trial",
            is_trial=_pbool(d.get("is_trial")),
            expires_at=_pdt(d.get("expires_at")),
            created_at=_pdt(d.get("created_at")),
            updated_at=_pdt(d.get("updated_at")),
        )


@dataclass
class Payment:
    TABLE = "payments"
    COLUMNS = (
        "id", "user_id", "plan", "amount", "status", "reference",
        "receipt_file_id", "created_at", "reviewed_at", "reviewed_by",
    )

    id: Optional[int] = None
    user_id: int = 0
    plan: str = ""
    amount: int = 0
    status: str = PaymentStatus.PENDING
    reference: str = ""
    receipt_file_id: Optional[str] = None
    created_at: Optional[dt.datetime] = None
    reviewed_at: Optional[dt.datetime] = None
    reviewed_by: Optional[int] = None

    def to_row(self) -> list:
        return [
            _s(self.id), _s(self.user_id), _s(self.plan), _s(self.amount),
            _s(self.status), _s(self.reference), _s(self.receipt_file_id),
            _s(self.created_at), _s(self.reviewed_at), _s(self.reviewed_by),
        ]

    @classmethod
    def from_row(cls, d: dict) -> "Payment":
        return cls(
            id=_pint(d.get("id")),
            user_id=_pint(d.get("user_id")) or 0,
            plan=_pstr(d.get("plan")),
            amount=_pint(d.get("amount")) or 0,
            status=_pstr(d.get("status")) or PaymentStatus.PENDING,
            reference=_pstr(d.get("reference")),
            receipt_file_id=(d.get("receipt_file_id") or None),
            created_at=_pdt(d.get("created_at")),
            reviewed_at=_pdt(d.get("reviewed_at")),
            reviewed_by=_pint(d.get("reviewed_by")),
        )


@dataclass
class Product:
    TABLE = "products"
    COLUMNS = ("id", "user_id", "title", "unit_price", "created_at", "category")

    id: Optional[int] = None
    user_id: int = 0
    title: str = ""
    unit_price: int = 0
    created_at: Optional[dt.datetime] = None
    #: دسته‌بندیِ دلخواهِ کاربر (خالی = دسته‌بندی‌نشده).
    category: str = ""

    def to_row(self) -> list:
        return [
            _s(self.id), _s(self.user_id), _s(self.title),
            _s(self.unit_price), _s(self.created_at), _s(self.category),
        ]

    @classmethod
    def from_row(cls, d: dict) -> "Product":
        return cls(
            id=_pint(d.get("id")),
            user_id=_pint(d.get("user_id")) or 0,
            title=_pstr(d.get("title")),
            unit_price=_pint(d.get("unit_price")) or 0,
            created_at=_pdt(d.get("created_at")),
            category=_pstr(d.get("category")),
        )


@dataclass
class GroupEvent:
    """یک رویداد مالی در یک گروه تلگرام (درخواست پرداخت یا پرداخت).

    برای ``kind == "request"``: ``actor`` درخواست‌دهنده و ``counterparty`` کسی
    است که باید بپردازد. برای ``kind == "payment"``: ``actor`` پرداخت‌کننده و
    ``counterparty`` دریافت‌کننده است. ``request_id`` یک پرداخت را به درخواستِ
    مرتبطش وصل می‌کند.
    """

    TABLE = "group_events"
    COLUMNS = (
        "id", "chat_id", "kind", "actor_id", "actor_name",
        "counterparty_id", "counterparty_name", "amount", "reason",
        "status", "request_id", "created_at", "settled_at",
    )

    id: Optional[int] = None
    chat_id: int = 0
    kind: str = GroupEventKind.REQUEST
    actor_id: int = 0
    actor_name: str = ""
    counterparty_id: Optional[int] = None
    counterparty_name: str = ""
    amount: int = 0
    reason: str = ""
    status: str = GroupEventStatus.OPEN
    request_id: Optional[int] = None
    created_at: Optional[dt.datetime] = None
    settled_at: Optional[dt.datetime] = None

    def to_row(self) -> list:
        return [
            _s(self.id), _s(self.chat_id), _s(self.kind), _s(self.actor_id),
            _s(self.actor_name), _s(self.counterparty_id),
            _s(self.counterparty_name), _s(self.amount), _s(self.reason),
            _s(self.status), _s(self.request_id), _s(self.created_at),
            _s(self.settled_at),
        ]

    @classmethod
    def from_row(cls, d: dict) -> "GroupEvent":
        return cls(
            id=_pint(d.get("id")),
            chat_id=_pint(d.get("chat_id")) or 0,
            kind=_pstr(d.get("kind")) or GroupEventKind.REQUEST,
            actor_id=_pint(d.get("actor_id")) or 0,
            actor_name=_pstr(d.get("actor_name")),
            counterparty_id=_pint(d.get("counterparty_id")),
            counterparty_name=_pstr(d.get("counterparty_name")),
            amount=_pint(d.get("amount")) or 0,
            reason=_pstr(d.get("reason")),
            status=_pstr(d.get("status")) or GroupEventStatus.OPEN,
            request_id=_pint(d.get("request_id")),
            created_at=_pdt(d.get("created_at")),
            settled_at=_pdt(d.get("settled_at")),
        )


@dataclass
class Rate:
    """نرخ دلار در یک روز (تومان به ازای هر دلار).

    برای هر تاریخ حداکثر یک ردیف نگه داشته می‌شود؛ ثبت دوباره‌ی همان روز
    مقدار را به‌روز می‌کند.
    """

    TABLE = "rates"
    COLUMNS = ("id", "date", "usd", "source", "created_at")

    id: Optional[int] = None
    date: Optional[dt.date] = None
    usd: int = 0  # تومان به ازای هر دلار
    source: str = "manual"  # manual | channel
    created_at: Optional[dt.datetime] = None

    def to_row(self) -> list:
        return [
            _s(self.id), _s(self.date), _s(self.usd),
            _s(self.source), _s(self.created_at),
        ]

    @classmethod
    def from_row(cls, d: dict) -> "Rate":
        return cls(
            id=_pint(d.get("id")),
            date=_pdate(d.get("date")),
            usd=_pint(d.get("usd")) or 0,
            source=_pstr(d.get("source")) or "manual",
            created_at=_pdt(d.get("created_at")),
        )


@dataclass
class Branch:
    """یک شعبه از کسب‌وکار (برای صاحبانی که بیش از یک نقطه‌ی فروش دارند)."""

    TABLE = "branches"
    COLUMNS = ("id", "owner_id", "name", "code", "is_active", "created_at")

    id: Optional[int] = None
    owner_id: int = 0
    name: str = ""
    code: str = ""  # کد پیوستن که صاحب کسب‌وکار به کارمند می‌دهد
    is_active: bool = True
    created_at: Optional[dt.datetime] = None

    def to_row(self) -> list:
        return [
            _s(self.id), _s(self.owner_id), _s(self.name), _s(self.code),
            _s(self.is_active), _s(self.created_at),
        ]

    @classmethod
    def from_row(cls, d: dict) -> "Branch":
        return cls(
            id=_pint(d.get("id")),
            owner_id=_pint(d.get("owner_id")) or 0,
            name=_pstr(d.get("name")),
            code=_pstr(d.get("code")),
            is_active=_pbool(d.get("is_active")),
            created_at=_pdt(d.get("created_at")),
        )


@dataclass
class BranchMember:
    """کارمندی که با کدِ شعبه به آن پیوسته و از طرفِ همان شعبه ثبت می‌کند."""

    TABLE = "branch_members"
    COLUMNS = ("id", "branch_id", "owner_id", "user_id", "name", "created_at")

    id: Optional[int] = None
    branch_id: int = 0
    owner_id: int = 0
    user_id: int = 0
    name: str = ""
    created_at: Optional[dt.datetime] = None

    def to_row(self) -> list:
        return [
            _s(self.id), _s(self.branch_id), _s(self.owner_id),
            _s(self.user_id), _s(self.name), _s(self.created_at),
        ]

    @classmethod
    def from_row(cls, d: dict) -> "BranchMember":
        return cls(
            id=_pint(d.get("id")),
            branch_id=_pint(d.get("branch_id")) or 0,
            owner_id=_pint(d.get("owner_id")) or 0,
            user_id=_pint(d.get("user_id")) or 0,
            name=_pstr(d.get("name")),
            created_at=_pdt(d.get("created_at")),
        )


@dataclass
class Customer:
    """یک طرف‌حساب (مشتری/تأمین‌کننده) که یک‌بار ذخیره و بارها استفاده می‌شود."""

    TABLE = "customers"
    COLUMNS = ("id", "user_id", "name", "phone", "address", "note", "created_at")

    id: Optional[int] = None
    user_id: int = 0
    name: str = ""
    phone: str = ""
    address: str = ""
    note: str = ""
    created_at: Optional[dt.datetime] = None

    def to_row(self) -> list:
        return [
            _s(self.id), _s(self.user_id), _s(self.name), _s(self.phone),
            _s(self.address), _s(self.note), _s(self.created_at),
        ]

    @classmethod
    def from_row(cls, d: dict) -> "Customer":
        return cls(
            id=_pint(d.get("id")),
            user_id=_pint(d.get("user_id")) or 0,
            name=_pstr(d.get("name")),
            phone=_pstr(d.get("phone")),
            address=_pstr(d.get("address")),
            note=_pstr(d.get("note")),
            created_at=_pdt(d.get("created_at")),
        )


@dataclass
class Sequence:
    """شمارنده‌ی شناسه‌ی هر جدول (در اسپردشیت مرکزی).

    چون داده‌ی هر کاربر در اسپردشیت جداگانه‌ای است، بدون یک شمارنده‌ی مرکزی
    ممکن بود دو کاربر شناسه‌ی یکسان بگیرند و در حافظه روی هم بیفتند.
    """

    TABLE = "sequences"
    COLUMNS = ("id", "name", "last_id")

    id: Optional[int] = None
    name: str = ""
    last_id: int = 0

    def to_row(self) -> list:
        return [_s(self.id), _s(self.name), _s(self.last_id)]

    @classmethod
    def from_row(cls, d: dict) -> "Sequence":
        return cls(
            id=_pint(d.get("id")),
            name=_pstr(d.get("name")),
            last_id=_pint(d.get("last_id")) or 0,
        )


#: جدول‌های اسپردشیتِ **مرکزی** — لایه‌ی حساب/رجیستری.
#: این‌ها عمداً مرکزی‌اند چون کوئری‌شان ذاتاً بین‌کاربری است: ادمین پرداختی را
#: فقط با شناسه‌اش تأیید می‌کند، کارمند با «کد» به شعبه می‌پیوندد (هنوز مالک
#: را نمی‌شناسیم)، و نرخ دلار سراسری است.
CENTRAL_MODELS = (User, Subscription, Payment, Rate, Branch, BranchMember, Sequence)

#: جدول‌های اسپردشیتِ **اختصاصیِ هر کاربر** — دفترِ واقعیِ کسب‌وکار.
USER_MODELS = (
    Transaction, LedgerEntry, Invoice, InvoiceItem, Product, GroupEvent, Customer,
)

#: همه‌ی مدل‌ها (برای سازگاری و ابزارهای عمومی).
ALL_MODELS = CENTRAL_MODELS + USER_MODELS
TABLE_MODELS = {m.TABLE: m for m in ALL_MODELS}

CENTRAL_TABLES = frozenset(m.TABLE for m in CENTRAL_MODELS)
USER_TABLES = frozenset(m.TABLE for m in USER_MODELS)

#: نامِ فیلدی که «مالکِ» هر ردیف را در جدول‌های اختصاصی مشخص می‌کند.
#: ``invoice_items`` فیلد مالک ندارد و از روی فاکتورش حل می‌شود.
OWNER_FIELD = {
    "transactions": "user_id",
    "ledger_entries": "user_id",
    "invoices": "user_id",
    "products": "user_id",
    "group_events": "chat_id",
    "customers": "user_id",
}
