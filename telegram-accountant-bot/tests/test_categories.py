from hesabyar.core.categories import detect_category
from hesabyar.db.models import Kind


class TestExpenseCategories:
    def test_rent(self):
        assert detect_category("اجاره مغازه", Kind.EXPENSE) == "اجاره"

    def test_bills(self):
        assert detect_category("قبض برق", Kind.EXPENSE) == "قبوض"

    def test_salary(self):
        assert detect_category("حقوق کارگر", Kind.EXPENSE) == "حقوق و دستمزد"

    def test_materials(self):
        assert detect_category("خرید مواد اولیه", Kind.EXPENSE) == "خرید کالا و مواد اولیه"

    def test_transport(self):
        assert detect_category("کرایه پیک", Kind.EXPENSE) == "حمل و نقل"

    def test_marketing(self):
        assert detect_category("تبلیغات اینستاگرام", Kind.EXPENSE) == "بازاریابی و تبلیغات"

    def test_default_expense(self):
        assert detect_category("یه چیز نامشخص", Kind.EXPENSE) == "متفرقه"


class TestIncomeCategories:
    def test_sale(self):
        assert detect_category("فروش محصول", Kind.INCOME) == "فروش کالا"

    def test_service(self):
        assert detect_category("خدمات مشاوره", Kind.INCOME) == "درآمد خدمات"

    def test_default_income(self):
        assert detect_category("یه درآمد", Kind.INCOME) == "فروش کالا"
