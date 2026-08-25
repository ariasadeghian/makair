"""تست‌های تبِ «📋 خلاصه» و دسته‌بندیِ کالاها (فاز ۱۴).

قاعده‌ی اصلی: تبِ خلاصه فقط نمایشی است. بات هرگز از آن نمی‌خواند و هرچه
داخلش باشد (یا نباشد) روی دیتای واقعیِ `products` اثری ندارد.
"""
from types import SimpleNamespace

import pytest

from fakes import FakeSpreadsheet

from hesabyar.bot import handlers, keyboards, texts
from hesabyar.config import Settings
from hesabyar.db import sheets_client as sc
from hesabyar.db.models import Product, USER_MODELS
from hesabyar.services import products as products_service
from hesabyar.services import transactions as tx

UID = 16_001


def _cb(markup):
    rows = getattr(markup, "inline_keyboard", None)
    return [b.callback_data for row in rows for b in row] if rows else []


# --- مدل --------------------------------------------------------------------------


class TestProductModel:
    def test_category_is_a_new_column_not_a_replacement(self):
        for old in ("id", "user_id", "title", "unit_price", "created_at"):
            assert old in Product.COLUMNS, old
        assert Product.COLUMNS[-1] == "category"

    def test_round_trip(self):
        product = Product(id=1, user_id=UID, title="مبل", unit_price=5_000_000,
                          category="مبلمان")
        row = dict(zip(Product.COLUMNS, product.to_row()))
        assert Product.from_row(row).category == "مبلمان"

    def test_old_rows_without_the_column_default_to_empty(self):
        assert Product.from_row({"id": "1", "title": "مبل"}).category == ""


class TestProductsService:
    async def test_category_is_saved(self, store):
        await tx.get_or_create_user(store, UID)
        product = await products_service.add_product(
            store, UID, "مبل", 5_000_000, "مبلمان"
        )
        assert product.category == "مبلمان"
        assert store.get("products", product.id).category == "مبلمان"

    async def test_used_categories_are_unique_and_ranked(self, store):
        await tx.get_or_create_user(store, UID)
        for title, cat in [("مبل", "مبلمان"), ("میز", "مبلمان"), ("لیوان", "ظروف")]:
            await products_service.add_product(store, UID, title, 1000, cat)
        await products_service.add_product(store, UID, "بی‌دسته", 1000)
        assert products_service.used_categories(store, UID) == ["مبلمان", "ظروف"]

    async def test_categories_do_not_leak_between_users(self, store):
        await tx.get_or_create_user(store, UID)
        await tx.get_or_create_user(store, UID + 1)
        await products_service.add_product(store, UID, "مبل", 1000, "مبلمان")
        await products_service.add_product(store, UID + 1, "کتاب", 1000, "نوشت‌افزار")
        assert products_service.used_categories(store, UID) == ["مبلمان"]

    async def test_by_category_puts_uncategorised_last(self, store):
        await tx.get_or_create_user(store, UID)
        await products_service.add_product(store, UID, "بی‌دسته", 1000)
        await products_service.add_product(store, UID, "مبل", 1000, "مبلمان")
        grouped = products_service.by_category(store, UID)
        assert list(grouped) == ["مبلمان", ""]


# --- تبِ خلاصه --------------------------------------------------------------------


def _user(**kw):
    return SimpleNamespace(
        id=UID, business_name=kw.get("name", "قنادی شیرین"),
        business_type=kw.get("industry", "cafe"),
    )


def _grouped():
    return {
        "مبلمان": [
            SimpleNamespace(title="مبل", unit_price=25_000_000),
            SimpleNamespace(title="میز", unit_price=3_000_000),
        ],
        "ظروف": [SimpleNamespace(title="لیوان", unit_price=50_000)],
    }


