"""تست‌های کاهش کامندها به ۴ تای اصلی (فاز ۵).

قرارداد: منوی «/» تلگرام فقط ۴ کامند نشان می‌دهد، ولی هیچ قابلیتی از دست
نمی‌رود — بقیه‌ی کامندها alias مخفی می‌مانند و مسیرِ اصلی‌شان دکمه‌های منوی
۶بخشیِ فاز ۳ است.
"""
import inspect
import re
from types import SimpleNamespace

from telegram.ext import ApplicationBuilder, CommandHandler

from hesabyar.bot import app, handlers, keyboards, texts

CORE = {"start", "help", "cancel", "undo"}


def _registered_commands() -> set:
    application = ApplicationBuilder().token("1:AA").build()
    handlers.register(application)
    names = set()
    for group in application.handlers.values():
        for h in group:
            if isinstance(h, CommandHandler):
                names |= set(h.commands)
    return names


def _menu_callbacks() -> set:
    menus = (keyboards.report_menu, keyboards.transactions_menu,
             keyboards.ledger_menu, keyboards.invoice_menu,
             keyboards.business_menu, keyboards.account_menu)
    return {b.callback_data for fn in menus
            for row in fn().inline_keyboard for b in row}


# --- فهرستی که به تلگرام معرفی می‌شود -------------------------------------------


class _FakeBot:
    def __init__(self):
        self.calls: list = []

    async def set_my_commands(self, commands, scope=None):
        self.calls.append((scope, [(c.command, c.description) for c in commands]))


class TestPublishedMenu:
    async def _publish(self):
        bot = _FakeBot()
        await app.publish_command_menu(bot)
        return bot

    async def test_private_menu_is_exactly_the_four(self):
        bot = await self._publish()
        private = [cmds for scope, cmds in bot.calls
                   if type(scope).__name__ == "BotCommandScopeAllPrivateChats"]
        assert len(private) == 1
        assert {c for c, _ in private[0]} == CORE

    async def test_default_scope_is_overwritten_too(self):
        """وگرنه فهرستِ بلندِ نسخه‌ی قبلی روی سرورِ تلگرام باقی می‌ماند."""
        bot = await self._publish()
        default = [cmds for scope, cmds in bot.calls if scope is None]
        assert len(default) == 1
        assert {c for c, _ in default[0]} == CORE

    async def test_group_menu_keeps_balance(self):
        """در گروه کیبوردِ منو وجود ندارد؛ /balance باید دیده شود."""
        bot = await self._publish()
        group = [cmds for scope, cmds in bot.calls
                 if type(scope).__name__ == "BotCommandScopeAllGroupChats"]
        assert len(group) == 1
        assert "balance" in {c for c, _ in group[0]}

    async def test_no_hidden_command_is_advertised(self):
        bot = await self._publish()
        advertised = {c for _, cmds in bot.calls for c, _ in cmds}
        leaked = advertised & (set(handlers.ALIAS_COMMANDS) - {"balance"})
        assert not leaked, f"هنوز تبلیغ می‌شوند: {leaked}"

    async def test_every_advertised_command_has_a_description(self):
        bot = await self._publish()
        for _, cmds in bot.calls:
            for name, desc in cmds:
                assert desc.strip(), name

    async def test_core_list_matches_the_constant(self):
        assert {name for name, _ in app.CORE_COMMANDS} == CORE


# --- alias های مخفی هنوز کار می‌کنند ---------------------------------------------


class TestAliasesStillWork:
    def test_every_alias_still_has_a_handler(self):
        registered = _registered_commands()
        missing = set(handlers.ALIAS_COMMANDS) - registered
        assert not missing, f"تایپشان دیگر کار نمی‌کند: {missing}"

    def test_core_commands_are_registered(self):
        assert CORE <= _registered_commands()

    def test_registration_covers_the_whole_map(self):
        assert _registered_commands() == set(handlers.COMMAND_HANDLERS)

    def test_public_and_alias_lists_are_disjoint_and_complete(self):
        assert not set(handlers.PUBLIC_COMMANDS) & set(handlers.ALIAS_COMMANDS)
        assert (set(handlers.PUBLIC_COMMANDS) | set(handlers.ALIAS_COMMANDS)
                == set(handlers.COMMAND_HANDLERS))

    def test_public_list_matches_what_is_advertised(self):
        assert set(handlers.PUBLIC_COMMANDS) == CORE

    def test_no_alias_points_at_a_missing_function(self):
        for name, fn in handlers.COMMAND_HANDLERS.items():
            assert inspect.iscoroutinefunction(fn), name


# --- هیچ قابلیتی از منو بیرون نیفتاده ------------------------------------------


#: هر alias ⇒ دکمه‌ای که همان کار را از منو انجام می‌دهد.
MENU_ROUTE = {
    "export": "act:export",
    "search": "act:search",
    "backup": "act:backup",
    "dashboard": "dash:show",
    "list": "act:list",
    "products": "act:products",
    "industry": "act:industry",
    "invoices": "act:invoices",
    "dollar": "act:dollar",
    "rate": "act:rate",
    "remind": "act:remind",
    "branches": "act:branches",
    "join": "act:join",
    "leave": "act:leave",
}

