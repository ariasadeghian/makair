"""تست سرویس دفتر بدهکار/بستانکار (ledger)."""
import datetime as dt

import jdatetime

from hesabyar.core import jalali
from hesabyar.db.models import Direction, LedgerEntry
from hesabyar.services import ledger, transactions

USER_ID = 777_222
OTHER_USER_ID = 888_333


def _date(year: int, month: int, day: int) -> dt.date:
    """ساخت یک datetime.date میلادی از تاریخ شمسی."""
    return jdatetime.date(year, month, day).togregorian()


def _dt(year: int, month: int, day: int, hh: int = 12, mm: int = 0) -> dt.datetime:
    """ساخت datetime aware تهران از تاریخ شمسی."""
    g = jdatetime.date(year, month, day).togregorian()
    return dt.datetime(g.year, g.month, g.day, hh, mm, tzinfo=jalali.TEHRAN)


class TestAddEntry:
    def test_creates_user_and_persists(self, session):
        entry = ledger.add_entry(
            session,
            USER_ID,
            direction=Direction.RECEIVABLE,
            party_name="آقای رضایی",
            amount=1_500_000,
            due_date=_date(1403, 5, 10),
            description="بابت فروش",
        )
        assert isinstance(entry, LedgerEntry)
        assert entry.id is not None
        assert entry.amount == 1_500_000
        assert entry.direction == Direction.RECEIVABLE
        assert entry.is_settled is False
        assert entry.settled_at is None
        # کاربر باید به‌صورت خودکار ساخته شده باشد (کلید خارجی).
        from hesabyar.db.models import User

        assert session.get(User, USER_ID) is not None

    def test_add_without_due_date(self, session):
        entry = ledger.add_entry(
            session,
            USER_ID,
            direction=Direction.PAYABLE,
            party_name="فروشگاه مرکزی",
            amount=800_000,
        )
        assert entry.due_date is None
        assert entry.description == ""


class TestTotals:
    def _seed(self, session):
        transactions.get_or_create_user(session, USER_ID)
        ledger.add_entry(
            session, USER_ID, direction=Direction.RECEIVABLE,
            party_name="مشتری الف", amount=1_000_000, due_date=_date(1403, 5, 5),
        )
        ledger.add_entry(
            session, USER_ID, direction=Direction.RECEIVABLE,
            party_name="مشتری ب", amount=500_000, due_date=_date(1403, 5, 20),
        )
        ledger.add_entry(
            session, USER_ID, direction=Direction.PAYABLE,
            party_name="تامین‌کننده", amount=300_000, due_date=_date(1403, 5, 12),
        )
        ledger.add_entry(
            session, USER_ID, direction=Direction.PAYABLE,
            party_name="اجاره", amount=200_000,  # بدون سررسید
        )

    def test_totals_of_open_entries(self, session):
        self._seed(session)
        t = ledger.totals(session, USER_ID)
        assert t["receivable"] == 1_500_000
        assert t["payable"] == 500_000
        assert t["net"] == 1_000_000

    def test_settled_entries_excluded_from_totals(self, session):
        self._seed(session)
        # یک ردیف طلب را تسویه کن؛ باید از جمع کنار برود.
        open_receivables = ledger.list_open(
            session, USER_ID, direction=Direction.RECEIVABLE
        )
        target = open_receivables[0]
        ledger.settle(session, target.id, USER_ID, _dt(1403, 5, 6))
        t = ledger.totals(session, USER_ID)
        assert t["receivable"] == 1_500_000 - target.amount


