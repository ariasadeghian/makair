"""تست سرویس گزارش‌ها."""
import datetime as dt

import jdatetime

from hesabyar.core import jalali, money
from hesabyar.db.models import Kind
from hesabyar.services import reports, transactions

USER_ID = 777_222


def _dt(year: int, month: int, day: int, hh: int = 12, mm: int = 0) -> dt.datetime:
    """ساخت datetime aware تهران از تاریخ شمسی."""
    g = jdatetime.date(year, month, day).togregorian()
    return dt.datetime(g.year, g.month, g.day, hh, mm, tzinfo=jalali.TEHRAN)


def _seed_month(session) -> None:
    """چند تراکنش در مرداد ۱۴۰۳ می‌سازد."""
    transactions.get_or_create_user(session, USER_ID)
    transactions.add_transaction(
        session, USER_ID, kind=Kind.INCOME, amount=2_000_000,
        category="فروش کالا", description="", occurred_at=_dt(1403, 5, 3),
    )
    transactions.add_transaction(
        session, USER_ID, kind=Kind.EXPENSE, amount=600_000,
        category="قبوض", description="", occurred_at=_dt(1403, 5, 4),
    )
    transactions.add_transaction(
        session, USER_ID, kind=Kind.EXPENSE, amount=400_000,
        category="حمل و نقل", description="", occurred_at=_dt(1403, 5, 5),
    )
    transactions.add_transaction(
        session, USER_ID, kind=Kind.EXPENSE, amount=100_000,
        category="پذیرایی و خوراک", description="", occurred_at=_dt(1403, 5, 6),
    )


class TestPeriodLabel:
    def test_labels(self):
        assert reports.period_label("day") == "امروز"
        assert reports.period_label("week") == "این هفته"
        assert reports.period_label("month") == "این ماه"


class TestBuildReport:
    def test_month_report_has_title_and_amounts(self, session):
        _seed_month(session)
        base = _dt(1403, 5, 15, 18, 0)
        text = reports.build_report(session, USER_ID, base, "month")

        # عنوان دوره باید در متن باشد.
        assert reports.period_label("month") in text
        # مبالغ فرمت‌شده‌ی فارسی.
        assert money.format_amount(2_000_000) in text  # درآمد
        assert money.format_amount(1_100_000) in text  # جمع هزینه
        assert money.format_amount(900_000) in text  # مانده = ۲۰۰۰۰۰۰ - ۱۱۰۰۰۰۰

    def test_month_report_lists_top_expense_categories(self, session):
        _seed_month(session)
        base = _dt(1403, 5, 15, 18, 0)
        text = reports.build_report(session, USER_ID, base, "month")

        # بزرگ‌ترین دسته‌ی هزینه (قبوض) باید در فهرست باشد.
        assert "قبوض" in text
        assert money.format_amount(600_000) in text
        # تعداد تراکنش (۴) با ارقام فارسی.
        assert money.to_persian_digits("4") in text

    def test_empty_report(self, session):
        transactions.get_or_create_user(session, USER_ID)
        base = _dt(1403, 5, 15, 18, 0)
        text = reports.build_report(session, USER_ID, base, "month")

        assert reports.period_label("month") in text
        assert "ثبت نشده" in text

    def test_day_report_uses_day_bounds(self, session):
        transactions.get_or_create_user(session, USER_ID)
        base = _dt(1403, 5, 15, 20, 0)
        # یک تراکنش امروز و یکی روز قبل.
        transactions.add_transaction(
            session, USER_ID, kind=Kind.INCOME, amount=300_000,
            category="فروش کالا", description="", occurred_at=_dt(1403, 5, 15, 9, 0),
        )
        transactions.add_transaction(
            session, USER_ID, kind=Kind.EXPENSE, amount=50_000,
            category="قبوض", description="", occurred_at=_dt(1403, 5, 14, 9, 0),
        )
        text = reports.build_report(session, USER_ID, base, "day")
        assert reports.period_label("day") in text
        # فقط تراکنش امروز باید در جمع بیاید.
        assert money.format_amount(300_000) in text