#: استثناهای آگاهانه — جایشان منوی خصوصی نیست.
NO_MENU = {
    "balance": "مخصوصِ گروه است و آنجا کیبوردِ منو وجود ندارد",
    "pilot": "فقط ادمین؛ عمداً پنهان است",
}


class TestNothingBecameUnreachable:
    def test_every_alias_is_either_in_a_menu_or_a_known_exception(self):
        covered = set(MENU_ROUTE) | set(NO_MENU)
        assert set(handlers.ALIAS_COMMANDS) == covered, (
            f"بی‌مسیر: {set(handlers.ALIAS_COMMANDS) - covered}"
        )

    def test_each_route_button_really_exists_in_a_menu(self):
        buttons = _menu_callbacks()
        missing = {cmd: cb for cmd, cb in MENU_ROUTE.items() if cb not in buttons}
        assert not missing, f"دکمه‌شان در هیچ منویی نیست: {missing}"

    def test_menu_actions_are_dispatched(self):
        """هر ``act:*`` منو باید در ``on_menu_action`` هندل شود."""
        source = inspect.getsource(handlers.on_menu_action)
        for cmd, cb in MENU_ROUTE.items():
            if not cb.startswith("act:"):
                continue
            action = cb.split(":", 1)[1]
            assert f'"{action}"' in source, f"{cmd} ⇒ {cb} بی‌هندلر است"

    def test_group_command_is_advertised_where_it_is_usable(self):
        assert "balance" in {name for name, _ in app.GROUP_COMMANDS}


# --- متن راهنما -----------------------------------------------------------------


#: متن‌هایی که عمداً هنوز یک کامندِ مخفی را نام می‌برند، و دلیلش.
TEXTS_ALLOWED_TO_MENTION = {
    "BRANCH_CREATED": "دستورالعملی است که به یک نفرِ دیگر داده می‌شود",
    "JOIN_ASK_CODE": "همان‌جا راه دکمه‌ای را هم می‌گوید",
    "GROUP_INTRO": "در گروه، /balance واقعاً در منوی «/» هست",
    "RATE_NONE": "ثبتِ نرخ فقط با کامند و فقط برای ادمین است",
    "RATE_BAD": "ثبتِ نرخ فقط با کامند و فقط برای ادمین است",
    "SEARCH_USAGE": "فقط وقتی دیده می‌شود که کسی خودش /search تایپ کرده",
}


class TestNoStaleCommandAdvertising:
    def test_texts_do_not_point_users_at_hidden_commands(self):
        """جلوگیری از ارجاعِ جامانده به کامندی که دیگر در منوی «/» نیست."""
        alias = set(handlers.ALIAS_COMMANDS)
        offenders = {}
        for name in dir(texts):
            if name.startswith("_") or name in TEXTS_ALLOWED_TO_MENTION:
                continue
            value = getattr(texts, name)
            if not isinstance(value, str):
                continue
            hits = {c for c in alias if re.search(rf"/{c}\b", value)}
            if hits:
                offenders[name] = sorted(hits)
        assert not offenders, f"ارجاع به کامندِ مخفی: {offenders}"

    def test_the_allowlist_has_no_dead_entries(self):
        for name in TEXTS_ALLOWED_TO_MENTION:
            value = getattr(texts, name, "")
            assert any(re.search(rf"/{c}\b", value)
                       for c in handlers.ALIAS_COMMANDS), f"{name} دیگر لازم نیست"


class TestHelpText:
    def test_does_not_list_the_hidden_commands(self):
        listed = [c for c in handlers.ALIAS_COMMANDS if f"/{c}" in texts.HELP]
        assert not listed, f"هنوز در راهنما تبلیغ می‌شوند: {listed}"

    def test_mentions_all_four_core_commands(self):
        for name in CORE:
            assert f"/{name}" in texts.HELP, name

    def test_points_at_the_bottom_menu(self):
        assert "منوی پایین" in texts.HELP

    def test_is_much_shorter_than_a_twenty_command_list(self):
        assert texts.HELP.count("• /") == len(CORE)

    async def test_help_still_sends_the_main_keyboard(self, store):
        replies: list = []

        class _Msg:
            async def reply_text(self, text, **kw):
                replies.append({"text": text, **kw})

        ctx = SimpleNamespace(
            application=SimpleNamespace(bot_data={"store": store}),
            user_data={}, chat_data={}, args=[],
        )
        update = SimpleNamespace(message=_Msg())
        await handlers.help_cmd(update, ctx)
        markup = replies[-1]["reply_markup"]
        labels = [b.text for row in markup.keyboard for b in row]
        assert labels[0] == texts.BTN_REPORT
        assert len(labels) == 6