class TestListOpen:
    def _seed(self, session):
        transactions.get_or_create_user(session, USER_ID)
        ledger.add_entry(
            session, USER_ID, direction=Direction.PAYABLE,
            party_name="بدون سررسید", amount=100, due_date=None,
        )
        ledger.add_entry(
            session, USER_ID, direction=Direction.RECEIVABLE,
            party_name="سررسید دیر", amount=200, due_date=_date(1403, 6, 1),
        )
        ledger.add_entry(
            session, USER_ID, direction=Direction.RECEIVABLE,
            party_name="سررسید زود", amount=300, due_date=_date(1403, 5, 1),
        )

    def test_order_by_due_date_none_last(self, session):
        self._seed(session)
        rows = ledger.list_open(session, USER_ID)
        names = [r.party_name for r in rows]
        assert names == ["سررسید زود", "سررسید دیر", "بدون سررسید"]

    def test_filter_by_direction(self, session):
        self._seed(session)
        receivables = ledger.list_open(
            session, USER_ID, direction=Direction.RECEIVABLE
        )
        assert len(receivables) == 2
        assert all(r.direction == Direction.RECEIVABLE for r in receivables)

    def test_settled_not_listed(self, session):
        self._seed(session)
        rows = ledger.list_open(session, USER_ID)
        settled = ledger.settle(session, rows[0].id, USER_ID, _dt(1403, 5, 2))
        assert settled is not None
        remaining = ledger.list_open(session, USER_ID)
        assert settled.id not in [r.id for r in remaining]


class TestSettle:
    def test_settle_sets_fields(self, session):
        entry = ledger.add_entry(
            session, USER_ID, direction=Direction.RECEIVABLE,
            party_name="مشتری", amount=400_000, due_date=_date(1403, 5, 8),
        )
        when = _dt(1403, 5, 9, 10, 30)
        result = ledger.settle(session, entry.id, USER_ID, when)
        assert result is not None
        assert result.is_settled is True
        assert result.settled_at == when

    def test_settle_wrong_user_returns_none(self, session):
        entry = ledger.add_entry(
            session, USER_ID, direction=Direction.PAYABLE,
            party_name="طرف", amount=50_000,
        )
        # کاربر دیگری تلاش می‌کند ردیف را تسویه کند.
        transactions.get_or_create_user(session, OTHER_USER_ID)
        result = ledger.settle(session, entry.id, OTHER_USER_ID, _dt(1403, 5, 10))
        assert result is None
        # ردیف باید همچنان باز بماند.
        still_open = session.get(LedgerEntry, entry.id)
        assert still_open.is_settled is False

    def test_settle_missing_entry_returns_none(self, session):
        transactions.get_or_create_user(session, USER_ID)
        assert ledger.settle(session, 999_999, USER_ID, _dt(1403, 5, 10)) is None


class TestDueWithin:
    def _seed(self, session):
        transactions.get_or_create_user(session, USER_ID)
        # معوق (قبل از base)
        ledger.add_entry(
            session, USER_ID, direction=Direction.RECEIVABLE,
            party_name="معوق", amount=100, due_date=_date(1403, 5, 5),
        )
        # داخل بازه‌ی ۷ روزه
        ledger.add_entry(
            session, USER_ID, direction=Direction.PAYABLE,
            party_name="نزدیک", amount=200, due_date=_date(1403, 5, 13),
        )
        # درست روی مرز آستانه
        ledger.add_entry(
            session, USER_ID, direction=Direction.RECEIVABLE,
            party_name="مرز", amount=300, due_date=_date(1403, 5, 17),
        )
        # بعد از بازه
        ledger.add_entry(
            session, USER_ID, direction=Direction.PAYABLE,
            party_name="دور", amount=400, due_date=_date(1403, 5, 25),
        )
        # بدون سررسید (نباید بیاید)
        ledger.add_entry(
            session, USER_ID, direction=Direction.PAYABLE,
            party_name="بی‌سررسید", amount=500, due_date=None,
        )

    def test_includes_overdue_and_within_window(self, session):
        self._seed(session)
        base = _dt(1403, 5, 10)  # آستانه = ۱۴۰۳/۵/۱۷
        rows = ledger.due_within(session, USER_ID, 7, base)
        names = [r.party_name for r in rows]
        # معوق، نزدیک و مرز باید بیایند و به ترتیب سررسید مرتب باشند.
        assert names == ["معوق", "نزدیک", "مرز"]

    def test_excludes_settled(self, session):
        self._seed(session)
        base = _dt(1403, 5, 10)
        rows = ledger.due_within(session, USER_ID, 7, base)
        ledger.settle(session, rows[0].id, USER_ID, base)
        rows2 = ledger.due_within(session, USER_ID, 7, base)
        assert rows[0].id not in [r.id for r in rows2]


