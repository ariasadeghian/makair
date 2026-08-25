"""تشخیصِ نیتِ طلب/بدهی از جمله‌ی آزاد — نباید هزینه/درآمد بشود.

قبل از این، «من ۲ میلیون به رضا بدهکارم» می‌افتاد دستِ پارسرِ عمومیِ
تراکنش (که کلیدواژه‌ای برای طلب/بدهی ندارد) و به‌عنوان هزینه‌ی «متفرقه»
ثبت می‌شد — یعنی یک وعده‌ی پرداخت، بی‌سروصدا، تبدیل به خرج می‌شد. این
باگِ درستیِ داده است، نه ظاهری.

سه لایه تست می‌شود:

۱. ``TestParser`` — خودِ ``ledger_nlp`` جدا، روی نمونه‌های تیکت + رقمِ
   عربی/فارسی + مبلغِ نوشتاری + فاصله‌گذاریِ نامرتب.
۲. ``TestRouting`` — مسیریابیِ سطحِ بات: جمله‌ی طلب/بدهی باید کارتِ تأیید
   بدهد، نه پیامِ «هزینه ثبت شد».
۳. ``TestPersistence`` — تأیید باید فقط روی دفتر بنشیند: نه تراکنشِ
   تکراری، نه اثر روی جمعِ گزارش‌ها، و تسویه دست‌نخورده بماند.
"""
from types import SimpleNamespace

from hesabyar.bot import handlers, keyboards, texts
from hesabyar.config import Settings
from hesabyar.core import jalali, ledger_nlp
from hesabyar.db.models import Direction
from hesabyar.services import ledger as ledger_service
from hesabyar.services import transactions as tx

UID = 55_701

CANCEL = keyboards.CANCEL_DATA


def _cb(markup):
    if markup is None:
        return []
    return [b.callback_data for row in markup.inline_keyboard for b in row]


# --- ۱) پارسر، جدا از بات ------------------------------------------------------------