class TestSummarySheet:
    def test_it_is_created_when_missing(self):
        sheet = FakeSpreadsheet()
        sc.rebuild_summary_sheet(sheet, _user(), _grouped(), "طلایی")
        assert sc.SUMMARY_SHEET_TITLE in {ws.title for ws in sheet.worksheets()}

    def test_business_details_are_at_the_top(self):
        sheet = FakeSpreadsheet()
        sc.rebuild_summary_sheet(sheet, _user(), _grouped(), "طلایی")
        rows = sheet.worksheet(sc.SUMMARY_SHEET_TITLE).get_all_values()
        assert rows[0][0].startswith("👤")
        flat = {r[0]: r[1] for r in rows if len(r) > 1}
        assert flat["نام کسب‌وکار"] == "قنادی شیرین"
        assert flat["صنف"] == "cafe"
        assert flat["پلن اشتراک"] == "طلایی"

    def test_products_are_grouped_under_category_headers(self):
        sheet = FakeSpreadsheet()
        sc.rebuild_summary_sheet(sheet, _user(), _grouped(), "طلایی")
        first = [r[0] for r in sheet.worksheet(sc.SUMMARY_SHEET_TITLE).get_all_values()]
        assert "-- مبلمان --" in first and "-- ظروف --" in first
        assert first.index("-- مبلمان --") < first.index("مبل") < first.index("-- ظروف --")

    def test_uncategorised_products_get_a_readable_header(self):
        sheet = FakeSpreadsheet()
        sc.rebuild_summary_sheet(
            sheet, _user(), {"": [SimpleNamespace(title="مبل", unit_price=1)]}, ""
        )
        first = [r[0] for r in sheet.worksheet(sc.SUMMARY_SHEET_TITLE).get_all_values()]
        assert "-- بدون دسته --" in first

    def test_it_is_fully_rebuilt_not_appended(self):
        sheet = FakeSpreadsheet()
        sc.rebuild_summary_sheet(sheet, _user(), _grouped(), "طلایی")
        before = len(sheet.worksheet(sc.SUMMARY_SHEET_TITLE).get_all_values())
        sc.rebuild_summary_sheet(sheet, _user(), _grouped(), "طلایی")
        assert len(sheet.worksheet(sc.SUMMARY_SHEET_TITLE).get_all_values()) == before

    def test_a_removed_product_disappears_on_rebuild(self):
        sheet = FakeSpreadsheet()
        sc.rebuild_summary_sheet(sheet, _user(), _grouped(), "طلایی")
        sc.rebuild_summary_sheet(sheet, _user(), {"ظروف": _grouped()["ظروف"]}, "طلایی")
        first = [r[0] for r in sheet.worksheet(sc.SUMMARY_SHEET_TITLE).get_all_values()]
        assert "مبل" not in first

    def test_no_products_is_not_an_error(self):
        sheet = FakeSpreadsheet()
        sc.rebuild_summary_sheet(sheet, _user(), {}, "")
        first = [r[0] for r in sheet.worksheet(sc.SUMMARY_SHEET_TITLE).get_all_values()]
        assert "هنوز کالایی ثبت نشده" in first

    def test_missing_business_details_show_a_dash(self):
        sheet = FakeSpreadsheet()
        sc.rebuild_summary_sheet(sheet, _user(name="", industry=""), {}, "")
        flat = {r[0]: r[1]
                for r in sheet.worksheet(sc.SUMMARY_SHEET_TITLE).get_all_values()
                if len(r) > 1}
        assert flat["نام کسب‌وکار"] == "—" and flat["صنف"] == "—"


class TestTheBotNeverReadsIt:
    def test_no_model_owns_this_tab(self):
        assert sc.SUMMARY_SHEET_TITLE not in {m.TABLE for m in USER_MODELS}

    async def test_load_user_ignores_it(self, store):
        """حتی اگر تبِ خلاصه پر از زباله باشد، دیتای واقعی سالم می‌ماند."""
        await tx.get_or_create_user(store, UID)
        await store.ensure_user_spreadsheet(UID, "تست")
        await products_service.add_product(store, UID, "مبل", 5_000_000, "مبلمان")
        await store.flush()
        await store.refresh_summary(UID)

        # زباله داخلِ تبِ نمایشی
        sheet = store._client.sheets[store.get("users", UID).sheet_id]
        sheet.worksheet(sc.SUMMARY_SHEET_TITLE).update(
            [["آشغال", "۹۹۹"], ["چیز", "بی‌ربط"]]
        )

        store.data["products"].clear()
        store._loaded_users.discard(UID)
        store._user_ss.pop(UID, None)
        await store.load_user(UID)

        products = products_service.list_products(store, UID)
        assert len(products) == 1
        assert (products[0].title, products[0].category) == ("مبل", "مبلمان")

    async def test_deleting_the_summary_tab_breaks_nothing(self, store):
        await tx.get_or_create_user(store, UID)
        await store.ensure_user_spreadsheet(UID, "تست")
        await products_service.add_product(store, UID, "مبل", 1000, "مبلمان")
        await store.flush()
        await store.refresh_summary(UID)

        sheet = store._client.sheets[store.get("users", UID).sheet_id]
        sheet._ws.pop(sc.SUMMARY_SHEET_TITLE)

        store.data["products"].clear()
        store._loaded_users.discard(UID)
        store._user_ss.pop(UID, None)
        await store.load_user(UID)
        assert len(products_service.list_products(store, UID)) == 1