class TestEntriesDueForReminder:
    def test_spans_all_users(self, session):
        transactions.get_or_create_user(session, USER_ID)
        transactions.get_or_create_user(session, OTHER_USER_ID)
        # کاربر اول: یک ردیف رسیده و یک ردیف آینده.
        ledger.add_entry(
            session, USER_ID, direction=Direction.RECEIVABLE,
            party_name="رسیده-۱", amount=100, due_date=_date(1403, 5, 9),
        )
        ledger.add_entry(
            session, USER_ID, direction=Direction.RECEIVABLE,
            party_name="آینده", amount=100, due_date=_date(1403, 5, 20),
        )
        # کاربر دوم: یک ردیف رسیده و یک ردیف بدون سررسید.
        ledger.add_entry(
            session, OTHER_USER_ID, direction=Direction.PAYABLE,
            party_name="رسیده-۲", amount=100, due_date=_date(1403, 5, 10),
        )
        ledger.add_entry(
            session, OTHER_USER_ID, direction=Direction.PAYABLE,
            party_name="بی‌سررسید", amount=100, due_date=None,
        )
        base = _dt(1403, 5, 10)  # امروز = ۱۴۰۳/۵/۱۰
        rows = ledger.entries_due_for_reminder(session, base)
        names = [r.party_name for r in rows]
        assert "رسیده-۱" in names
        assert "رسیده-۲" in names
        assert "آینده" not in names
        assert "بی‌سررسید" not in names
        # مرتب بر سررسید صعودی.
        assert names == ["رسیده-۱", "رسیده-۲"]

    def test_excludes_settled(self, session):
        transactions.get_or_create_user(session, USER_ID)
        entry = ledger.add_entry(
            session, USER_ID, direction=Direction.RECEIVABLE,
            party_name="رسیده", amount=100, due_date=_date(1403, 5, 9),
        )
        base = _dt(1403, 5, 10)
        assert len(ledger.entries_due_for_reminder(session, base)) == 1
        ledger.settle(session, entry.id, USER_ID, base)
        assert ledger.entries_due_for_reminder(session, base) == []


class TestBuildLedgerReport:
    def test_report_contains_totals_and_rows(self, session):
        transactions.get_or_create_user(session, USER_ID)
        ledger.add_entry(
            session, USER_ID, direction=Direction.RECEIVABLE,
            party_name="آقای احمدی", amount=1_200_000, due_date=_date(1403, 5, 15),
        )
        ledger.add_entry(
            session, USER_ID, direction=Direction.PAYABLE,
            party_name="شرکت پخش", amount=400_000, due_date=_date(1403, 5, 18),
        )
        report = ledger.build_ledger_report(session, USER_ID)
        assert isinstance(report, str)
        assert "طلب" in report
        assert "بدهی" in report
        assert "خالص" in report
        # نام طرف‌حساب‌ها و مبالغ فارسی باید در متن باشند.
        assert "آقای احمدی" in report
        assert "شرکت پخش" in report
        assert "۱٬۲۰۰٬۰۰۰" in report
        # سررسید شمسی ردیف نخست.
        assert jalali.format_date(_date(1403, 5, 15)) in report

    def test_report_when_empty(self, session):
        transactions.get_or_create_user(session, USER_ID)
        report = ledger.build_ledger_report(session, USER_ID)
        assert isinstance(report, str)
        assert "خالص" in report
