"""سرویس مدیریت تراکنش‌های درآمد و هزینه.

این ماژول لایه‌ی منطق تجاریِ ثبت، فهرست‌گیری، خلاصه‌گیری و حذف تراکنش‌هاست.
همه‌ی مبالغ عدد صحیح و به «تومان» هستند و زمان‌ها aware (منطقه‌ی تهران).
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Transaction, User


def get_or_create_user(
    session: Session, user_id: int, business_name: str | None = None
) -> User:
    """کاربر را برمی‌گرداند و اگر نبود می‌سازد.

    چون :class:`Transaction` کلید خارجی به کاربر دارد، پیش از ثبت هر تراکنش
    باید کاربر وجود داشته باشد. ``user_id`` همان شناسه‌ی عددی تلگرام است.
    """
    user = session.get(User, user_id)
    if user is None:
        user = User(id=user_id, business_name=business_name)
        session.add(user)
        session.commit()
    elif business_name and not user.business_name:
        # نام کسب‌وکار تازه رسیده؛ اگر قبلاً خالی بود، پرش کن.
        user.business_name = business_name
        session.commit()
    return user


def add_transaction(
    session: Session,
    user_id: int,
    *,
    kind: str,
    amount: int,
    category: str,
    description: str,
    occurred_at: dt.datetime,
) -> Transaction:
    """یک تراکنش تازه ثبت می‌کند و شیء ذخیره‌شده را برمی‌گرداند.

    ``kind`` باید یکی از مقادیر :class:`~hesabyar.db.models.Kind` باشد،
    ``amount`` مبلغ مثبت به تومان و ``occurred_at`` زمان aware رخداد است.
    """
    # اطمینان از وجود کاربر برای رعایت کلید خارجی.
    get_or_create_user(session, user_id)
    tx = Transaction(
        user_id=user_id,
        kind=kind,
        amount=int(amount),
        category=category,
        description=description,
        occurred_at=occurred_at,
    )
    session.add(tx)
    session.commit()
    return tx


def list_transactions(
    session: Session,
    user_id: int,
    start: dt.datetime,
    end: dt.datetime,
    kind: str | None = None,
) -> list[Transaction]:
    """فهرست تراکنش‌های کاربر در بازه‌ی ``[start, end]`` (هر دو سرشامل).

    اگر ``kind`` داده شود فقط تراکنش‌های همان نوع برمی‌گردند. خروجی بر
    اساس ``occurred_at`` (و برای پایداری، ``id``) صعودی مرتب است.
    """
    stmt = (
        select(Transaction)
        .where(Transaction.user_id == user_id)
        .where(Transaction.occurred_at >= start)
        .where(Transaction.occurred_at <= end)
    )
    if kind is not None:
        stmt = stmt.where(Transaction.kind == kind)
    stmt = stmt.order_by(Transaction.occurred_at.asc(), Transaction.id.asc())
    return list(session.execute(stmt).scalars().all())


def summary(
    session: Session, user_id: int, start: dt.datetime, end: dt.datetime
) -> dict:
    """خلاصه‌ی درآمد و هزینه‌ی کاربر در یک بازه.

    ساختار خروجی::

        {
            'income': int,                     # جمع درآمد
            'expense': int,                    # جمع هزینه
            'balance': int,                    # درآمد منهای هزینه
            'count': int,                      # تعداد کل تراکنش‌ها
            'expense_by_category': dict[str, int],
            'income_by_category': dict[str, int],
        }
    """
    from ..db.models import Kind  # واردسازی محلی برای پرهیز از وابستگی چرخه‌ای

    txs = list_transactions(session, user_id, start, end)
    income = 0
    expense = 0
    income_by_category: dict[str, int] = {}
    expense_by_category: dict[str, int] = {}
    for tx in txs:
        amount = int(tx.amount)
        if tx.kind == Kind.INCOME:
            income += amount
            income_by_category[tx.category] = (
                income_by_category.get(tx.category, 0) + amount
            )
        else:
            expense += amount
            expense_by_category[tx.category] = (
                expense_by_category.get(tx.category, 0) + amount
            )
    return {
        "income": income,
        "expense": expense,
        "balance": income - expense,
        "count": len(txs),
        "expense_by_category": expense_by_category,
        "income_by_category": income_by_category,
    }


def delete_last(session: Session, user_id: int) -> Transaction | None:
    """آخرین تراکنش ثبت‌شده‌ی کاربر (بر اساس ``id``) را حذف می‌کند.

    شیء حذف‌شده را برمی‌گرداند تا بتوان برای کاربر بازتاب داد؛ اگر
    تراکنشی نبود ``None``.
    """
    stmt = (
        select(Transaction)
        .where(Transaction.user_id == user_id)
        .order_by(Transaction.id.desc())
        .limit(1)
    )
    tx = session.execute(stmt).scalars().first()
    if tx is None:
        return None
    session.delete(tx)
    session.commit()
    return tx
