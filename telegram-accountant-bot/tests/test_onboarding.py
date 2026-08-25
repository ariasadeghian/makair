"""تست‌های ویزاردِ شروعِ کار در اولین /start (فاز ۱۲)."""
from types import SimpleNamespace

from hesabyar.bot import handlers, keyboards, texts
from hesabyar.config import Settings
from hesabyar.core import industries
from hesabyar.services import transactions as tx

UID = 14_001


def _cb(markup):
    """callback_dataهای یک کیبورد شیشه‌ای (کیبورد پایین ⇒ فهرست خالی)."""
    rows = getattr(markup, "inline_keyboard", None)
    return [b.callback_data for row in rows for b in row] if rows else []


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

    async def edit_message_text(self, **kw):
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


async def _start(ctx):
    msg = _Msg("/start")
    await handlers.start(_update(message=msg), ctx)
    return msg


async def _say(ctx, text):
    msg = _Msg(text)
    await handlers.on_text(_update(message=msg), ctx)
    return msg


async def _press(ctx, data, message=None):
    query = _Query(data, message=message)
    handler = {
        "onboarding:skip": handlers.on_onboarding_skip,
    }.get(data, handlers.on_industry)
    await handler(_update(query=query), ctx)
    return query


FIRST_INDUSTRY = industries.all_industries()[0].key


# --- کاربر تازه در برابر کاربر قدیمی --------------------------------------------


class TestWhoSeesTheWizard:
    async def test_a_new_user_enters_the_wizard(self, store):
        ctx = _ctx(store)
        msg = await _start(ctx)
        assert ctx.user_data["flow"] == "onboarding"
        assert msg.replies[-1]["text"] == texts.WELCOME

    async def test_an_existing_user_goes_straight_to_the_menu(self, store):
        ctx = _ctx(store)
        user = await tx.get_or_create_user(store, UID)
        user.onboarded = True
        await store.update("users", user)

        msg = await _start(ctx)
        assert "flow" not in ctx.user_data
        assert msg.replies[-1]["text"] == texts.WELCOME_BACK
        labels = [b.text for r in msg.markup.keyboard for b in r]
        assert labels[0] == texts.BTN_REPORT

    async def test_the_wizard_is_offered_only_once(self, store):
        """حتی اگر کاربر نصفه رهایش کند، /start بعدی دوباره نمی‌پرسد."""
        ctx = _ctx(store)
        await _start(ctx)
        second = await _start(_ctx(store))
        assert second.replies[-1]["text"] == texts.WELCOME_BACK

    async def test_rows_without_the_column_are_treated_as_onboarded(self, store):
        """کاربرِ قدیمی که نام دارد، نباید ناگهان ویزارد ببیند."""
        from hesabyar.db.models import User
        user = User.from_row({"id": "5", "business_name": "مغازه‌ی قدیمی"})
        assert user.onboarded is True

    async def test_a_brand_new_row_is_not_onboarded(self):
        from hesabyar.db.models import User
        assert User.from_row({"id": "6"}).onboarded is False


# --- نقطه‌ی عطفِ شروعِ آنبردینگ (برای قیف/تحلیل) --------------------------------


class TestOnboardingStartedMilestone:
    async def test_start_stamps_onboarding_started_at(self, store):
        ctx = _ctx(store)
        await _start(ctx)
        user = await tx.get_or_create_user(store, UID)
        assert user.onboarding_started_at is not None

    async def test_second_start_does_not_move_the_stamp(self, store):
        ctx = _ctx(store)
        await _start(ctx)
        first = (await tx.get_or_create_user(store, UID)).onboarding_started_at

        await _start(_ctx(store))
        second = (await tx.get_or_create_user(store, UID)).onboarding_started_at
        assert second == first


# --- مسیرِ کامل -------------------------------------------------------------------


class TestHappyPath:
    async def test_name_then_industry_then_done(self, store):
        ctx = _ctx(store)
        await _start(ctx)

        # مرحله‌ی ۱ — نام
        msg = await _say(ctx, "قنادی شیرین")
        assert (await tx.get_or_create_user(store, UID)).business_name == "قنادی شیرین"
        assert "قنادی شیرین" in msg.replies[-1]["text"]
        picker = msg.replies[-1]["reply_markup"]
        assert any(d.startswith("ind:") for d in _cb(picker))
        assert "onboarding:skip" in _cb(picker)
        assert ctx.user_data.get("onboarding") is True

        # مرحله‌ی ۲ — صنف
        query = await _press(ctx, f"ind:{FIRST_INDUSTRY}")
        user = await tx.get_or_create_user(store, UID)
        assert user.business_type == FIRST_INDUSTRY

        # پیامِ پایانی + کیبورد اصلی
        sent = [r["text"] for r in query.message.replies]
        assert any(texts.ONBOARD_FINISHED.split("\n")[0] in t for t in sent)
        assert "onboarding" not in ctx.user_data
        last = query.message.replies[-1]["reply_markup"]
        assert [b.text for r in last.keyboard for b in r][0] == texts.BTN_REPORT

    async def test_the_final_message_offers_help(self, store):
        ctx = _ctx(store)
        await _start(ctx)
        await _say(ctx, "قنادی شیرین")
        query = await _press(ctx, f"ind:{FIRST_INDUSTRY}")
        helps = [r for r in query.message.replies
                 if "act:help" in _cb(r.get("reply_markup"))]
        assert helps, "دکمه‌ی راهنما در پیام پایانی نیست"

    async def test_the_final_message_includes_an_industry_example(self, store):
        ctx = _ctx(store)
        await _start(ctx)
        await _say(ctx, "قنادی شیرین")
        query = await _press(ctx, f"ind:{FIRST_INDUSTRY}")
        body = "\n".join(r["text"] for r in query.message.replies)
        assert industries.example_for(FIRST_INDUSTRY) in body

    async def test_an_empty_name_reasks(self, store):
        ctx = _ctx(store)
        await _start(ctx)
        msg = await _say(ctx, "   ")
        assert ctx.user_data["flow"] == "onboarding"
        assert msg.replies[-1]["text"] == texts.WELCOME

    async def test_after_the_wizard_text_is_logged_normally(self, store):
        ctx = _ctx(store)
        await _start(ctx)
        await _say(ctx, "قنادی شیرین")
        await _press(ctx, f"ind:{FIRST_INDUSTRY}")
        await _say(ctx, "۵۰۰ هزار خرید مواد اولیه")
        assert len(store.list("transactions")) == 1


