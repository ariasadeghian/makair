"""سرویس کالاهای ذخیره‌شده (برای ساخت سریع فاکتور)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .transactions import get_or_create_user
from ..db.models import Product


def add_product(
    session: Session, user_id: int, title: str, unit_price: int
) -> Product:
    """یک کالا با قیمت پیش‌فرض ذخیره می‌کند."""
    get_or_create_user(session, user_id)
    product = Product(user_id=user_id, title=title.strip()[:200], unit_price=int(unit_price))
    session.add(product)
    session.commit()
    return product


def list_products(session: Session, user_id: int, limit: int = 30) -> list[Product]:
    """فهرست کالاهای کاربر (جدیدترین‌ها اول)."""
    stmt = (
        select(Product)
        .where(Product.user_id == user_id)
        .order_by(Product.id.desc())
        .limit(limit)
    )
    return list(session.execute(stmt).scalars().all())


def get_product(session: Session, user_id: int, product_id: int) -> Product | None:
    product = session.get(Product, product_id)
    return product if product is not None and product.user_id == user_id else None


def delete_product(session: Session, user_id: int, product_id: int) -> Product | None:
    product = get_product(session, user_id, product_id)
    if product is None:
        return None
    session.delete(product)
    session.commit()
    return product
