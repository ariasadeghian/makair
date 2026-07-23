"""تست یکپارچگی: مسیرهای واقعی هندلرها روی سرویس‌های واقعی.

هدف: اطمینان از هماهنگ‌بودن لایه‌ی بات (bot/handlers, reminders) با ماژول‌های
سرویس — همان آرگومان‌ها و همان شکل خروجی که هندلرها استفاده می‌کنند.
"""
import datetime as dt

from hesabyar.config import Settings
from hesabyar.core import jalali, nlp
from hesabyar.db.models import Direction, Kind
from hesabyar.pdf.invoice_pdf import render_invoice_pdf
from hesabyar.services import invoices as invoice_service
from hesabyar.services import ledger as ledger_service
from hesabyar.services import ocr as ocr_service
from hesabyar.services import reports as report_service
from hesabyar.services import transactions as tx_service

UID = 12345


async def test_transaction_flow(store):
    """مثل _log_transaction در هندلر."""
    await tx_service.get_or_create_user(store, UID)
    parsed = nlp.parse_transaction("امروز ۲ میلیون فروختم", base=jalali.now())
    assert parsed is not None
    assert parsed.kind == Kind.INCOME
    assert parsed.amount == 2_000_000
    tx = await tx_service.add_transaction(
        store,
        UID,
        kind=parsed.kind,
        amount=parsed.amount,
        category=parsed.category,
        description=parsed.description,
        occurred_at=parsed.occurred_at,
    )
    assert tx.id is not None

    # هزینه هم اضافه کنیم
    p2 = nlp.parse_transaction("قبض برق ۳۲۰ هزار پرداختم", base=jalali.now())
    assert p2 is not None and p2.kind == Kind.EXPENSE and p2.amount == 320_000
    await tx_service.add_transaction(
        store, UID, kind=p2.kind, amount=p2.amount,
        category=p2.category, description=p2.description, occurred_at=p2.occurred_at,
    )

    s = tx_service.summary(store, UID, *jalali.month_bounds(jalali.now()))
    assert s["income"] == 2_000_000
    assert s["expense"] == 320_000
    assert s["balance"] == 1_680_000

    report = report_service.build_report(store, UID, jalali.now(), "month")
    assert isinstance(report, str) and "۲٬۰۰۰٬۰۰۰" in report


async def test_ledger_flow(store):
    """مثل _handle_ledger_flow و reminders."""
    await tx_service.get_or_create_user(store, UID)
    today = jalali.now().date()
    await ledger_service.add_entry(
        store, UID, direction=Direction.RECEIVABLE,
        party_name="علی", amount=500_000, due_date=today, description="",
    )
    await ledger_service.add_entry(
        store, UID, direction=Direction.PAYABLE,
        party_name="شرکت پخش", amount=300_000, due_date=None, description="",
    )

    t = ledger_service.totals(store, UID)
    assert t["receivable"] == 500_000
    assert t["payable"] == 300_000
    assert t["net"] == 200_000

    report = ledger_service.build_ledger_report(store, UID)
    assert "علی" in report

    due = ledger_service.entries_due_for_reminder(store, jalali.now())
    assert any(e.party_name == "علی" for e in due)


async def test_invoice_flow(store, tmp_path):
    """مثل _finalize_invoice در هندلر."""
    user = await tx_service.get_or_create_user(store, UID)
    user.business_name = "فروشگاه نمونه"
    items = [
        {"title": "پیراهن", "quantity": 3, "unit_price": 250_000},
        {"title": "شلوار", "quantity": 2, "unit_price": 400_000},
    ]
    invoice = await invoice_service.create_invoice(
        store, UID, customer_name="رضا محمدی",
        items=items, issue_date=jalali.now().date(),
    )
    assert invoice.total == 3 * 250_000 + 2 * 400_000

    out = str(tmp_path / "factor.pdf")
    render_invoice_pdf(invoice, user, out)
    with open(out, "rb") as fh:
        head = fh.read(5)
    assert head.startswith(b"%PDF")

    fetched = invoice_service.get_invoice(store, invoice.id, UID)
    assert fetched is not None
    # کاربر دیگر نباید فاکتور را ببیند
    assert invoice_service.get_invoice(store, invoice.id, 999) is None


async def test_moadian_payload_from_db_invoice(store):
    """مثل on_moadian: ساخت payload از یک فاکتور واقعی دیتابیس."""
    from hesabyar.services import moadian as moadian_service

    user = await tx_service.get_or_create_user(store, UID)
    user.business_name = "فروشگاه تست"
    invoice = await invoice_service.create_invoice(
        store, UID, customer_name="مشتری",
        items=[{"title": "کالا", "quantity": 2, "unit_price": 100_000}],
        issue_date=jalali.now().date(),
    )
    payload = moadian_service.build_invoice_payload(
        invoice, user, economic_code="123", seller_tin="456", vat_rate=0.10
    )
    assert payload["header"]["inno"] == invoice.number
    assert len(payload["body"]) == 1
    assert payload["totals"]["subtotal"] == 200_000
    assert payload["totals"]["vat"] == 20_000
    assert payload["totals"]["total"] == 220_000


async def test_deleted_transaction_attributes_readable(store):
    """الگوی undo: پس از حذف و commit، صفت‌های تراکنش باید خوانا بمانند."""
    await tx_service.get_or_create_user(store, UID)
    t = await tx_service.add_transaction(
        store, UID, kind=Kind.EXPENSE, amount=50_000,
        category="متفرقه", description="x", occurred_at=jalali.now(),
    )
    deleted = await tx_service.delete_transaction(store, UID, t.id)
    assert deleted is not None
    label = f"{deleted.kind} {deleted.amount} {deleted.category}"
    assert "50000" in label


def test_ocr_provider_selection():
    """مثل build_application و on_photo."""
    off = Settings(bot_token="x")
    assert isinstance(ocr_service.get_ocr_provider(off), ocr_service.NullOcrProvider)

    on = Settings(
        bot_token="x", ocr_base_url="https://api.example.com/v1",
        ocr_api_key="secret", ocr_model="gpt-4o-mini",
    )
    provider = ocr_service.get_ocr_provider(on)
    assert not isinstance(provider, ocr_service.NullOcrProvider)

    parsed = ocr_service.parse_receipt_text("خرید مواد اولیه ۵۰۰ هزار تومان", base=jalali.now())
    assert parsed is not None and parsed.amount == 500_000
