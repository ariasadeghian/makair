import os

from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from hesabyar.core import jalali
from hesabyar.db.database import init_db, make_session_factory
from hesabyar.db.models import Direction, Kind
from hesabyar.services import backup
from hesabyar.services import invoices as inv
from hesabyar.services import ledger
from hesabyar.services import transactions as tx

UID = 55


class TestFullExport:
    def test_multi_sheet_export(self, session, tmp_path):
        user = tx.get_or_create_user(session, UID)
        user.business_name = "کسب‌وکار من"
        tx.add_transaction(
            session, UID, kind=Kind.INCOME, amount=1_000_000,
            category="فروش کالا", description="فروش", occurred_at=jalali.now(),
        )
        tx.add_transaction(
            session, UID, kind=Kind.EXPENSE, amount=300_000,
            category="اجاره", description="اجاره مغازه", occurred_at=jalali.now(),
        )
        ledger.add_entry(
            session, UID, direction=Direction.RECEIVABLE,
            party_name="علی", amount=500_000,
        )
        inv.create_invoice(
            session, UID, customer_name="رضا",
            items=[{"title": "کالا", "quantity": 1, "unit_price": 200_000}],
            issue_date=jalali.now().date(),
        )
        session.commit()

        out = str(tmp_path / "full.xlsx")
        backup.export_full_user_xlsx(session, UID, out, business=user)
        assert os.path.exists(out)

        wb = load_workbook(out)
        assert set(wb.sheetnames) == {"تراکنش‌ها", "طلب و بدهی", "فاکتورها"}
        # ۲ تراکنش (به‌علاوه‌ی سطر هدر)
        assert wb["تراکنش‌ها"].max_row == 3
        assert wb["طلب و بدهی"].max_row == 2   # هدر + ۱ ردیف
        assert wb["فاکتورها"].max_row == 2     # هدر + ۱ فاکتور

    def test_empty_user(self, session, tmp_path):
        tx.get_or_create_user(session, UID)
        session.commit()
        out = str(tmp_path / "empty.xlsx")
        backup.export_full_user_xlsx(session, UID, out)
        wb = load_workbook(out)
        assert wb["تراکنش‌ها"].max_row == 1  # فقط هدر


class TestSqliteBackup:
    def test_backup_file_db(self, tmp_path):
        db_path = tmp_path / "data.db"
        url = f"sqlite:///{db_path}"
        engine = create_engine(url, future=True)
        init_db(engine)
        # چند رکورد بنویس تا فایل خالی نباشد
        SessionLocal = make_session_factory(engine)
        s = SessionLocal()
        tx.get_or_create_user(s, UID)
        s.close()
        engine.dispose()

        dest = backup.backup_sqlite(url, dest_dir=str(tmp_path / "backups"), stamp="20250101-000000")
        assert dest is not None
        assert os.path.exists(dest)
        assert dest.endswith(".bak")

    def test_memory_db_returns_none(self):
        assert backup.backup_sqlite("sqlite://") is None
        assert backup.backup_sqlite("sqlite:///:memory:") is None

    def test_non_sqlite_returns_none(self):
        assert backup.backup_sqlite("postgresql://localhost/db") is None
