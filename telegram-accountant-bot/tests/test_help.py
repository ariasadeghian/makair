"""تست‌های راهنما و پیامِ «متوجه نشدم» (فاز ۷).

قاعده‌ی اصلی: هر مثالی که راهنما نشان می‌دهد باید واقعاً پارس شود. راهنمایی
که به کاربر فرمتی یاد بدهد که بات نمی‌فهمد، از نبودش بدتر است.
"""
import re
from types import SimpleNamespace

import pytest

from hesabyar.bot import handlers, keyboards, texts
from hesabyar.config import Settings
from hesabyar.core import invoice_nlp, jalali, nlp
from hesabyar.db.models import Kind
from hesabyar.services import transactions as tx

UID = 9001


def _plain(example: str) -> str:
    """مثال را از گیومه‌ی فارسی بیرون می‌آورد."""
    return example.strip("«».").strip()


def _examples_in(text: str) -> list[str]:
    """مثال‌های قابل‌تایپِ داخل «…».

    گیومه در متن‌های فارسی برای نامِ دکمه‌ها هم به کار می‌رود («📊 گزارش»)؛
    مثالِ واقعی همیشه مبلغ دارد، پس فقط عبارت‌های عددی را برمی‌داریم.
    """
    quoted = [m.strip() for m in re.findall(r"«([^»]+)»", text)]
    return [q for q in quoted if re.search(r"[\d۰-۹]", q)]


# --- مثال‌های راهنما واقعاً کار می‌کنند -------------------------------------------


class TestDocumentedExamplesActuallyParse:
    @pytest.mark.parametrize("example", texts.WRITE_EXAMPLES_TX)
    def test_transaction_examples(self, example):
        parsed = nlp.parse_transaction(_plain(example), base=jalali.now())
        assert parsed is not None, example
        assert parsed.amount > 0
        assert parsed.kind in (Kind.INCOME, Kind.EXPENSE)

    @pytest.mark.parametrize("example", texts.WRITE_EXAMPLES_INVOICE)
    def test_invoice_examples(self, example):
        parsed = invoice_nlp.parse_invoice_text(_plain(example))
        assert parsed is not None, example
        assert parsed.customer_name
        assert parsed.items and all(i.unit_price > 0 for i in parsed.items)

    def test_every_example_inside_the_help_text_parses(self):
        """هیچ مثالی در راهنما نباید مرده باشد."""
        dead = []
        for example in _examples_in(texts.HELP):
            if "[" in example or "…" in example:   # قالبِ نمادین، نه مثالِ واقعی
                continue
            text = _plain(example)
            if invoice_nlp.looks_like_invoice(text):
                ok = invoice_nlp.parse_invoice_text(text) is not None
            else:
                ok = nlp.parse_transaction(text, base=jalali.now()) is not None
            if not ok:
                dead.append(example)
        assert not dead, f"این مثال‌ها پارس نمی‌شوند: {dead}"

    def test_onboarding_invoice_example_parses(self):
        for example in _examples_in(texts.ONBOARD_DONE):
            if "{" in example:                      # جای‌گذاریِ صنفی
                continue
            assert invoice_nlp.parse_invoice_text(_plain(example)) is not None, example

    @pytest.mark.parametrize("message", [texts.UNKNOWN_INPUT, texts.UNKNOWN_INVOICE_INPUT])
    def test_examples_in_the_guidance_messages_parse(self, message):
        for example in _examples_in(message):
            text = _plain(example)
            ok = (invoice_nlp.parse_invoice_text(text) is not None
                  or nlp.parse_transaction(text, base=jalali.now()) is not None)
            assert ok, example


# --- محتوای راهنما --------------------------------------------------------------


class TestHelpContent:
    def test_has_the_write_it_directly_section(self):
        assert "می‌تونی مستقیم بنویسی" in texts.HELP

    def test_shows_both_kinds_of_example(self):
        for example in texts.WRITE_EXAMPLES_TX + texts.WRITE_EXAMPLES_INVOICE:
            assert example in texts.HELP, example

    def test_has_at_least_four_written_examples(self):
        assert len(_examples_in(texts.HELP)) >= 4

    def test_mentions_that_invoices_are_confirmed_first(self):
        assert "تأیید" in texts.HELP


