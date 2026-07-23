"""مدل‌های دیتابیس (SQLAlchemy 2.0).

طرح داده‌ای ساده و سبک برای یک کسب‌وکار خرد:

* :class:`User` — هر کاربر تلگرام یک کسب‌وکار است.
* :class:`Transaction` — ثبت درآمد/هزینه.
* :class:`LedgerEntry` — دفتر بدهکار/بستانکار (طلب و بدهی).
* :class:`Invoice` و :class:`InvoiceItem` — فاکتور فروش.

همه‌ی مبالغ به «تومان» و به‌صورت عدد صحیح ذخیره می‌شوند.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """کلاس پایه‌ی مدل‌ها."""


# --- ثابت‌ها -----------------------------------------------------------------


class Kind:
    """نوع تراکنش."""

    INCOME = "income"  # درآمد
    EXPENSE = "expense"  # هزینه

    ALL = (INCOME, EXPENSE)


class Direction:
    """جهت ردیف دفتر بدهکار/بستانکار."""

    RECEIVABLE = "receivable"  # طلب من از دیگران (دیگران به من بدهکارند)
    PAYABLE = "payable"  # بدهی من به دیگران (من به دیگران بدهکارم)

    ALL = (RECEIVABLE, PAYABLE)


# --- مدل‌ها -------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    #: شناسه‌ی عددی کاربر در تلگرام (کلید اصلی، بدون افزایش خودکار)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    business_name: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(50))
    address: Mapped[str | None] = mapped_column(String(400))
    currency: Mapped[str] = mapped_column(String(20), default="تومان")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    ledger_entries: Mapped[list["LedgerEntry"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    invoices: Mapped[list["Invoice"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(10))  # Kind.INCOME / Kind.EXPENSE
    amount: Mapped[int] = mapped_column(BigInteger)  # تومان، مثبت
    category: Mapped[str] = mapped_column(String(60), default="متفرقه")
    description: Mapped[str] = mapped_column(String(400), default="")
    occurred_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="transactions")


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    direction: Mapped[str] = mapped_column(String(12))  # Direction.*
    party_name: Mapped[str] = mapped_column(String(200))  # طرف‌حساب
    amount: Mapped[int] = mapped_column(BigInteger)  # تومان، مثبت
    description: Mapped[str] = mapped_column(String(400), default="")
    due_date: Mapped[dt.date | None] = mapped_column(Date)
    is_settled: Mapped[bool] = mapped_column(Boolean, default=False)
    settled_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="ledger_entries")


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    #: شماره‌ی نمایشی فاکتور، مثلاً «۱۴۰۳-۰۰۰۱»
    number: Mapped[str] = mapped_column(String(30))
    #: دنباله‌ی عددی برای هر کاربر (برای یکتایی و مرتب‌سازی)
    seq: Mapped[int] = mapped_column(Integer)
    customer_name: Mapped[str] = mapped_column(String(200))
    customer_phone: Mapped[str] = mapped_column(String(50), default="")
    customer_address: Mapped[str] = mapped_column(String(400), default="")
    issue_date: Mapped[dt.date] = mapped_column(Date)
    note: Mapped[str] = mapped_column(String(400), default="")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="invoices")
    items: Mapped[list["InvoiceItem"]] = relationship(
        back_populates="invoice",
        cascade="all, delete-orphan",
        order_by="InvoiceItem.id",
    )

    @property
    def total(self) -> int:
        """جمع کل فاکتور به تومان."""
        return sum(item.line_total for item in self.items)


class PaymentStatus:
    """وضعیت پرداخت اشتراک."""

    PENDING = "pending"  # در انتظار تأیید مدیر
    APPROVED = "approved"  # تأییدشده
    REJECTED = "rejected"  # ردشده

    ALL = (PENDING, APPROVED, REJECTED)


class Subscription(Base):
    """اشتراک هر کاربر (هر کاربر یک ردیف)."""

    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    plan: Mapped[str] = mapped_column(String(20), default="trial")
    is_trial: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Payment(Base):
    """درخواست پرداخت اشتراک (کارت‌به‌کارت)."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    plan: Mapped[str] = mapped_column(String(20))
    amount: Mapped[int] = mapped_column(BigInteger)  # تومان
    status: Mapped[str] = mapped_column(String(12), default=PaymentStatus.PENDING)
    #: کد پیگیری یا توضیح واریز که کاربر می‌فرستد
    reference: Mapped[str] = mapped_column(String(200), default="")
    #: شناسه‌ی عکس رسید در تلگرام (در صورت ارسال عکس)
    receipt_file_id: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger)


class InvoiceItem(Base):
    __tablename__ = "invoice_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[int] = mapped_column(BigInteger)  # تومان

    invoice: Mapped["Invoice"] = relationship(back_populates="items")

    @property
    def line_total(self) -> int:
        return int(self.quantity) * int(self.unit_price)
