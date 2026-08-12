"""تست‌های سنجه‌های پایلوت (روی Store ساختگی)."""
import datetime as dt

from hesabyar.core import jalali
from hesabyar.db.models import Kind
from hesabyar.services import pilot
from hesabyar.services import transactions as tx


async def test_empty_store(store):
    m = pilot.compute_pilot_metrics(store, jalali.now())
    assert m["total_users"] == 0
    assert m["activated"] == 0
    assert "داشبورد پایلوت" in pilot.build_pilot_report(m)


async def test_fast_activation(store):
    now = jalali.now()
    await tx.get_or_create_user(store, 1)
    await tx.add_transaction(
        store, 1, kind=Kind.INCOME, amount=100, category="x",
        description="", occurred_at=now,
    )
    m = pilot.compute_pilot_metrics(store, now)
    assert m["activated"] == 1
    # کاربر و اولین ثبت هر دو «همین حالا» ساخته شده‌اند → زیر ۲ دقیقه
    assert m["fast_activation"] == 1
    assert m["usage"]["transactions"] == 1


async def test_cohort_d7_and_week2(store):
    now = jalali.now()
    user = await tx.get_or_create_user(store, 7)
    user.created_at = now - dt.timedelta(days=15)  # کوهورتِ قدیمی‌تر
    for i in range(5):
        t = await tx.add_transaction(
            store, 7, kind=Kind.EXPENSE, amount=100, category="x",
            description="", occurred_at=now,
        )
        # داخل بازه‌ی هفته‌ی دوم: [signup+7, signup+14)
        t.created_at = now - dt.timedelta(days=15) + dt.timedelta(days=8, hours=i)

    m = pilot.compute_pilot_metrics(store, now)
    assert m["d7_eligible"] == 1
    assert m["d7_returned"] == 1
    assert m["w2_eligible"] == 1
    assert m["w2_active"] == 1


async def test_usage_counts(store):
    now = jalali.now()
    await tx.get_or_create_user(store, 2)
    from hesabyar.db.models import Direction, Instrument
    from hesabyar.services import ledger, products
    await ledger.add_entry(
        store, 2, direction=Direction.PAYABLE, party_name="چک‌دار",
        amount=1, instrument=Instrument.CHEQUE, cheque_no="111111",
    )
    await products.add_product(store, 2, "کالا", 1000)
    m = pilot.compute_pilot_metrics(store, now)
    assert m["usage"]["ledger"] == 1
    assert m["usage"]["cheques"] == 1
    assert m["usage"]["products"] == 1


# --- قیفِ آنبردینگ و DAU (فاز ۱۸) ------------------------------------------------


async def test_onboarding_funnel_counts_only_those_who_saw_it(store):
    now = jalali.now()
    saw_onboarding = await tx.get_or_create_user(store, 10)
    saw_onboarding.onboarding_started_at = now
    await store.update("users", saw_onboarding)

    await tx.get_or_create_user(store, 11)  # هیچ‌کدام از قیف را رد نکرده

    m = pilot.compute_pilot_metrics(store, now)
    assert m["total_users"] == 2
    assert m["onboarding_started"] == 1
    assert m["first_invoice_activated"] == 0
    assert m["first_contact_activated"] == 0


async def test_creating_an_invoice_activates_both_invoice_and_contact_milestones(store):
    from hesabyar.services import invoices as invoice_service

    now = jalali.now()
    await tx.get_or_create_user(store, 12)
    await invoice_service.create_invoice(
        store, 12, customer_name="علی",
        items=[{"title": "کالا", "quantity": 1, "unit_price": 10_000}],
        issue_date=now.date(),
    )
    m = pilot.compute_pilot_metrics(store, jalali.now())
    assert m["first_invoice_activated"] == 1
    assert m["first_contact_activated"] == 1  # فاکتور خودش رکورد مشتری می‌سازد


async def test_active_today_is_narrower_than_active_last_7(store):
    now = jalali.now()
    await tx.get_or_create_user(store, 20)
    await tx.add_transaction(
        store, 20, kind=Kind.EXPENSE, amount=100, category="x",
        description="", occurred_at=now,
    )
    await tx.get_or_create_user(store, 21)
    stale = await tx.add_transaction(
        store, 21, kind=Kind.EXPENSE, amount=100, category="x",
        description="", occurred_at=now,
    )
    stale.created_at = now - dt.timedelta(days=3)  # توی هفته هست، امروز نه

    # ``now``ی تازه: created_atِ تراکنشِ کاربرِ ۲۰ کمی بعد از ``now``ی بالا
    # مهر خورده (بازه‌ها «تا همین لحظه»اند، نه پایانِ روز/هفته).
    m = pilot.compute_pilot_metrics(store, jalali.now())
    assert m["active_today"] == 1
    assert m["active_last_7"] == 2


async def test_report_surfaces_the_new_sections(store):
    m = pilot.compute_pilot_metrics(store, jalali.now())
    text = pilot.build_pilot_report(m)
    assert "قیفِ آنبردینگ" in text
    assert "DAU" in text