# --- رد کردن مرحله‌ها -------------------------------------------------------------


class TestSkipping:
    async def test_every_step_offers_a_skip_button(self, store):
        ctx = _ctx(store)
        msg = await _start(ctx)
        assert "onboarding:skip" in _cb(msg.markup)          # مرحله‌ی نام
        after = await _say(ctx, "قنادی شیرین")
        assert "onboarding:skip" in _cb(after.markup)        # مرحله‌ی صنف

    async def test_skipping_the_name_moves_to_the_industry_step(self, store):
        ctx = _ctx(store)
        msg = await _start(ctx)
        query = await _press(ctx, "onboarding:skip", message=msg)
        assert "flow" not in ctx.user_data
        assert ctx.user_data.get("onboarding") is True
        assert query.message.replies[-1]["text"] == texts.ONBOARD_ASK_INDUSTRY_ANON
        assert not (await tx.get_or_create_user(store, UID)).business_name

    async def test_skipping_both_steps_still_finishes_cleanly(self, store):
        ctx = _ctx(store)
        msg = await _start(ctx)
        await _press(ctx, "onboarding:skip", message=msg)     # نام
        query = await _press(ctx, "onboarding:skip", message=msg)  # صنف

        assert "onboarding" not in ctx.user_data
        user = await tx.get_or_create_user(store, UID)
        assert not user.business_name and not user.business_type
        assert user.onboarded is True
        last = query.message.replies[-1]["reply_markup"]
        assert [b.text for r in last.keyboard for b in r][0] == texts.BTN_REPORT

    async def test_skipping_only_the_industry_keeps_the_name(self, store):
        ctx = _ctx(store)
        await _start(ctx)
        msg = await _say(ctx, "قنادی شیرین")
        await _press(ctx, "onboarding:skip", message=msg)
        user = await tx.get_or_create_user(store, UID)
        assert user.business_name == "قنادی شیرین"
        assert user.business_type == ""

    async def test_the_bot_works_after_skipping_everything(self, store):
        ctx = _ctx(store)
        msg = await _start(ctx)
        await _press(ctx, "onboarding:skip", message=msg)
        await _press(ctx, "onboarding:skip", message=msg)
        await _say(ctx, "۵۰۰ هزار خرید مواد اولیه")
        assert len(store.list("transactions")) == 1

    async def test_a_stray_skip_press_does_not_crash(self, store):
        ctx = _ctx(store)
        await tx.get_or_create_user(store, UID)
        query = await _press(ctx, "onboarding:skip")   # هیچ ویزاردی باز نیست
        assert query.message.replies   # فقط پیامِ پایانی، بدون خطا


# --- جبرانِ مرحله‌ی ردشده از منوی کسب‌وکار -----------------------------------------


class TestFillItInLater:
    async def test_business_menu_has_a_name_button(self):
        assert "act:bizname" in _cb(keyboards.business_menu())

    async def test_setting_the_name_from_the_menu(self, store):
        ctx = _ctx(store)
        msg = await _start(ctx)
        await _press(ctx, "onboarding:skip", message=msg)
        await _press(ctx, "onboarding:skip", message=msg)

        query = _Query("act:bizname")
        await handlers.on_menu_action(_update(query=query), ctx)
        assert texts.SELLER_HEADER in query.message.replies[-1]["text"]
        assert "seller:set:business_name" in _cb(query.message.replies[-1]["reply_markup"])

        field = _Query("seller:set:business_name")
        await handlers.on_seller_action(_update(query=field), ctx)
        assert ctx.user_data["flow"] == "seller_field"

        done = await _say(ctx, "قنادی شیرین")
        assert (await tx.get_or_create_user(store, UID)).business_name == "قنادی شیرین"
        assert "قنادی شیرین" in done.replies[-1]["text"]
        assert "flow" not in ctx.user_data

    async def test_industry_can_still_be_set_later(self, store):
        ctx = _ctx(store)
        msg = await _start(ctx)
        await _press(ctx, "onboarding:skip", message=msg)
        await _press(ctx, "onboarding:skip", message=msg)

        query = _Query("act:industry")
        await handlers.on_menu_action(_update(query=query), ctx)
        picker = query.message.replies[-1]["reply_markup"]
        assert "onboarding:skip" not in _cb(picker), "بیرونِ ویزارد، «رد کردن» بی‌معنا است"

        await _press(ctx, f"ind:{FIRST_INDUSTRY}")
        assert (await tx.get_or_create_user(store, UID)).business_type == FIRST_INDUSTRY


class TestRegistration:
    def test_skip_handler_is_registered(self):
        import re
        from telegram.ext import ApplicationBuilder, CallbackQueryHandler
        application = ApplicationBuilder().token("1:AA").build()
        handlers.register(application)
        patterns = [h.pattern.pattern for group in application.handlers.values()
                    for h in group
                    if isinstance(h, CallbackQueryHandler) and h.pattern]
        matching = [p for p in patterns if re.match(p, "onboarding:skip")]
        assert matching == [r"^onboarding:skip$"], matching
