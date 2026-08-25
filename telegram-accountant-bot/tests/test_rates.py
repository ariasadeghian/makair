"""تست‌های نرخ دلار و نمای دلاریِ درآمد."""
import datetime as dt

from hesabyar.core import jalali
from hesabyar.db.models import Kind
from hesabyar.services import rates
from hesabyar.services import transactions as tx

UID = 601


async def _tx(store, kind, amount, when):
    return await tx.add_transaction(
        store, UID, kind=kind, amount=amount, category="x",
        description="", occurred_at=when,
    )


class TestParseRateMessage:
    def test_simple_persian_post(self):
        assert rates.parse_rate_message("دلار آزاد: ۸۹٬۵۰۰ تومان") == 89_500

    def test_english_digits_and_commas(self):
        assert rates.parse_rate_message("قیمت دلار 92,300") == 92_300

    def test_rial_is_converted_to_toman(self):
        assert rates.parse_rate_message("دلار ۸۹۵٬۰۰۰ ریال") == 89_500

    def test_ignores_message_without_dollar_word(self):
        assert rates.parse_rate_message("طلا ۳٬۲۰۰٬۰۰۰ تومان") is None

    def test_ignores_out_of_range_numbers(self):
        # «۱۴۰۵» سال است، نه نرخ
        assert rates.parse_rate_message("گزارش دلار سال ۱۴۰۵") is None

    def test_picks_first_plausible_number(self):
        text = "امروز ۹ مرداد — دلار ۸۸٬۷۰۰ تومان"
        assert rates.parse_rate_message(text) == 88_700

    def test_empty(self):
        assert rates.parse_rate_message("") is None


class TestSetAndLookup:
    async def test_set_and_get(self, store):
        today = jalali.now().date()
        await rates.set_rate(store, 89_000, today)
        assert rates.rate_for(store, today) == 89_000

    async def test_same_day_updates_not_duplicates(self, store):
        today = jalali.now().date()
        await rates.set_rate(store, 89_000, today)
        await rates.set_rate(store, 90_500, today)
        assert len(store.list("rates", lambda r: True)) == 1
        assert rates.rate_for(store, today) == 90_500

    async def test_carries_forward_last_known(self, store):
        today = jalali.now().date()
        await rates.set_rate(store, 80_000, today - dt.timedelta(days=5))
        # روزی که نرخ ندارد ⇒ آخرین نرخِ پیش از آن
        assert rates.rate_for(store, today) == 80_000

    async def test_does_not_use_future_rate(self, store):
        today = jalali.now().date()
        await rates.set_rate(store, 95_000, today + dt.timedelta(days=3))
        assert rates.rate_for(store, today) is None

    async def test_latest_rate(self, store):
        today = jalali.now().date()
        await rates.set_rate(store, 80_000, today - dt.timedelta(days=2))
        await rates.set_rate(store, 91_000, today)
        assert rates.latest_rate(store).usd == 91_000

    async def test_no_rate_returns_none(self, store):
        assert rates.rate_for(store, jalali.now().date()) is None
        assert rates.latest_rate(store) is None


class TestConvertPeriod:
    async def test_uses_each_days_own_rate(self, store):
        """خرید در دلارِ ارزان و فروش در دلارِ گران باید در جمعِ دلاری دیده شود."""
        now = jalali.now()
        d1 = now - dt.timedelta(days=10)
        await rates.set_rate(store, 50_000, d1.date())
        await rates.set_rate(store, 100_000, now.date())
        await tx.get_or_create_user(store, UID)
        await _tx(store, Kind.EXPENSE, 50_000_000, d1)   # $۱۰۰۰ در آن روز
        await _tx(store, Kind.INCOME, 100_000_000, now)  # $۱۰۰۰ در امروز

        start, end = jalali.month_bounds(now)
        # اگر بازه شامل هر دو باشد
        res = rates.convert_period(store, UID, min(start, d1), end)
        assert round(res["expense_usd"]) == 1000
        assert round(res["income_usd"]) == 1000
        # تومانی دو برابر شده ولی دلاری سربه‌سر است
        assert res["balance"] == 50_000_000
        assert round(res["balance_usd"]) == 0

    async def test_counts_missing_rates(self, store):
        now = jalali.now()
        await tx.get_or_create_user(store, UID)
        await _tx(store, Kind.INCOME, 1_000_000, now)
        start, end = jalali.month_bounds(now)
        res = rates.convert_period(store, UID, start, end)
        assert res["missing"] == 1 and res["covered"] == 0
        assert res["income_usd"] == 0


class TestUsdReport:
    async def test_without_rate(self, store):
        assert "نرخ" in rates.build_usd_report(store, UID)

    async def test_flags_nominal_growth_as_not_real(self, store):
        """درآمد تومانی بالا، دلاری پایین ⇒ باید هشدار «رشدِ اسمی» بدهد."""
        now = jalali.now()
        start, _ = jalali.month_bounds(now)
        prev = start - dt.timedelta(days=1)  # ماه قبل

        await tx.get_or_create_user(store, UID)
        await rates.set_rate(store, 50_000, prev.date())
        await rates.set_rate(store, 100_000, now.date())
        await _tx(store, Kind.INCOME, 50_000_000, prev)   # $۱۰۰۰
        await _tx(store, Kind.INCOME, 60_000_000, now)    # $۶۰۰ — تومانی +۲۰٪

        report = rates.build_usd_report(store, UID, now)
        assert "رشدِ اسمی است" in report
        assert "به تومان" in report and "به دلار" in report

    async def test_real_growth_is_confirmed(self, store):
        now = jalali.now()
        start, _ = jalali.month_bounds(now)
        prev = start - dt.timedelta(days=1)

        await tx.get_or_create_user(store, UID)
        await rates.set_rate(store, 50_000, prev.date())
        await rates.set_rate(store, 55_000, now.date())
        await _tx(store, Kind.INCOME, 50_000_000, prev)    # $۱۰۰۰
        await _tx(store, Kind.INCOME, 110_000_000, now)    # $۲۰۰۰
        report = rates.build_usd_report(store, UID, now)
        assert "رشدت واقعی است" in report

    async def test_empty_month(self, store):
        now = jalali.now()
        await rates.set_rate(store, 89_000, now.date())
        assert "تراکنشی ثبت نشده" in rates.build_usd_report(store, UID, now)