class TestParser:
    """نمونه‌های دقیقِ تیکت — هرکدام جهت، طرف‌حساب و مبلغِ مشخص."""

    def test_payable_i_owe_reza_with_subject(self):
        r = ledger_nlp.parse_ledger_text("من ۲ میلیون به رضا بدهکارم")
        assert r.direction == Direction.PAYABLE
        assert r.party_name == "رضا"
        assert r.amount == 2_000_000

    def test_payable_i_owe_reza_no_subject(self):
        r = ledger_nlp.parse_ledger_text("به رضا ۲ میلیون بدهکارم")
        assert r.direction == Direction.PAYABLE
        assert r.party_name == "رضا"
        assert r.amount == 2_000_000

    def test_payable_debt_noun_construction(self):
        r = ledger_nlp.parse_ledger_text("۲ میلیون به رضا بدهی دارم")
        assert r.direction == Direction.PAYABLE
        assert r.party_name == "رضا"
        assert r.amount == 2_000_000

    def test_payable_became_indebted(self):
        r = ledger_nlp.parse_ledger_text("به حسن ۳ میلیون بدهکار شدم")
        assert r.direction == Direction.PAYABLE
        assert r.party_name == "حسن"
        assert r.amount == 3_000_000

    def test_payable_must_give(self):
        r = ledger_nlp.parse_ledger_text("من باید ۵ میلیون به علی بدهم")
        assert r.direction == Direction.PAYABLE
        assert r.party_name == "علی"
        assert r.amount == 5_000_000

    def test_payable_debt_dari_variant(self):
        r = ledger_nlp.parse_ledger_text("به حسن ۳ میلیون بدهی دارم")
        assert r.direction == Direction.PAYABLE
        assert r.party_name == "حسن"

    def test_receivable_third_person_colloquial(self):
        r = ledger_nlp.parse_ledger_text("علی ۵ میلیون به من بدهکاره")
        assert r.direction == Direction.RECEIVABLE
        assert r.party_name == "علی"
        assert r.amount == 5_000_000

    def test_receivable_third_person_formal(self):
        r = ledger_nlp.parse_ledger_text("حسن ۴ میلیون تومان به من بدهکار است")
        assert r.direction == Direction.RECEIVABLE
        assert r.party_name == "حسن"
        assert r.amount == 4_000_000

    def test_receivable_claim_from(self):
        r = ledger_nlp.parse_ledger_text("از علی ۳ میلیون طلب دارم")
        assert r.direction == Direction.RECEIVABLE
        assert r.party_name == "علی"
        assert r.amount == 3_000_000

    def test_receivable_creditor_noun(self):
        r = ledger_nlp.parse_ledger_text("۳ میلیون از رضا طلبکارم")
        assert r.direction == Direction.RECEIVABLE
        assert r.party_name == "رضا"
        assert r.amount == 3_000_000

    def test_receivable_must_give_third_person(self):
        r = ledger_nlp.parse_ledger_text("رضا باید ۲ میلیون به من بدهد")
        assert r.direction == Direction.RECEIVABLE
        assert r.party_name == "رضا"
        assert r.amount == 2_000_000

    # --- همان کلمه، جهتِ برعکس — دقیقاً چیزی که تیکت رویش تأکید کرده ---------------

    def test_same_word_opposite_direction_receivable(self):
        r = ledger_nlp.parse_ledger_text("علی ۲ میلیون به من بدهکار است")
        assert r.direction == Direction.RECEIVABLE
        assert r.party_name == "علی"

    def test_same_word_opposite_direction_payable(self):
        r = ledger_nlp.parse_ledger_text("من ۲ میلیون به علی بدهکارم")
        assert r.direction == Direction.PAYABLE
        assert r.party_name == "علی"

    # --- تراکنش‌های عادی: نباید هیچ‌کدام دفتری تشخیص داده شوند --------------------

    def test_ordinary_payment_is_not_ledger(self):
        assert ledger_nlp.parse_ledger_text("۲ میلیون به رضا پرداخت کردم") is None

    def test_ordinary_sale_is_not_ledger(self):
        assert ledger_nlp.parse_ledger_text("امروز ۲ میلیون فروختم") is None

    def test_ordinary_expense_is_not_ledger(self):
        assert ledger_nlp.parse_ledger_text("۵۰۰ هزار خرج کردم") is None

    def test_ordinary_bill_is_not_ledger(self):
        assert ledger_nlp.parse_ledger_text("قبض برق ۳۰۰ هزار پرداختم") is None

    def test_looks_like_ledger_matches_the_gate(self):
        """دروازه‌ی ارزان و پارسِ کامل نباید در نتیجه با هم اختلاف داشته باشند."""
        ledger_texts = ["من ۲ میلیون به رضا بدهکارم", "از علی ۳ میلیون طلب دارم"]
        ordinary_texts = ["۲ میلیون به رضا پرداخت کردم", "امروز ۲ میلیون فروختم"]
        for t in ledger_texts:
            assert ledger_nlp.looks_like_ledger(t) is True
        for t in ordinary_texts:
            assert ledger_nlp.looks_like_ledger(t) is False

    # --- ارقام، فاصله‌گذاری، مبلغِ نوشتاری ------------------------------------------

    def test_arabic_indic_digits(self):
        r = ledger_nlp.parse_ledger_text("من ٢ میلیون به رضا بدهکارم")
        assert r.direction == Direction.PAYABLE
        assert r.amount == 2_000_000

    def test_persian_digits(self):
        r = ledger_nlp.parse_ledger_text("من ۲ میلیون به رضا بدهکارم")
        assert r.amount == 2_000_000

    def test_messy_spacing(self):
        r = ledger_nlp.parse_ledger_text("من   ۲ میلیون  به   رضا   بدهکارم")
        assert r.direction == Direction.PAYABLE
        assert r.party_name == "رضا"
        assert r.amount == 2_000_000

    def test_amount_in_words(self):
        r = ledger_nlp.parse_ledger_text("من دو میلیون به رضا بدهکارم")
        assert r.amount == 2_000_000

    def test_amount_in_words_receivable(self):
        r = ledger_nlp.parse_ledger_text("از علی سه میلیون طلب دارم")
        assert r.direction == Direction.RECEIVABLE
        assert r.amount == 3_000_000

    def test_grouped_digits_with_separators(self):
        r = ledger_nlp.parse_ledger_text("به رضا ۲,۰۰۰,۰۰۰ تومان بدهکارم")
        assert r.amount == 2_000_000

    def test_no_amount_returns_none(self):
        """بدونِ مبلغ چیزی برای ثبت نیست — نباید حدس بزند."""
        assert ledger_nlp.parse_ledger_text("علی به من بدهکار است") is None
        assert ledger_nlp.parse_ledger_text("من به علی بدهکارم") is None

    def test_empty_text(self):
        assert ledger_nlp.parse_ledger_text("") is None
        assert ledger_nlp.parse_ledger_text(None) is None

    def test_honorific_party_name(self):
        r = ledger_nlp.parse_ledger_text("به آقای رضایی ۲ میلیون بدهکارم")
        assert r.party_name == "آقای رضایی"