# --- رنگِ دسته‌ها --------------------------------------------------------------------


class TestCategoryColors:
    def test_the_same_name_always_gets_the_same_colour(self):
        assert sc.color_for_category("مبلمان") == sc.color_for_category("مبلمان")

    def test_different_names_usually_differ(self):
        names = ["مبلمان", "ظروف", "پوشاک", "نوشت‌افزار", "خوراکی"]
        assert len({str(sc.color_for_category(n)) for n in names}) > 1

    def test_rules_target_the_category_column(self):
        sheet = FakeSpreadsheet()
        ws = sheet.add_worksheet("products")
        sc.apply_category_colors(sheet, ws, ["مبلمان", "ظروف"])
        requests = sheet.batch_updates[-1]["requests"]
        formulas = [
            r["addConditionalFormatRule"]["rule"]["booleanRule"]["condition"]
            ["values"][0]["userEnteredValue"]
            for r in requests if "addConditionalFormatRule" in r
        ]
        letter = sc._col_letter(list(Product.COLUMNS).index("category") + 1)
        assert formulas == [f'=${letter}2="مبلمان"', f'=${letter}2="ظروف"']

    def test_the_header_row_is_excluded(self):
        sheet = FakeSpreadsheet()
        ws = sheet.add_worksheet("products")
        sc.apply_category_colors(sheet, ws, ["مبلمان"])
        rule = sheet.batch_updates[-1]["requests"][0]["addConditionalFormatRule"]
        assert rule["rule"]["ranges"][0]["startRowIndex"] == 1

    def test_empty_categories_are_ignored(self):
        sheet = FakeSpreadsheet()
        ws = sheet.add_worksheet("products")
        sc.apply_category_colors(sheet, ws, ["", None])
        assert sheet.batch_updates == []

    def test_duplicates_produce_one_rule_each(self):
        sheet = FakeSpreadsheet()
        ws = sheet.add_worksheet("products")
        sc.apply_category_colors(sheet, ws, ["مبلمان", "مبلمان", "ظروف"])
        adds = [r for r in sheet.batch_updates[-1]["requests"]
                if "addConditionalFormatRule" in r]
        assert len(adds) == 2

    def test_old_rules_are_deleted_first(self):
        class _WithRules(FakeSpreadsheet):
            def fetch_sheet_metadata(self, params=None):
                return {"sheets": [{"properties": {"sheetId": 1},
                                    "conditionalFormats": [{}, {}, {}]}]}

        sheet = _WithRules()
        ws = sheet.add_worksheet("products")   # sheetId = 1
        sc.apply_category_colors(sheet, ws, ["مبلمان"])
        deletes = [r["deleteConditionalFormatRule"]["index"]
                   for r in sheet.batch_updates[-1]["requests"]
                   if "deleteConditionalFormatRule" in r]
        assert deletes == [2, 1, 0], "باید از آخر به اول حذف شوند"

    def test_an_api_failure_is_swallowed(self):
        class _Angry(FakeSpreadsheet):
            def batch_update(self, body):
                raise RuntimeError("quota")

        sheet = _Angry()
        ws = sheet.add_worksheet("products")
        sc.apply_category_colors(sheet, ws, ["مبلمان"])   # نباید بترکد


# --- جریانِ افزودنِ کالا -------------------------------------------------------------


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

    @property
    def markup(self):
        return self.replies[-1].get("reply_markup") if self.replies else None


class _Query:
    def __init__(self, data, message=None):
        self.data = data
        self.message = message or _Msg()
        self.edits: list = []

    async def answer(self, text=None, show_alert=False):
        return None

    async def edit_message_text(self, text, **kw):
        self.edits.append({"text": text, **kw})

    async def edit_message_reply_markup(self, reply_markup=None):
        return None


class _Bot:
    async def send_message(self, chat_id, text=None, **kw):
        return None


def _ctx(store):
    app = SimpleNamespace(
        bot_data={"store": store, "settings": Settings(bot_token="x")}, bot=_Bot()
    )
    return SimpleNamespace(application=app, bot=app.bot,
                           chat_data={}, user_data={}, args=[])


def _update(message=None, query=None):
    return SimpleNamespace(
        message=message, callback_query=query,
        effective_user=SimpleNamespace(id=UID, full_name="تست", username="t"),
        effective_chat=SimpleNamespace(id=UID, type="private", title=None),
        effective_message=message or (query.message if query else None),
    )


async def _say(ctx, text):
    msg = _Msg(text)
    await handlers.on_text(_update(message=msg), ctx)
    return msg


