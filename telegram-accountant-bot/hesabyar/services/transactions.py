"""سرویس تراکنش‌های درآمد و هزینه (روی :class:`Store`).

خواندن‌ها همگام (sync، از حافظه) و نوشتن‌ها async (صف‌شونده روی شیت)‌اند.
همه‌ی مبالغ عدد صحیح و به «تومان»؛ زمان‌ها aware (منطقه‌ی تهران).
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from ..core import jalali
from ..db.models import Kind, Transaction, User
from ..db.store import Store


async def get_or_create_user(
    store: Store, user_id: int, business_name: str | None = None
) -> User:
    """کاربر را برمی‌گرداند و اگر نبود می‌سازد.

    این تابع نقطه‌ی ورودِ تقریباً همه‌ی هندلرهاست، پس همین‌جا مطمئن می‌شویم
    اسپردشیت اختصاصیِ کاربر وجود دارد و دفترش در حافظه بارگذاری شده است.
    """
    user = store.get("users", user_id)
    if user is None:
        user = User(id=user_id, business_name=business_name)
        await store.add("users", user)
    elif business_name and not user.business_name:
        user.business_name = business_name
        await store.update("users", user)

    # دفترِ اختصاصیِ کاربر: بساز اگر نیست، بخوان اگر هنوز در حافظه نیامده.
    if not user.sheet_id:
        await store.ensure_user_spreadsheet(user_id, business_name or "")
    else:
        await store.load_user(user_id)
    return user


async def add_transaction(
    store: Store,
    user_id: int,
    *,
    kind: str,
    amount: int,
    category: str,
    description: str,
    occurred_at: dt.datetime,
    branch_id: int = 0,
    logged_by: int | None = None,
) -> Transaction:
    """یک تراکنش تازه ثبت می‌کند و شیء ذخیره‌شده را برمی‌گرداند.

    ``branch_id``/``logged_by`` وقتی پر می‌شوند که کارمندِ یک شعبه ثبت کرده
    باشد؛ تراکنش در دفترِ ``user_id`` (صاحب کسب‌وکار) می‌نشیند.
    """
    owner = await get_or_create_user(store, user_id)
    tx = Transaction(
        user_id=user_id, kind=kind, amount=int(amount), category=category,
        description=description, occurred_at=occurred_at,
        branch_id=int(branch_id or 0), logged_by=logged_by,
    )
    await store.add("transactions", tx)
    if owner.first_transaction_at is None:
        owner.first_transaction_at = tx.created_at
        await store.update("users", owner)
    return tx


def list_transactions(
    store: Store,
    user_id: int,
    start: dt.datetime,
    end: dt.datetime,
    kind: str | None = None,
) -> list[Transaction]:
    """تراکنش‌های کاربر در بازه‌ی ``[start, end]`` (هر دو سرشامل)، صعودی."""

    def _match(t: Transaction) -> bool:
        if t.user_id != user_id or t.occurred_at is None:
            return False
        if not (start <= t.occurred_at <= end):
            return False
        return kind is None or t.kind == kind

    rows = store.list("transactions", _match)
    return sorted(rows, key=lambda t: (t.occurred_at, t.id))


def summary(store: Store, user_id: int, start: dt.datetime, end: dt.datetime) -> dict:
    """خلاصه‌ی درآمد/هزینه در یک بازه."""
    txs = list_transactions(store, user_id, start, end)
    income = expense = 0
    income_by: dict[str, int] = {}
    expense_by: dict[str, int] = {}
    for tx in txs:
        amount = int(tx.amount)
        if tx.kind == Kind.INCOME:
            income += amount
            income_by[tx.category] = income_by.get(tx.category, 0) + amount
        else:
            expense += amount
            expense_by[tx.category] = expense_by.get(tx.category, 0) + amount
    return {
        "income": income, "expense": expense, "balance": income - expense,
        "count": len(txs), "expense_by_category": expense_by,
        "income_by_category": income_by,
    }


async def delete_last(store: Store, user_id: int) -> Optional[Transaction]:
    """آخرین تراکنش کاربر (بیشترین id) را حذف می‌کند."""
    rows = store.list("transactions", lambda t: t.user_id == user_id)
    if not rows:
        return None
    tx = max(rows, key=lambda t: t.id)
    await store.delete("transactions", tx.id)
    return tx


def get_transaction(
    store: Store, user_id: int, transaction_id: int
) -> Optional[Transaction]:
    tx = store.get("transactions", transaction_id)
    return tx if tx is not None and tx.user_id == user_id else None


async def delete_transaction(
    store: Store, user_id: int, transaction_id: int
) -> Optional[Transaction]:
    tx = get_transaction(store, user_id, transaction_id)
    if tx is None:
        return None
    await store.delete("transactions", tx.id)
    return tx


async def update_transaction(
    store: Store,
    user_id: int,
    transaction_id: int,
    *,
    amount: int | None = None,
    category: str | None = None,
    description: str | None = None,
    kind: str | None = None,
) -> Optional[Transaction]:
    tx = get_transaction(store, user_id, transaction_id)
    if tx is None:
        return None
    if amount is not None:
        tx.amount = int(amount)
    if category is not None:
        tx.category = category
    if description is not None:
        tx.description = description
    if kind is not None:
        tx.kind = kind
    await store.update("transactions", tx)
    return tx


def _recency_key(t: Transaction):
    return (t.occurred_at or t.created_at or jalali.now(), t.id)


def recent(store: Store, user_id: int, limit: int = 10) -> list[Transaction]:
    rows = store.list("transactions", lambda t: t.user_id == user_id)
    rows.sort(key=_recency_key, reverse=True)
    return rows[:limit]


def search_transactions(
    store: Store, user_id: int, query: str, limit: int = 15
) -> list[Transaction]:
    q = (query or "").strip()
    if not q:
        return []
    rows = store.list(
        "transactions",
        lambda t: t.user_id == user_id
        and (q in (t.description or "") or q in (t.category or "")),
    )
    rows.sort(key=_recency_key, reverse=True)
    return rows[:limit]