# --- ۲) مسیریابیِ سطحِ بات -------------------------------------------------------------


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
        self.markup_edits: list = []

    async def answer(self, text=None, show_alert=False):
        return None

    async def edit_message_text(self, text, **kw):
        self.edits.append({"text": text, **kw})

    async def edit_message_reply_markup(self, reply_markup=None):
        self.markup_edits.append(reply_markup)


class _Bot:
    def __init__(self):
        self.sent: list = []

    async def send_message(self, chat_id, text=None, **kw):
        self.sent.append({"chat_id": chat_id, "text": text, **kw})


def _ctx(store, **settings):
    app = SimpleNamespace(
        bot_data={"store": store, "settings": Settings(bot_token="x", **settings)},
        bot=_Bot(),
    )
    return SimpleNamespace(application=app, bot=app.bot,
                           chat_data={}, user_data={}, args=[])


def _update(message=None, query=None):
    msg = message or (query.message if query else None)
    return SimpleNamespace(
        message=message, callback_query=query,
        effective_user=SimpleNamespace(id=UID, full_name="تست", username="t"),
        effective_chat=SimpleNamespace(id=UID, type="private", title=None),
        effective_message=msg,
    )


async def _type(ctx, text):
    msg = _Msg(text)
    await handlers.on_text(_update(message=msg), ctx)
    return msg


async def _press(ctx, data, message=None):
    query = _Query(data, message=message)
    await handlers.on_ledger_nlp(_update(query=query), ctx)
    return query


