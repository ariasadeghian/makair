"""تست‌های تطبیقِ تقریبیِ نام‌ها (فاز ۱۰)."""
from types import SimpleNamespace

import pytest

from hesabyar.bot import handlers
from hesabyar.config import Settings
from hesabyar.core import fuzzy
from hesabyar.core.categories import detect_category
from hesabyar.db.models import Kind
from hesabyar.services import products as products_service
from hesabyar.services import transactions as tx

UID = 12_001


# --- خودِ الگوریتم ---------------------------------------------------------------


class TestSimilarity:
    def test_identical_is_one(self):
        assert fuzzy.similarity("مبل", "مبل") == 1.0

    def test_empty_is_zero(self):
        assert fuzzy.similarity("", "مبل") == 0.0
        assert fuzzy.similarity("مبل", "") == 0.0

    def test_is_symmetric(self):
        assert fuzzy.similarity("مبلمان", "مبل") == fuzzy.similarity("مبل", "مبلمان")

    @pytest.mark.parametrize("a,b", [
        ("مبلمان", "مبل"),
        ("مبل راحتی", "مبل"),
        ("پیراهن مردانه", "پیراهن"),
        ("تبلیقات", "تبلیغات"),
        ("قبوض", "قبض"),
    ])
    def test_related_words_are_above_threshold(self, a, b):
        assert fuzzy.similarity(a, b) >= fuzzy.DEFAULT_THRESHOLD, (a, b)

    @pytest.mark.parametrize("a,b", [
        ("مبل", "میز"),
        ("مبل", "اجاره"),
        ("پیراهن", "لپ‌تاپ"),
        ("کولر گازی", "صندلی"),
    ])
    def test_unrelated_words_are_below_threshold(self, a, b):
        assert fuzzy.similarity(a, b) < fuzzy.DEFAULT_THRESHOLD, (a, b)


class TestNormalization:
    @pytest.mark.parametrize("a,b", [
        ("صندلي", "صندلی"),     # یِ عربی
        ("كاغذ", "کاغذ"),        # کافِ عربی
        ("لپ‌تاپ", "لپ تاپ"),    # نیم‌فاصله
        ("مبل  راحتی", "مبل راحتی"),
        ("مالياتِ", "مالیات"),   # اعراب
    ])
    def test_these_are_the_same_word(self, a, b):
        assert fuzzy.normalize(a) == fuzzy.normalize(b)
        assert fuzzy.similarity(a, b) == 1.0

    def test_case_folding(self):
        assert fuzzy.similarity("Laptop", "laptop") == 1.0


class TestBestMatch:
    CANDIDATES = ["مبل", "میز", "صندلی", "پیراهن مردانه"]

    def test_the_spec_example(self):
        """«مبلمان» باید «مبل» را پیدا کند."""
        assert fuzzy.best_match("مبلمان", self.CANDIDATES) == "مبل"

    def test_unrelated_word_matches_nothing(self):
        assert fuzzy.best_match("کولر گازی", self.CANDIDATES) is None
        assert fuzzy.best_match("اجاره مغازه", self.CANDIDATES) is None

    def test_returns_the_candidate_verbatim(self):
        """خروجی باید همان رشته‌ی ذخیره‌شده باشد، نه شکلِ نرمال‌شده."""
        assert fuzzy.best_match("پیراهن مردونه", ["پیراهن مردانه"]) == "پیراهن مردانه"

    def test_empty_query_or_candidates(self):
        assert fuzzy.best_match("", self.CANDIDATES) is None
        assert fuzzy.best_match("مبل", []) is None
        assert fuzzy.best_match("مبل", ["", None]) is None

    def test_shortest_wins_a_tie(self):
        assert fuzzy.best_match("مبل", ["مبل راحتی", "مبل"]) == "مبل"

    def test_very_short_query_needs_an_exact_match(self):
        """واژه‌ی دوحرفی شبیهِ همه‌چیز است؛ نباید حدس بزند."""
        assert fuzzy.best_match("می", ["میز", "مبل"]) is None
        assert fuzzy.best_match("می", ["می", "میز"]) == "می"

    def test_threshold_is_respected(self):
        assert fuzzy.best_match("مبل", ["میز"], threshold=0.1) == "میز"
        assert fuzzy.best_match("مبلمان", ["مبل"], threshold=0.99) is None

    def test_picks_the_closest_of_several(self):
        assert fuzzy.best_match("صندلي اداری", self.CANDIDATES) == "صندلی"


