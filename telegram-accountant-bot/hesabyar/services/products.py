"""سرویس کالاهای ذخیره‌شده (روی :class:`Store`)."""
from __future__ import annotations

from typing import Optional

from ..db.models import Product
from ..db.store import Store
from .transactions import get_or_create_user


async def add_product(
    store: Store, user_id: int, title: str, unit_price: int, category: str = ""
) -> Product:
    await get_or_create_user(store, user_id)
    product = Product(
        user_id=user_id, title=title.strip()[:200], unit_price=int(unit_price),
        category=(category or "").strip()[:100],
    )
    await store.add("products", product)
    return product


def used_categories(store: Store, user_id: int) -> list[str]:
    """دسته‌هایی که همین کاربر قبلاً استفاده کرده — پرکاربردترین اول."""
    counts: dict[str, int] = {}
    for product in store.list("products", lambda p: p.user_id == user_id):
        name = (product.category or "").strip()
        if name:
            counts[name] = counts.get(name, 0) + 1
    return sorted(counts, key=lambda name: (-counts[name], name))


def by_category(store: Store, user_id: int) -> dict[str, list[Product]]:
    """کالاهای کاربر، گروه‌شده بر اساس دسته (دسته‌ی خالی آخر می‌آید)."""
    grouped: dict[str, list[Product]] = {}
    for product in sorted(list_products(store, user_id, limit=1000),
                          key=lambda p: p.title):
        grouped.setdefault((product.category or "").strip(), []).append(product)
    ordered = {name: items for name, items in sorted(grouped.items()) if name}
    if "" in grouped:
        ordered[""] = grouped[""]
    return ordered


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
