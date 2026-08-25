"""تست‌های پروفایلِ صنفِ کسب‌وکار (خالص + ذخیره‌سازی)."""
from hesabyar.core import industries
from hesabyar.db.models import Kind
from hesabyar.services import transactions as tx

UID = 909


class TestLookup:
    def test_known_and_unknown(self):
        assert industries.get("car") is not None
        assert industries.get("") is None
        assert industries.get(None) is None
        assert industries.get("ناشناخته") is None

    def test_labels_unique_and_nonempty(self):
        labels = [i.label for i in industries.all_industries()]
        assert len(labels) == len(set(labels))
        assert all(labels)

    def test_example_falls_back(self):
        assert industries.example_for(None) == industries.example_for("")
        assert "پژو" in industries.example_for("car")
        assert "مانتو" in industries.example_for("online_shop")

    def test_label_for_unknown(self):
        assert industries.label_for(None) == "نامشخص"


class TestRefineCategory:
    def test_car_specific_beats_generic(self):
        # «پژو» در حالت عمومی «خرید کالا…» می‌شد؛ در نمایشگاه باید «خرید خودرو» شود
        cat = industries.refine_category(
            "یک پژو ۴۰۰ میلیون خریدم", Kind.EXPENSE, "car", "خرید کالا و مواد اولیه"
        )
        assert cat == "خرید خودرو"

    def test_car_commission_income(self):
        cat = industries.refine_category(
            "۵ میلیون کمیسیون گرفتم", Kind.INCOME, "car", "فروش کالا"
        )
        assert cat == "کمیسیون"

    def test_online_shop_shipping(self):
        cat = industries.refine_category(
            "۲۰۰ هزار بابت تیپاکس دادم", Kind.EXPENSE, "online_shop", "متفرقه"
        )
        assert cat == "بسته‌بندی و ارسال"

    def test_food_materials(self):
        cat = industries.refine_category(
            "۳ میلیون گوشت خریدم", Kind.EXPENSE, "food", "خرید کالا و مواد اولیه"
        )
        assert cat == "مواد غذایی"

    def test_no_industry_keeps_fallback(self):
        assert industries.refine_category(
            "یک پژو خریدم", Kind.EXPENSE, "", "متفرقه"
        ) == "متفرقه"

    def test_unmatched_keeps_fallback(self):
        assert industries.refine_category(
            "قبض برق دادم", Kind.EXPENSE, "car", "قبوض"
        ) == "قبوض"

    def test_other_industry_has_no_overrides(self):
        assert industries.refine_category(
            "یک پژو خریدم", Kind.EXPENSE, "other", "متفرقه"
        ) == "متفرقه"

    def test_empty_text_is_safe(self):
        assert industries.refine_category("", Kind.EXPENSE, "car", "متفرقه") == "متفرقه"


class TestPersistence:
    async def test_business_type_round_trips(self):
        from fakes import FakeSpreadsheet

        from hesabyar.db.store import Store

        ss = FakeSpreadsheet()
        s = Store(ss)
        await s.load()
        user = await tx.get_or_create_user(s, UID)
        user.business_type = "car"
        await s.update("users", user)
        await s.flush()

        # بارگذاری مجدد از همان «شیت» باید مقدار را حفظ کند
        s2 = Store(ss)
        await s2.load()
        assert s2.get("users", UID).business_type == "car"

    async def test_default_is_empty(self, store):
        user = await tx.get_or_create_user(store, UID)
        assert user.business_type == ""