class TestCanonical:
    def test_returns_the_known_name(self):
        assert fuzzy.canonical("مبلمان", ["مبل", "میز"]) == "مبل"

    def test_returns_the_query_when_nothing_is_close(self):
        assert fuzzy.canonical("کولر گازی", ["مبل", "میز"]) == "کولر گازی"

    def test_empty_known_list_changes_nothing(self):
        assert fuzzy.canonical("مبلمان", []) == "مبلمان"


# --- دسته‌بندی -------------------------------------------------------------------


class TestCategoryFuzzy:
    @pytest.mark.parametrize("text,expected", [
        ("تبلیقات اینستاگرام", "بازاریابی و تبلیغات"),   # غلط تایپی
        ("کاغذی برای پرینتر", "ملزومات اداری"),
        ("بيمه تامين اجتماعي", "مالیات و بیمه"),         # حروف عربی
        ("مالياتِ عملکرد", "مالیات و بیمه"),             # اعراب
    ])
    def test_near_misses_still_find_the_category(self, text, expected):
        assert detect_category(text, Kind.EXPENSE) == expected

    def test_unrelated_text_stays_default(self):
        assert detect_category("یه چیز نامربوط", Kind.EXPENSE) == "متفرقه"
        assert detect_category("", Kind.EXPENSE) == "متفرقه"

    def test_exact_keywords_still_win(self):
        assert detect_category("قبض برق", Kind.EXPENSE) == "قبوض"
        assert detect_category("اجاره مغازه", Kind.EXPENSE) == "اجاره"

    def test_income_side_works_too(self):
        assert detect_category("خدمت به مشتری", Kind.INCOME) == "درآمد خدمات"

    def test_a_short_noise_word_does_not_pick_a_category(self):
        assert detect_category("با یه چیزی", Kind.EXPENSE) == "متفرقه"


# --- کالاها --------------------------------------------------------------------


class _Msg:
    def __init__(self, text=""):
        self.text = text
        self.replies: list = []
        self.chat = SimpleNamespace(id=UID, type="private", title=None)
        self.chat_id = UID
        self.message_id = 1
        self.entities = []
        self.reply_to_message = None

    async def reply_text(self, text, **kw):
        self.replies.append({"text": text, **kw})
        return SimpleNamespace(message_id=2, chat_id=UID)


class _Bot:
    async def send_message(self, chat_id, text=None, **kw):
        return None

    async def edit_message_text(self, **kw):
        return None


def _ctx(store):
    app = SimpleNamespace(
        bot_data={"store": store, "settings": Settings(bot_token="x")}, bot=_Bot()
    )
    return SimpleNamespace(application=app, bot=app.bot,
                           chat_data={}, user_data={}, args=[])


def _update(message):
    return SimpleNamespace(
        message=message, callback_query=None,
        effective_user=SimpleNamespace(id=UID, full_name="تست", username="t"),
        effective_chat=SimpleNamespace(id=UID, type="private", title=None),
        effective_message=message,
    )


def _products(*pairs):
    return {title: SimpleNamespace(id=i, title=title, unit_price=price)
            for i, (title, price) in enumerate(pairs, start=1)}