# --- پیامِ «متوجه نشدم» ---------------------------------------------------------


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
    def __init__(self):
        self.sent: list = []

    async def send_message(self, chat_id, text=None, **kw):
        self.sent.append({"chat_id": chat_id, "text": text, **kw})

    async def edit_message_text(self, **kw):
        return None


def _ctx(store):
    app = SimpleNamespace(
        bot_data={"store": store, "settings": Settings(bot_token="x")},
        bot=_Bot(),
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


async def _say(ctx, text):
    msg = _Msg(text)
    await handlers.on_text(_update(msg), ctx)
    return msg


def _cb(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


class TestGuidanceOnFailedParse:
    async def test_gibberish_gets_the_transaction_guidance(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        msg = await _say(ctx, "یه چیزی بگو ببینم")
        reply = msg.replies[-1]
        assert reply["text"] == texts.UNKNOWN_INPUT
        assert store.list("transactions") == []

    async def test_guidance_carries_a_submenu_so_the_user_is_not_stuck(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        msg = await _say(ctx, "یه چیزی بگو ببینم")
        data = _cb(msg.replies[-1]["reply_markup"])
        assert data == _cb(keyboards.transactions_menu())
        assert "menu:main" in data, "راه بازگشت ندارد"

    async def test_a_failed_invoice_gets_invoice_guidance_and_invoice_menu(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        msg = await _say(ctx, "فاکتور چی شد بالاخره؟")
        reply = msg.replies[-1]
        assert reply["text"] == texts.UNKNOWN_INVOICE_INPUT
        assert _cb(reply["reply_markup"]) == _cb(keyboards.invoice_menu())

    async def test_the_two_messages_are_different(self):
        assert texts.UNKNOWN_INPUT != texts.UNKNOWN_INVOICE_INPUT


class TestGuidanceDoesNotFireWhenItShouldNot:
    async def test_not_when_a_transaction_parses(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        msg = await _say(ctx, "۵۰۰ هزار خرید مواد اولیه")
        assert msg.replies[-1]["text"] != texts.UNKNOWN_INPUT
        assert len(store.list("transactions")) == 1

    async def test_not_when_an_invoice_parses(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        msg = await _say(ctx, "فاکتور برای علی، ۲ عدد صندلی ۵۰۰ هزار تومانی")
        assert msg.replies[-1]["text"] not in (
            texts.UNKNOWN_INPUT, texts.UNKNOWN_INVOICE_INPUT
        )
        assert ctx.user_data.get("invnlp")

    @pytest.mark.parametrize("flow,payload", [
        ("invoice_customer", {"invoice": {"items": [], "discount": 0, "shipping": 0}}),
        ("ledger_party", {"ledger": {"direction": "receivable"}}),
        ("prod_name", {}),
        ("statement_party", {}),
        ("search_query", {}),
        ("join_code", {}),
        ("onboarding", {}),
    ])
    async def test_not_in_the_middle_of_another_flow(self, store, flow, payload):
        """وسطِ یک جریان، متنِ نامفهوم متعلق به همان جریان است."""
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        ctx.user_data["flow"] = flow
        ctx.user_data.update(payload)
        msg = await _say(ctx, "یه چیزی بگو ببینم")
        texts_sent = [r["text"] for r in msg.replies]
        assert texts.UNKNOWN_INPUT not in texts_sent, flow
        assert texts.UNKNOWN_INVOICE_INPUT not in texts_sent, flow

    async def test_not_when_a_main_menu_button_is_pressed(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        for label in handlers._MAIN_MENU:
            msg = await _say(ctx, label)
            assert msg.replies[-1]["text"] != texts.UNKNOWN_INPUT, label

    async def test_group_messages_never_get_this_guidance(self, store):
        """در گروه، پیامِ نامرتبط باید بی‌جواب بماند، نه اینکه راهنما بیاید."""
        ctx = _ctx(store)
        message = _Msg("یه چیزی بگو ببینم")
        message.chat = SimpleNamespace(id=-100, type="supergroup", title="گروه")
        message.chat_id = -100
        update = SimpleNamespace(
            message=message, callback_query=None,
            effective_user=SimpleNamespace(id=UID, full_name="تست", username="t"),
            effective_chat=SimpleNamespace(id=-100, type="supergroup", title="گروه"),
            effective_message=message,
        )
        await handlers.on_group_message(update, ctx)
        sent = [r["text"] for r in message.replies]
        assert texts.UNKNOWN_INPUT not in sent
        assert texts.UNKNOWN_INVOICE_INPUT not in sent
