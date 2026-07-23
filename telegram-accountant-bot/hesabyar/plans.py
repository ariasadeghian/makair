"""پلن‌های اشتراک و مدت آزمایش.

قیمت‌ها به «تومان» و قابل‌تنظیم‌اند. مدل قیمت‌گذاری بر اساس همان بازار
هدف (کسب‌وکارهای خرد ایرانی): ماهی حدود ۲۰۰ هزار تومان با تخفیف برای
دوره‌های بلندتر.
"""
from __future__ import annotations

#: مدت دوره‌ی آزمایشی رایگان (روز)
TRIAL_DAYS = 14

#: کلید هر پلن به مشخصاتش
PLANS: dict[str, dict] = {
    "monthly": {"label": "یک‌ماهه", "days": 30, "price": 200_000},
    "quarterly": {"label": "سه‌ماهه", "days": 90, "price": 500_000},
    "yearly": {"label": "یک‌ساله", "days": 365, "price": 1_800_000},
}

#: ترتیب نمایش پلن‌ها
PLAN_ORDER = ["monthly", "quarterly", "yearly"]


def get_plan(key: str) -> dict | None:
    """مشخصات یک پلن را برمی‌گرداند (یا ``None`` اگر نامعتبر باشد)."""
    return PLANS.get(key)