class TestProductNameFuzzy:
    def test_typed_variant_reuses_the_saved_product_name(self):
        products = _products(("مبل", 25_000_000))
        item = handlers._parse_item("مبلمان ۲ ۳۰ میلیون", products)
        assert item["title"] == "مبل", "کالای تکراری ساخته شد"
        assert (item["quantity"], item["unit_price"]) == (2, 30_000_000)

    def test_exact_name_still_takes_the_saved_price(self):
        products = _products(("مبل", 25_000_000))
        item = handlers._parse_item("۳ مبل", products)
        assert (item["title"], item["quantity"], item["unit_price"]) == (
            "مبل", 3, 25_000_000
        )

    @pytest.mark.parametrize("text,qty,price", [
        ("مبل ۲ ۳۰ میلیون", 2, 30_000_000),
        ("مبلمان ۲ ۳۰ میلیون", 2, 30_000_000),
        ("۲ مبل ۵۰۰ هزار", 2, 500_000),
    ])
    def test_a_typed_price_beats_the_saved_one(self, text, qty, price):
        """اگر کاربر قیمت نوشت، همان معتبر است — نه قیمتِ ذخیره‌شده."""
        item = handlers._parse_item(text, _products(("مبل", 25_000_000)))
        assert (item["title"], item["quantity"], item["unit_price"]) == (
            "مبل", qty, price
        )

    @pytest.mark.parametrize("text,qty", [("مبل", 1), ("۲ مبل", 2), ("مبل ۳", 3)])
    def test_without_a_typed_price_the_saved_one_is_used(self, text, qty):
        item = handlers._parse_item(text, _products(("مبل", 25_000_000)))
        assert (item["quantity"], item["unit_price"]) == (qty, 25_000_000)

    def test_a_genuinely_new_product_keeps_its_own_name(self):
        products = _products(("مبل", 25_000_000))
        item = handlers._parse_item("کولر گازی ۱ ۴۰ میلیون", products)
        assert item["title"] == "کولر گازی"

    def test_works_with_no_saved_products(self):
        item = handlers._parse_item("مبلمان ۲ ۳۰ میلیون", {})
        assert item["title"] == "مبلمان"

    def test_cross_format_is_canonicalised_too(self):
        products = _products(("پیراهن مردانه", 500_000))
        item = handlers._parse_item("پیراهن مردونه × ۲ × ۴۰۰ هزار", products)
        assert item["title"] == "پیراهن مردانه"

    def test_unparsable_text_is_still_none(self):
        assert handlers._parse_item("سلام", _products(("مبل", 1))) is None
        assert handlers._parse_item("", _products(("مبل", 1))) is None

    async def test_typed_item_in_the_invoice_builder(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        await products_service.add_product(store, UID, "مبل", 25_000_000)
        ctx.user_data["flow"] = "invoice_items"
        ctx.user_data["invoice"] = {
            "customer_name": "رضا", "items": [], "discount": 0, "shipping": 0
        }
        await handlers.on_text(_update(_Msg("مبلمان ۲ ۳۰ میلیون")), ctx)
        assert ctx.user_data["invoice"]["items"][0]["title"] == "مبل"

    async def test_sentence_invoice_canonicalises_names_too(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        await products_service.add_product(store, UID, "مبل", 25_000_000)
        await handlers.on_text(
            _update(_Msg("فاکتور برای رضا ۲ عدد مبلمان ۳۰ میلیون")), ctx
        )
        assert ctx.user_data["invnlp"]["items"][0]["title"] == "مبل"

    async def test_sentence_invoice_keeps_unknown_names(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        await products_service.add_product(store, UID, "مبل", 25_000_000)
        await handlers.on_text(
            _update(_Msg("فاکتور برای رضا ۱ عدد کولر گازی ۴۰ میلیون")), ctx
        )
        assert ctx.user_data["invnlp"]["items"][0]["title"] == "کولر گازی"


class TestCustomersStayExact:
    """نامِ آدم‌ها فازی نمی‌شود — «رضا» و «رضایی» دو نفرند."""

    async def test_similar_names_remain_two_people(self, store):
        from hesabyar.services import customers as customers_service
        await tx.get_or_create_user(store, UID)
        first = await customers_service.find_or_create_customer(store, UID, "رضا")
        second = await customers_service.find_or_create_customer(store, UID, "رضایی")
        assert first.id != second.id
        assert len(store.list("customers")) == 2
