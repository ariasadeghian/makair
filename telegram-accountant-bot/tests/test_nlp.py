"""تست‌های ماژول :mod:`hesabyar.core.nlp`."""
import datetime as dt

from hesabyar.core import jalali, nlp
from hesabyar.db.models import Kind

# زمان مبنای ثابت برای قطعی‌بودن تست‌های تاریخ (aware، تهران).
BASE = dt.datetime(2024, 7, 23, 14, 30, tzinfo=jalali.TEHRAN)


class TestKindAndAmount:
    def test_expense_buy_materials(self):
        parsed = nlp.parse_transaction(
            "دیروز ۵۰۰ هزار بابت خرید مواد اولیه دادم", base=BASE
        )
        assert parsed is not None
        assert parsed.kind == Kind.EXPENSE
        assert parsed.amount == 500_000
        assert parsed.category == "خرید کالا و مواد اولیه"

    def test_income_sale(self):
        parsed = nlp.parse_transaction("امروز ۲ میلیون فروختم", base=BASE)
        assert parsed is not None
        assert parsed.kind == Kind.INCOME
        assert parsed.amount == 2_000_000
        assert parsed.category == "فروش کالا"

    def test_expense_utility_bill(self):
        parsed = nlp.parse_transaction("قبض برق ۳۰۰ هزار پرداختم", base=BASE)
        assert parsed is not None
        assert parsed.kind == Kind.EXPENSE
        assert parsed.amount == 300_000
        assert parsed.category == "قبوض"

    def test_income_received_payment(self):
        parsed = nlp.parse_transaction(
            "یک میلیون و پانصد هزار تومان از مشتری گرفتم", base=BASE
        )
        assert parsed is not None
        assert parsed.kind == Kind.INCOME
        assert parsed.amount == 1_500_000

    def test_income_deposit(self):
        parsed = nlp.parse_transaction("۸۰۰ هزار تومان به حسابم واریز شد", base=BASE)
        assert parsed is not None
        assert parsed.kind == Kind.INCOME
        assert parsed.amount == 800_000

    def test_ambiguous_defaults_to_expense(self):
        # بدون هیچ کلیدواژه‌ی نوع → پیش‌فرض هزینه
        parsed = nlp.parse_transaction("۵۰ هزار تومان", base=BASE)
        assert parsed is not None
        assert parsed.kind == Kind.EXPENSE
        assert parsed.amount == 50_000

    def test_rial_converted_to_toman(self):
        parsed = nlp.parse_transaction("۵۰۰۰ ریال خرج کردم", base=BASE)
        assert parsed is not None
        assert parsed.kind == Kind.EXPENSE
        assert parsed.amount == 500


class TestNoAmount:
    def test_no_amount_returns_none(self):
        assert nlp.parse_transaction("یه چیزی خریدم", base=BASE) is None

    def test_empty_returns_none(self):
        assert nlp.parse_transaction("", base=BASE) is None

    def test_whitespace_returns_none(self):
        assert nlp.parse_transaction("   ", base=BASE) is None


class TestOccurredAt:
    def test_today_uses_base_date(self):
        parsed = nlp.parse_transaction("امروز ۲ میلیون فروختم", base=BASE)
        assert parsed is not None
        assert parsed.occurred_at.date() == BASE.date()
        # ساعت از base گرفته می‌شود
        assert parsed.occurred_at.hour == 14
        assert parsed.occurred_at.minute == 30

    def test_yesterday_shifts_one_day(self):
        parsed = nlp.parse_transaction(
            "دیروز ۵۰۰ هزار بابت خرید مواد اولیه دادم", base=BASE
        )
        assert parsed is not None
        assert parsed.occurred_at.date() == (BASE - dt.timedelta(days=1)).date()

    def test_occurred_at_is_timezone_aware(self):
        parsed = nlp.parse_transaction("۵۰ هزار تومان", base=BASE)
        assert parsed is not None
        assert parsed.occurred_at.tzinfo is not None
        # همان افست تهران (+03:30)
        assert parsed.occurred_at.utcoffset() == dt.timedelta(hours=3, minutes=30)

    def test_default_base_is_now_and_aware(self):
        parsed = nlp.parse_transaction("۵۰ هزار تومان")
        assert parsed is not None
        assert parsed.occurred_at.tzinfo is not None


class TestDescriptionAndRaw:
    def test_description_strips_amount_and_date(self):
        raw = "دیروز ۵۰۰ هزار بابت خرید مواد اولیه دادم"
        parsed = nlp.parse_transaction(raw, base=BASE)
        assert parsed is not None
        # متن خام دست‌نخورده می‌ماند
        assert parsed.raw == raw
        # شرح نباید مبلغ، واحد یا واژه‌ی تاریخ داشته باشد
        assert "۵۰۰" not in parsed.description
        assert "هزار" not in parsed.description
        assert "دیروز" not in parsed.description
        # ولی هسته‌ی معنایی حفظ می‌شود
        assert "مواد اولیه" in parsed.description
