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


class PaymentStatus:
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ALL = (PENDING, APPROVED, REJECTED)


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
    COLUMNS = ("id", "business_name", "phone", "address", "currency", "created_at")

    id: Optional[int] = None
    business_name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    currency: str = "تومان"
    created_at: Optional[dt.datetime] = None

    def to_row(self) -> list:
        return [
            _s(self.id), _s(self.business_name), _s(self.phone),
            _s(self.address), _s(self.currency), _s(self.created_at),
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
        )


@dataclass
class Transaction:
    TABLE = "transactions"
    COLUMNS = (
        "id", "user_id", "kind", "amount", "category",
        "description", "occurred_at", "created_at",
    )

    id: Optional[int] = None
    user_id: int = 0
    kind: str = Kind.EXPENSE
    amount: int = 0
    category: str = "متفرقه"
    description: str = ""
    occurred_at: Optional[dt.datetime] = None
    created_at: Optional[dt.datetime] = None

    def to_row(self) -> list:
        return [
            _s(self.id), _s(self.user_id), _s(self.kind), _s(self.amount),
            _s(self.category), _s(self.description), _s(self.occurred_at),
            _s(self.created_at),
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
        )


@dataclass
class LedgerEntry:
    TABLE = "ledger_entries"
    COLUMNS = (
        "id", "user_id", "direction", "party_name", "amount",
        "description", "due_date", "is_settled", "settled_at", "created_at",
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

    def to_row(self) -> list:
        return [
            _s(self.id), _s(self.user_id), _s(self.direction), _s(self.party_name),
            _s(self.amount), _s(self.description), _s(self.due_date),
            _s(self.is_settled), _s(self.settled_at), _s(self.created_at),
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
        "created_at",
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
    COLUMNS = ("id", "user_id", "title", "unit_price", "created_at")

    id: Optional[int] = None
    user_id: int = 0
    title: str = ""
    unit_price: int = 0
    created_at: Optional[dt.datetime] = None

    def to_row(self) -> list:
        return [
            _s(self.id), _s(self.user_id), _s(self.title),
            _s(self.unit_price), _s(self.created_at),
        ]

    @classmethod
    def from_row(cls, d: dict) -> "Product":
        return cls(
            id=_pint(d.get("id")),
            user_id=_pint(d.get("user_id")) or 0,
            title=_pstr(d.get("title")),
            unit_price=_pint(d.get("unit_price")) or 0,
            created_at=_pdt(d.get("created_at")),
        )


#: همه‌ی مدل‌ها به ترتیب تب‌ها (برای ساخت تب‌ها و بارگذاری).
ALL_MODELS = (
    User, Transaction, LedgerEntry, Invoice, InvoiceItem,
    Subscription, Payment, Product,
)
TABLE_MODELS = {m.TABLE: m for m in ALL_MODELS}
