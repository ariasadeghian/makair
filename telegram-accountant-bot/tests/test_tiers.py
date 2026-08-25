"""تست‌های سطح‌بندی اشتراک (برنزی/نقره‌ای/طلایی) و امضای پای سند."""
import datetime as dt

from hesabyar import plans
from hesabyar.core import jalali
from hesabyar.plans import Feature
from hesabyar.services import subscription as sub
from hesabyar.services import transactions as tx

UID = 771


class TestPlanTable:
    def test_every_plan_has_a_known_tier(self):
        for key, plan in plans.PLANS.items():
            assert plan["tier"] in plans.TIERS, key
            assert plan["days"] > 0 and plan["price"] > 0

    def test_higher_tiers_include_lower_features(self):
        bronze = plans.tier_features("bronze")
        silver = plans.tier_features("silver")
        gold = plans.tier_features("gold")
        assert bronze <= silver <= gold
        assert Feature.NO_WATERMARK in silver
        assert Feature.DOLLAR in gold and Feature.DOLLAR not in silver

    def test_yearly_is_cheaper_per_month(self):
        for tier in plans.TIER_ORDER:
            keys = plans.plans_for_tier(tier)
            monthly = next(k for k in keys if plans.PLANS[k]["days"] <= 31)
            yearly = next(k for k in keys if plans.PLANS[k]["days"] > 300)
            per_month_m = plans.PLANS[monthly]["price"]
            per_month_y = plans.PLANS[yearly]["price"] / 12
            assert per_month_y < per_month_m, tier

    def test_trial_gets_top_tier(self):
        assert plans.tier_of("trial") == plans.TRIAL_TIER
        assert plans.plan_has_feature("trial", Feature.DOLLAR)

    def test_unknown_plan_is_bronze(self):
        assert plans.tier_of("nope") == "bronze"
        assert not plans.plan_has_feature("nope", Feature.VOICE)


class TestFeatureGate:
    async def test_trial_user_has_everything(self, store):
        await tx.get_or_create_user(store, UID)
        await sub.get_or_create_subscription(store, UID)
        assert sub.has_feature(store, UID, Feature.VOICE)
        assert sub.has_feature(store, UID, Feature.DOLLAR)
        assert sub.current_tier(store, UID) == plans.TRIAL_TIER

    async def test_bronze_lacks_paid_features(self, store):
        await tx.get_or_create_user(store, UID)
        await sub.extend(store, UID, 30, "bronze_monthly")
        assert sub.current_tier(store, UID) == "bronze"
        assert not sub.has_feature(store, UID, Feature.VOICE)
        assert not sub.has_feature(store, UID, Feature.NO_WATERMARK)
        assert not sub.has_feature(store, UID, Feature.DOLLAR)

    async def test_silver_has_voice_but_not_dollar(self, store):
        await tx.get_or_create_user(store, UID)
        await sub.extend(store, UID, 30, "silver_monthly")
        assert sub.has_feature(store, UID, Feature.VOICE)
        assert sub.has_feature(store, UID, Feature.NO_WATERMARK)
        assert not sub.has_feature(store, UID, Feature.DOLLAR)

    async def test_gold_has_everything(self, store):
        await tx.get_or_create_user(store, UID)
        await sub.extend(store, UID, 30, "gold_monthly")
        for f in (Feature.VOICE, Feature.OCR, Feature.STATEMENT,
                  Feature.DOLLAR, Feature.GROUP, Feature.NO_WATERMARK):
            assert sub.has_feature(store, UID, f), f

    async def test_expired_subscription_drops_to_bronze(self, store):
        await tx.get_or_create_user(store, UID)
        s = await sub.extend(store, UID, 30, "gold_monthly")
        s.expires_at = jalali.now() - dt.timedelta(days=1)
        await store.update("subscriptions", s)
        assert sub.current_tier(store, UID) == "bronze"
        assert not sub.has_feature(store, UID, Feature.VOICE)

    async def test_unknown_user_is_bronze(self, store):
        assert sub.current_tier(store, 999) == "bronze"
        assert not sub.has_feature(store, 999, Feature.VOICE)


class TestWatermarkRendering:
    def _invoice(self):
        from hesabyar.db.models import Invoice, InvoiceItem
        inv = Invoice(
            id=1, user_id=UID, number="۱۴۰۵-۰۰۰۱", seq=1,
            customer_name="رضا", issue_date=jalali.now().date(),
        )
        inv.items = [InvoiceItem(id=1, invoice_id=1, title="کالا",
                                 quantity=1, unit_price=500_000)]
        return inv

    def test_watermark_changes_output(self, tmp_path):
        from hesabyar.pdf.invoice_pdf import render_invoice_pdf
        plain = str(tmp_path / "plain.pdf")
        marked = str(tmp_path / "marked.pdf")
        render_invoice_pdf(self._invoice(), None, plain)
        render_invoice_pdf(self._invoice(), None, marked,
                           watermark="ساخته‌شده با @testbot")
        import fitz
        with fitz.open(marked) as d:
            assert "testbot" in d[0].get_text()
        with fitz.open(plain) as d:
            assert "testbot" not in d[0].get_text()

    def test_statement_watermark(self, tmp_path):
        from hesabyar.pdf.invoice_pdf import render_statement_pdf
        data = {
            "party": "علی", "business_name": "فروشگاه", "date": jalali.now(),
            "entries": [{"label": "طلب از", "amount": 100_000,
                         "due_date": None, "is_cheque": False}],
            "receivable": 100_000, "payable": 0, "net": 100_000,
        }
        out = str(tmp_path / "st.pdf")
        render_statement_pdf(data, out, watermark="ساخته‌شده با @testbot")
        import fitz
        with fitz.open(out) as d:
            assert "testbot" in d[0].get_text()