class TestAddProductFlow:
    async def _start(self, ctx):
        await handlers.on_product_action(_update(query=_Query("prod:add")), ctx)
        return await _say(ctx, "مبل")

    async def test_the_category_step_comes_after_the_name(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        msg = await self._start(ctx)
        assert ctx.user_data["flow"] == "prod_category"
        assert msg.replies[-1]["text"] == texts.PRODUCT_ASK_CATEGORY
        assert {"pcat:new", "pcat:skip"} <= set(_cb(msg.markup))

    async def test_previous_categories_are_offered(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        await products_service.add_product(store, UID, "میز", 1000, "مبلمان")
        msg = await self._start(ctx)
        assert "pcat:pick:0" in _cb(msg.markup)

    async def test_picking_an_existing_category(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        await products_service.add_product(store, UID, "میز", 1000, "مبلمان")
        await self._start(ctx)
        await handlers.on_product_category(_update(query=_Query("pcat:pick:0")), ctx)
        assert ctx.user_data["flow"] == "prod_price"
        await _say(ctx, "۲۵ میلیون")

        saved = next(p for p in store.list("products") if p.title == "مبل")
        assert saved.category == "مبلمان"
        assert saved.unit_price == 25_000_000

    async def test_a_brand_new_category(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        await self._start(ctx)
        query = _Query("pcat:new")
        await handlers.on_product_category(_update(query=query), ctx)
        assert ctx.user_data["flow"] == "prod_newcat"
        assert query.message.replies[-1]["text"] == texts.PRODUCT_ASK_NEW_CATEGORY

        await _say(ctx, "مبلمان")
        assert ctx.user_data["flow"] == "prod_price"
        await _say(ctx, "۲۵ میلیون")
        assert store.list("products")[0].category == "مبلمان"

    async def test_skipping_leaves_the_category_empty(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        await self._start(ctx)
        await handlers.on_product_category(_update(query=_Query("pcat:skip")), ctx)
        await _say(ctx, "۲۵ میلیون")
        product = store.list("products")[0]
        assert product.category == "" and product.unit_price == 25_000_000

    async def test_typing_a_category_instead_of_tapping(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        await self._start(ctx)
        await _say(ctx, "مبلمان")
        assert ctx.user_data["flow"] == "prod_price"
        await _say(ctx, "۲۵ میلیون")
        assert store.list("products")[0].category == "مبلمان"

    async def test_the_confirmation_mentions_the_category(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        await self._start(ctx)
        await _say(ctx, "مبلمان")
        msg = await _say(ctx, "۲۵ میلیون")
        assert "مبلمان" in msg.replies[-1]["text"]

    async def test_a_stray_category_press_is_ignored(self, store):
        ctx = _ctx(store)
        query = _Query("pcat:skip")
        await handlers.on_product_category(_update(query=query), ctx)
        assert query.message.replies == []

    async def test_a_bad_index_falls_back_to_no_category(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        await self._start(ctx)
        await handlers.on_product_category(_update(query=_Query("pcat:pick:99")), ctx)
        await _say(ctx, "۲۵ میلیون")
        assert store.list("products")[0].category == ""


class TestSummaryStaysInSync:
    async def test_adding_a_product_updates_the_summary_tab(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        await store.ensure_user_spreadsheet(UID, "تست")

        await handlers.on_product_action(_update(query=_Query("prod:add")), ctx)
        await _say(ctx, "مبل")
        await _say(ctx, "مبلمان")
        await _say(ctx, "۲۵ میلیون")

        sheet = store._client.sheets[store.get("users", UID).sheet_id]
        first = [r[0] for r in sheet.worksheet(sc.SUMMARY_SHEET_TITLE).get_all_values()]
        assert "-- مبلمان --" in first and "مبل" in first

    async def test_refresh_is_harmless_without_a_spreadsheet(self, store):
        from hesabyar.db.models import User
        await store.add("users", User(id=UID))   # بدونِ sheet_id
        assert await store.refresh_summary(UID) is False

    async def test_refresh_is_harmless_for_an_unknown_user(self, store):
        assert await store.refresh_summary(99_999) is False

    async def test_real_data_is_untouched_by_the_refresh(self, store):
        await tx.get_or_create_user(store, UID)
        await store.ensure_user_spreadsheet(UID, "تست")
        await products_service.add_product(store, UID, "مبل", 5_000_000, "مبلمان")
        await store.flush()

        sheet = store._client.sheets[store.get("users", UID).sheet_id]
        before = sheet.worksheet("products").get_all_values()
        await store.refresh_summary(UID)
        assert sheet.worksheet("products").get_all_values() == before
