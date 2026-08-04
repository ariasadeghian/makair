"""تست‌های منوی ۶بخشی و زیرمنوهای شیشه‌ای (فاز ۳)."""
from types import SimpleNamespace

from hesabyar.bot import handlers, keyboards, texts
from hesabyar.config import Settings
from hesabyar.services import transactions as tx

UID = 6001

SUBMENUS = {
    "report": keyboards.report_menu,
    "transactions": keyboards.transactions_menu,
    "ledger": keyboards.ledger_menu,
    "invoice": keyboards.invoice_menu,
    "business": keyboards.business_menu,
    "account": keyboards.account_menu,
}


def _cb(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


# --- منوی اصلی ----------------------------------------------------------------


class TestMainMenu:
    def test_six_buttons_two_per_row(self):
        rows = keyboards.main_menu().keyboard
        assert len(rows) == 3
        assert all(len(r) == 2 for r in rows)
        labels = [b.text for r in rows for b in r]
        assert labels == [
            texts.BTN_REPORT, texts.BTN_TRANSACTIONS,
            texts.BTN_LEDGER, texts.BTN_INVOICE,
            texts.BTN_BUSINESS, texts.BTN_ACCOUNT,
        ]

    def test_labels_are_unique(self):
        labels = [b.text for r in keyboards.main_menu().keyboard for b in r]
        assert len(labels) == len(set(labels))

    def test_every_button_maps_to_a_submenu(self):
        labels = [b.text for r in keyboards.main_menu().keyboard for b in r]
        assert set(labels) == set(handlers._MAIN_MENU)


# --- زیرمنوها -----------------------------------------------------------------


class TestSubmenus:
    def test_all_have_back_to_main(self):
        for name, fn in SUBMENUS.items():
            assert "menu:main" in _cb(fn()), f"{name} دکمه‌ی بازگشت ندارد"

    def test_back_is_last_row(self):
        for name, fn in SUBMENUS.items():
            last = fn().inline_keyboard[-1]
            assert len(last) == 1 and last[0].callback_data == "menu:main", name

    def test_no_empty_submenu(self):
        for name, fn in SUBMENUS.items():
            assert len(_cb(fn())) >= 2, name

    def test_report_menu_keeps_existing_callbacks(self):
        data = _cb(keyboards.report_menu())
        # منطق قبلی دست‌نخورده مانده است
        assert {"report:day", "report:week", "report:month", "dash:show"} <= set(data)

    def test_ledger_menu_keeps_existing_and_adds_remind(self):
        data = _cb(keyboards.ledger_menu())
        assert {"ledger:add:receivable", "ledger:add:payable",
                "ledger:list", "ledger:statement"} <= set(data)
        assert "act:remind" in data

    def test_expected_actions_present(self):
        expected = {
            "report": {"act:export"},
            "transactions": {"act:list", "act:search", "act:undo"},
            "invoice": {"act:newinvoice", "act:products", "act:invoices"},
            "business": {"act:industry", "act:branches", "act:join",
                         "act:leave", "act:dollar", "act:rate"},
            "account": {"act:plans", "act:backup", "act:help"},
        }
        for name, wanted in expected.items():
            assert wanted <= set(_cb(SUBMENUS[name]())), name

    def test_every_action_has_a_dispatch_path(self):
        """هیچ دکمه‌ای نباید بی‌اثر باشد."""
        actions = set()
        for fn in SUBMENUS.values():
            actions |= {d.split(":", 1)[1] for d in _cb(fn()) if d.startswith("act:")}
        handled = {
            "search", "join", "newinvoice", "plans", "rate",
            "export", "list", "undo", "products", "invoices", "remind",
            "industry", "branches", "leave", "dollar", "backup", "help",
        }
        assert actions <= handled, f"بدونِ هندلر: {actions - handled}"


# --- رفتار در زمان اجرا ---------------------------------------------------------


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
        return SimpleNamespace(message_id=2)


class _Query:
    def __init__(self, data, message=None):
        self.data = data
        self.message = message or _Msg()
        self.edits: list = []

    async def answer(self, text=None, show_alert=False):
        return None

    async def edit_message_text(self, text, **kw):
        self.edits.append(text)


class _Bot:
    def __init__(self):
        self.sent: list = []

    async def send_message(self, chat_id, text=None, **kw):
        self.sent.append({"chat_id": chat_id, "text": text, **kw})


def _ctx(store, bot=None):
    app = SimpleNamespace(
        bot_data={"store": store, "settings": Settings(bot_token="x")},
        bot=bot or _Bot(),
    )
    return SimpleNamespace(application=app, bot=app.bot,
                           chat_data={}, user_data={}, args=[])


def _update(message=None, query=None):
    return SimpleNamespace(
        message=message, callback_query=query,
        effective_user=SimpleNamespace(id=UID, full_name="تست", username="t"),
        effective_chat=SimpleNamespace(id=UID, type="private", title=None),
        effective_message=message,
    )


class TestMenuRouting:
    async def test_each_main_button_opens_its_submenu(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        for label, (title, markup_fn) in handlers._MAIN_MENU.items():
            msg = _Msg(label)
            await handlers.on_text(_update(message=msg), ctx)
            assert msg.replies, f"«{label}» جوابی نداد"
            reply = msg.replies[-1]
            assert reply["text"] == title
            assert _cb(reply["reply_markup"]) == _cb(markup_fn())

    async def test_back_to_main_restores_reply_keyboard(self, store):
        bot = _Bot()
        ctx = _ctx(store, bot=bot)
        query = _Query("menu:main")
        await handlers.on_menu(_update(query=query), ctx)
        assert bot.sent, "کیبورد اصلی دوباره فرستاده نشد"
        markup = bot.sent[-1]["reply_markup"]
        assert [b.text for r in markup.keyboard for b in r][0] == texts.BTN_REPORT

    async def test_back_clears_a_half_finished_flow(self, store):
        ctx = _ctx(store)
        ctx.user_data["flow"] = "invoice_customer"
        ctx.user_data["invoice"] = {"items": [{"x": 1}]}
        await handlers.on_menu(_update(query=_Query("menu:main")), ctx)
        assert "flow" not in ctx.user_data
        assert "invoice" not in ctx.user_data

    async def test_search_action_starts_a_flow_then_runs(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        query = _Query("act:search")
        await handlers.on_menu_action(_update(query=query), ctx)
        assert ctx.user_data.get("flow") == "search_query"
        assert query.message.replies[-1]["text"] == texts.SEARCH_ASK

        # حالا کلمه را تایپ می‌کند ⇒ جست‌وجو اجرا و flow پاک می‌شود
        msg = _Msg("اجاره")
        await handlers.on_text(_update(message=msg), ctx)
        assert "flow" not in ctx.user_data
        assert msg.replies

    async def test_new_invoice_action_starts_builder(self, store):
        ctx = _ctx(store)
        query = _Query("act:newinvoice")
        await handlers.on_menu_action(_update(query=query), ctx)
        assert ctx.user_data.get("flow") == "invoice_customer"
        assert query.message.replies[-1]["text"] == texts.INVOICE_ASK_CUSTOMER

    async def test_list_action_reuses_existing_command(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        query = _Query("act:list")
        await handlers.on_menu_action(_update(query=query), ctx)
        # همان پیام «هنوز تراکنشی ثبت نکرده‌اید» از list_cmd
        assert query.message.replies
        assert "تراکنش" in query.message.replies[-1]["text"]

    async def test_unknown_action_is_silent(self, store):
        ctx = _ctx(store)
        query = _Query("act:nope")
        await handlers.on_menu_action(_update(query=query), ctx)
        assert query.message.replies == []