class TestRouting:
    async def test_ledger_sentence_offers_a_confirm_card_not_an_expense(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        msg = await _type(ctx, "من ۲ میلیون به رضا بدهکارم")
        assert "هزینه ثبت شد" not in msg.replies[-1]["text"]
        assert CANCEL in _cb(msg.markup)
        assert "lednlp:confirm" in _cb(msg.markup)
        assert store.list("transactions") == []
        assert store.list("ledger_entries") == []

    async def test_confirm_card_shows_correct_direction_and_party(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        msg = await _type(ctx, "حسن ۴ میلیون تومان به من بدهکار است")
        body = msg.replies[-1]["text"]
        assert "حسن" in body
        assert texts.LEDNLP_HEADER_RECEIVABLE in body

    async def test_payable_card_uses_payable_header(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        msg = await _type(ctx, "به رضا ۲ میلیون بدهکارم")
        body = msg.replies[-1]["text"]
        assert texts.LEDNLP_HEADER_PAYABLE in body
        assert "رضا" in body

    async def test_ordinary_expense_is_unaffected(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        await _type(ctx, "۵۰۰ هزار خرج کردم")
        rows = store.list("transactions")
        assert len(rows) == 1
        assert rows[0].kind == "expense"

    async def test_ordinary_income_is_unaffected(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        await _type(ctx, "امروز ۲ میلیون فروختم")
        rows = store.list("transactions")
        assert len(rows) == 1
        assert rows[0].kind == "income"

    async def test_payment_to_a_named_person_is_still_an_expense(self, store):
        """این خطِ فاصلِ ظریف است: «پرداخت کردم» یعنی تمام‌شده، نه بدهی."""
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        await _type(ctx, "۲ میلیون به رضا پرداخت کردم")
        assert len(store.list("transactions")) == 1
        assert store.list("ledger_entries") == []


# --- ۳) ثبت: فقط دفتر، نه تراکنش، نه اثر روی گزارش -------------------------------------


class TestPersistence:
    async def test_confirm_creates_only_a_ledger_entry(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        await _type(ctx, "من ۲ میلیون به رضا بدهکارم")
        await _press(ctx, "lednlp:confirm")
        assert ctx.user_data["flow"] == "ledger_due"
        await _type(ctx, "بدون تاریخ")

        assert store.list("transactions") == [], "نباید تراکنشِ تکراری ساخته شود"
        entries = store.list("ledger_entries")
        assert len(entries) == 1
        assert entries[0].direction == Direction.PAYABLE
        assert entries[0].party_name == "رضا"
        assert entries[0].amount == 2_000_000

    async def test_confirm_receivable_direction_is_exact(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        await _type(ctx, "از علی ۳ میلیون طلب دارم")
        await _press(ctx, "lednlp:confirm")
        await _type(ctx, "بدون تاریخ")
        entries = store.list("ledger_entries")
        assert len(entries) == 1
        assert entries[0].direction == Direction.RECEIVABLE
        assert entries[0].party_name == "علی"
        assert entries[0].amount == 3_000_000

    async def test_cancel_on_the_confirm_card_creates_nothing(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        await _type(ctx, "من ۲ میلیون به رضا بدهکارم")
        assert "lednlp" in ctx.user_data
        query = _Query(CANCEL)
        await handlers.on_flow_cancel(_update(query=query), ctx)
        assert "lednlp" not in ctx.user_data
        assert "flow" not in ctx.user_data
        assert store.list("ledger_entries") == []
        assert store.list("transactions") == []

    async def test_edit_manually_routes_into_the_manual_flow(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        await _type(ctx, "من ۲ میلیون به رضا بدهکارم")
        await _press(ctx, "lednlp:edit")
        assert ctx.user_data["flow"] == "ledger_party"
        assert ctx.user_data["ledger"] == {"direction": Direction.PAYABLE}
        assert "lednlp" not in ctx.user_data
        # از همین‌جا جریانِ دستیِ معمولی ادامه پیدا می‌کند
        msg = await _type(ctx, "کیان")
        assert ctx.user_data["flow"] == "ledger_amount"
        msg = await _type(ctx, "۵۰۰ هزار")
        assert ctx.user_data["flow"] == "ledger_due"
        await _type(ctx, "بدون تاریخ")
        entries = store.list("ledger_entries")
        assert len(entries) == 1
        assert entries[0].party_name == "کیان"
        assert entries[0].amount == 500_000

    async def test_stale_draft_after_restart_does_not_crash(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        query = await _press(ctx, "lednlp:confirm")
        assert texts.LEDNLP_GONE in query.edits[-1]["text"]

    async def test_reporting_totals_unaffected_by_open_ledger_entries(self, store):
        """یک طلبِ باز نباید در جمعِ درآمد/هزینه دیده شود — دو دفترِ جدا."""
        now = jalali.now()
        await tx.add_transaction(store, UID, kind="income", amount=1_000_000,
                                 category="فروش کالا", description="", occurred_at=now)
        before = tx.summary(store, UID, now.replace(hour=0, minute=0),
                            now.replace(hour=23, minute=59))

        ctx = _ctx(store)
        await _type(ctx, "من ۲ میلیون به رضا بدهکارم")
        await _press(ctx, "lednlp:confirm")
        await _type(ctx, "بدون تاریخ")

        after = tx.summary(store, UID, now.replace(hour=0, minute=0),
                           now.replace(hour=23, minute=59))
        assert after == before, "ثبتِ یک بدهیِ باز نباید جمعِ گزارش را عوض کند"
        assert store.list("ledger_entries") != []

    async def test_settlement_logic_is_untouched(self, store):
        """تسویه هنوز روی رکوردِ ساخته‌شده از NLP کار می‌کند — مسیرِ ثبت یکی است."""
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        await _type(ctx, "به رضا ۲ میلیون بدهکارم")
        await _press(ctx, "lednlp:confirm")
        await _type(ctx, "بدون تاریخ")
        entry = store.list("ledger_entries")[0]
        assert entry.is_settled is False

        settled = await ledger_service.settle(store, entry.id, UID, jalali.now())
        assert settled is not None
        assert settled.is_settled is True
        assert ledger_service.list_open(store, UID) == []
