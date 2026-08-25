"""تست سرویس گزارش‌ها."""
import datetime as dt

import jdatetime

from hesabyar.core import jalali, money
from hesabyar.db.models import Direction, Kind
from hesabyar.services import ledger, reports, transactions

USER_ID = 777_222


def _dt(year: int, month: int, day: int, hh: int = 12, mm: int = 0) -> dt.datetime:
    """ساخت datetime aware تهران از تاریخ شمسی."""
    g = jdatetime.date(year, month, day).togregorian()
    return dt.datetime(g.year, g.month, g.day, hh, mm, tzinfo=jalali.TEHRAN)


def _date(year: int, month: int, day: int) -> dt.date:
    return jdatetime.date(year, month, day).togregorian()


async def _seed_month(store) -> None:
    """چند تراکنش در مرداد ۱۴۰۳ می‌سازد."""
    await transactions.get_or_create_user(store, USER_ID)
    await transactions.add_transaction(
        store, USER_ID, kind=Kind.INCOME, amount=2_000_000,
        category="فروش کالا", description="", occurred_at=_dt(1403, 5, 3),
    )
    await transactions.add_transaction(
        store, USER_ID, kind=Kind.EXPENSE, amount=600_000,
        category="قبوض", description="", occurred_at=_dt(1403, 5, 4),
    )
    await transactions.add_transaction(
        store, USER_ID, kind=Kind.EXPENSE, amount=400_000,
        category="حمل و نقل", description="", occurred_at=_dt(1403, 5, 5),
    )
    await transactions.add_transaction(
        store, USER_ID, kind=Kind.EXPENSE, amount=100_000,
        category="پذیرایی و خوراک", description="", occurred_at=_dt(1403, 5, 6),
    )


class TestPeriodLabel:
    def test_labels(self):
        assert reports.period_label("day") == "امروز"
        assert reports.period_label("week") == "این هفته"
        assert reports.period_label("month") == "این ماه"


class TestBuildReport:
    async def test_month_report_has_title_and_amounts(self, store):
        await _seed_month(store)
        base = _dt(1403, 5, 15, 18, 0)
        text = reports.build_report(store, USER_ID, base, "month")

        # عنوان دوره باید در متن باشد.
        assert reports.period_label("month") in text
        # مبالغ فرمت‌شده‌ی فارسی.
        assert money.format_amount(2_000_000) in text  # درآمد
        assert money.format_amount(1_100_000) in text  # جمع هزینه
        assert money.format_amount(900_000) in text  # مانده = ۲۰۰۰۰۰۰ - ۱۱۰۰۰۰۰

    async def test_month_report_lists_top_expense_categories(self, store):
        await _seed_month(store)
        base = _dt(1403, 5, 15, 18, 0)
        text = reports.build_report(store, USER_ID, base, "month")

        # بزرگ‌ترین دسته‌ی هزینه (قبوض) باید در فهرست باشد.
        assert "قبوض" in text
        assert money.format_amount(600_000) in text
        # تعداد تراکنش (۴) با ارقام فارسی.
        assert money.to_persian_digits("4") in text


class TestBusinessSnapshot:
    async def test_brand_new_user_gets_a_nudge_not_zeros(self, store):
        await transactions.get_or_create_user(store, USER_ID)
        text = reports.build_business_snapshot(store, USER_ID, _dt(1403, 5, 15))
        assert "هنوز چیزی ثبت نکرده‌ای" in text
        assert money.format_amount(0) not in text

    async def test_shows_today_and_month_numbers(self, store):
        await _seed_month(store)
        base = _dt(1403, 5, 15, 18, 0)
        text = reports.build_business_snapshot(store, USER_ID, base)
        assert "امروز" in text and "این ماه" in text
        # جمع درآمدِ ماه (فقط یک تراکنشِ درآمد در _seed_month).
        assert money.format_amount(2_000_000) in text
        # مانده‌ی تقریبیِ ماه = ۲۰۰۰۰۰۰ - ۱۱۰۰۰۰۰.
        assert money.format_amount(900_000) in text
        # بزرگ‌ترین دسته‌ی هزینه.
        assert "قبوض" in text

    async def test_counts_distinct_debtors_not_entries(self, store):
        await _seed_month(store)
        base = _dt(1403, 5, 15, 18, 0)
        # دو ردیفِ طلب از «رضا» — باید یک نفر شمرده شود، نه دو.
        await ledger.add_entry(
            store, USER_ID, direction=Direction.RECEIVABLE,
            party_name="رضا", amount=1_000_000, due_date=_date(1403, 5, 20),
        )
        await ledger.add_entry(
            store, USER_ID, direction=Direction.RECEIVABLE,
            party_name="رضا", amount=500_000, due_date=_date(1403, 5, 25),
        )
        await ledger.add_entry(
            store, USER_ID, direction=Direction.RECEIVABLE,
            party_name="سارا", amount=300_000, due_date=_date(1403, 5, 25),
        )
        text = reports.build_business_snapshot(store, USER_ID, base)
        assert "۲ نفر به شما بدهکار هستند" in text
        assert money.format_amount(1_800_000) in text  # جمعِ کل سه ردیف

    async def test_flags_overdue_payments(self, store):
        await _seed_month(store)
        base = _dt(1403, 5, 15, 18, 0)
        await ledger.add_entry(
            store, USER_ID, direction=Direction.RECEIVABLE,
            party_name="رضا", amount=1_000_000, due_date=_date(1403, 5, 10),
        )
        text = reports.build_business_snapshot(store, USER_ID, base)
        assert "معوق" in text

    async def test_no_alerts_section_when_nothing_to_flag(self, store):
        # فقط یک تراکنشِ درآمد — بدون هزینه، بدون طلبِ باز، بدون معوقه.
        await transactions.get_or_create_user(store, USER_ID)
        await transactions.add_transaction(
            store, USER_ID, kind=Kind.INCOME, amount=2_000_000,
            category="فروش کالا", description="", occurred_at=_dt(1403, 5, 3),
        )
        base = _dt(1403, 5, 15, 18, 0)
        text = reports.build_business_snapshot(store, USER_ID, base)
        assert "نکته‌های مهم" not in text

    async def test_empty_report(self, store):
        await transactions.get_or_create_user(store, USER_ID)
        base = _dt(1403, 5, 15, 18, 0)
        text = reports.build_report(store, USER_ID, base, "month")

        assert reports.period_label("month") in text
        assert "ثبت نشده" in text

    async def test_day_report_uses_day_bounds(self, store):
        await transactions.get_or_create_user(store, USER_ID)
        base = _dt(1403, 5, 15, 20, 0)
        # یک تراکنش امروز و یکی روز قبل.
        await transactions.add_transaction(
            store, USER_ID, kind=Kind.INCOME, amount=300_000,
            category="فروش کالا", description="", occurred_at=_dt(1403, 5, 15, 9, 0),
        )
        await transactions.add_transaction(
            store, USER_ID, kind=Kind.EXPENSE, amount=50_000,
            category="قبوض", description="", occurred_at=_dt(1403, 5, 14, 9, 0),
        )
        text = reports.build_report(store, USER_ID, base, "day")
        assert reports.period_label("day") in text
        # فقط تراکنش امروز باید در جمع بیاید.
        assert money.format_amount(300_000) in text
