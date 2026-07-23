"""سرویس کالاهای ذخیره‌شده (روی :class:`Store`)."""
from __future__ import annotations

from typing import Optional

from ..db.models import Product
from ..db.store import Store
from .transactions import get_or_create_user


async def add_product(
    store: Store, user_id: int, title: str, unit_price: int
) -> Product:
    await get_or_create_user(store, user_id)
    product = Product(user_id=user_id, title=title.strip()[:200], unit_price=int(unit_price))
    await store.add("products", product)
    return product


def list_products(store: Store, user_id: int, limit: int = 30) -> list[Product]:
    rows = store.list("products", lambda p: p.user_id == user_id)
    rows.sort(key=lambda p: p.id, reverse=True)
    return rows[:limit]


def get_product(store: Store, user_id: int, product_id: int) -> Optional[Product]:
    product = store.get("products", product_id)
    return product if product is not None and product.user_id == user_id else None


async def delete_product(
    store: Store, user_id: int, product_id: int
) -> Optional[Product]:
    product = get_product(store, user_id, product_id)
    if product is None:
        return None
    await store.delete("products", product.id)
    return product
