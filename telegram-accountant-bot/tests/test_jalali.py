import datetime as dt

import jdatetime

from hesabyar.core import jalali


def _greg(y, m, d, hh=12, mm=0):
    g = jdatetime.date(y, m, d).togregorian()
    return dt.datetime(g.year, g.month, g.day, hh, mm, tzinfo=jalali.TEHRAN)


class TestFormat:
    def test_format_date(self):
        assert jalali.format_date(_greg(1403, 5, 1)) == "۱۴۰۳/۰۵/۰۱"

    def test_format_date_long(self):
        assert jalali.format_date_long(_greg(1403, 5, 1)) == "۱ مرداد ۱۴۰۳"

    def test_format_datetime(self):
        out = jalali.format_datetime(_greg(1403, 5, 1, 14, 30))
        assert out == "۱۴۰۳/۰۵/۰۱ - ۱۴:۳۰"

    def test_month_name(self):
        assert jalali.month_name(1) == "فروردین"
        assert jalali.month_name(12) == "اسفند"


class TestRelativeDate:
    def test_today(self):
        base = _greg(1403, 5, 10)
        assert jalali.parse_relative_date("امروز خرید کردم", base) == base.date()

    def test_yesterday(self):
        base = _greg(1403, 5, 10)
        expected = base.date() - dt.timedelta(days=1)
        assert jalali.parse_relative_date("دیروز ۵۰۰ دادم", base) == expected

    def test_day_before_yesterday(self):
        base = _greg(1403, 5, 10)
        expected = base.date() - dt.timedelta(days=2)
        assert jalali.parse_relative_date("پریروز", base) == expected

    def test_explicit_jalali(self):
        base = _greg(1403, 5, 10)
        got = jalali.parse_relative_date("۱۴۰۳/۰۵/۰۱ فاکتور", base)
        assert got == jdatetime.date(1403, 5, 1).togregorian()

    def test_none(self):
        base = _greg(1403, 5, 10)
        assert jalali.parse_relative_date("خرید مواد اولیه", base) is None


class TestBounds:
    def test_month_bounds_start_is_first_day(self):
        base = _greg(1403, 5, 15)
        start, end = jalali.month_bounds(base)
        js = jalali.to_jalali(start)
        assert (js.year, js.month, js.day) == (1403, 5, 1)
        assert end == base

    def test_week_bounds_starts_saturday(self):
        base = _greg(1403, 5, 15)
        start, _ = jalali.week_bounds(base)
        assert jalali.to_jalali(start).weekday() == 0  # شنبه

    def test_day_bounds(self):
        base = _greg(1403, 5, 15, 18, 0)
        start, end = jalali.day_bounds(base)
        assert start.hour == 0 and start.minute == 0
        assert end == base
