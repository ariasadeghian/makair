"""تست‌های قابلیت‌های «داخل باند»: چک، صورتحساب طرف‌حساب، خلاصه‌ی شبانه."""
from hesabyar.bot import handlers
from hesabyar.core import jalali, money
from hesabyar.db.models import Direction, Instrument, Kind
from hesabyar.services import ledger as ledger_service
from hesabyar.services import reports
from hesabyar.services import transactions as tx

UID = 321


class TestChequeDetection:
    def test_detects_cheque_and_number(self):
        inst, no, name = handlers._detect_cheque("چک ۱۲۳۴۵۶۷ رضایی")
        assert inst == Instrument.CHEQUE
        assert no == "1234567"
        assert "رضایی" in name and "چک" not in name and "۱۲۳" not in name

    def test_plain_name_is_cash(self):
        inst, no, name = handlers._detect_cheque("آقای رضایی")
        assert inst == Instrument.CASH
        assert no == "" and name == "آقای رضایی"


class TestChequeLedger:
    async def test_cheque_entry_and_report(self, store):
        await tx.get_or_create_user(store, UID)
        e = await ledger_service.add_entry(
            store, UID, direction=Direction.PAYABLE, party_name="رضایی",
            amount=50_000_000, due_date=jalali.now().date(),
            instrument=Instrument.CHEQUE, cheque_no="123456",
        )
        assert e.is_cheque and e.cheque_no == "123456"
        assert "🧾 چک" in ledger_service.build_ledger_report(store, UID)


class TestPartyStatement:
    async def test_net_debtor_and_entries(self, store):
        await tx.get_or_create_user(store, UID)
        # او ۵۰۰ به ما بدهکار، ما ۲۰۰ به او → خالص ۳۰۰ بدهکار
        await ledger_service.add_entry(
            store, UID, direction=Direction.RECEIVABLE,
            party_name="علی محمدی", amount=500_000,
        )
        await ledger_service.add_entry(
            store, UID, direction=Direction.PAYABLE,
            party_name="علی محمدی", amount=200_000,
        )
        st = ledger_service.build_party_statement(store, UID, "علی محمدی")
        assert st is not None
        assert "علی محمدی" in st
        assert "بدهکار" in st
        assert money.to_persian_digits("300") in st

    async def test_partial_name_match(self, store):
        await tx.get_or_create_user(store, UID)
        await ledger_service.add_entry(
            store, UID, direction=Direction.RECEIVABLE,
            party_name="علی محمدی", amount=100_000,
        )
        assert len(ledger_service.entries_for_party(store, UID, "علی")) == 1

    async def test_empty_returns_none(self, store):
        await tx.get_or_create_user(store, UID)
        assert ledger_service.build_party_statement(store, UID, "ناکس") is None

    async def test_statement_data_shape(self, store):
        await tx.get_or_create_user(store, UID)
        await ledger_service.add_entry(
            store, UID, direction=Direction.RECEIVABLE,
            party_name="حسینی", amount=750_000,
        )
        data = ledger_service.party_statement_data(store, UID, "حسینی")
        assert data is not None
        assert data["net"] == 750_000
        assert len(data["entries"]) == 1
        assert data["entries"][0]["label"] == "طلب از"


class TestStatementImage:
    async def test_png_created(self, store, tmp_path):
        from hesabyar.pdf.invoice_pdf import render_statement_image

        user = await tx.get_or_create_user(store, UID)
        user.business_name = "بوتیک آرا"
        await ledger_service.add_entry(
            store, UID, direction=Direction.RECEIVABLE, party_name="رضا رضایی",
            amount=500_000, due_date=jalali.now().date(),
        )
        await ledger_service.add_entry(
            store, UID, direction=Direction.PAYABLE, party_name="رضا رضایی",
            amount=200_000, instrument=Instrument.CHEQUE, cheque_no="998877",
        )
        data = ledger_service.party_statement_data(store, UID, "رضا رضایی", business=user)
        out = str(tmp_path / "statement.png")
        render_statement_image(data, out)
        with open(out, "rb") as fh:
            assert fh.read(8) == b"\x89PNG\r\n\x1a\n"
        import os as _os
        assert _os.path.getsize(out) > 3000


class TestDailyDigest:
    async def test_active_user_gets_digest(self, store):
        await tx.get_or_create_user(store, UID)
        await tx.add_transaction(
            store, UID, kind=Kind.INCOME, amount=2_000_000,
            category="فروش کالا", description="", occurred_at=jalali.now(),
        )
        digest = reports.build_daily_digest(store, UID, jalali.now())
        assert digest is not None
        assert "خلاصه‌ی امروز" in digest
        assert money.to_persian_digits("2") in digest or "۲" in digest

    async def test_inactive_user_none(self, store):
        await tx.get_or_create_user(store, UID)
        assert reports.build_daily_digest(store, UID, jalali.now()) is None
