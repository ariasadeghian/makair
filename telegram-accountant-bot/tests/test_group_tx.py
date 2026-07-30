"""تست ثبتِ فروش/هزینه در گروه (مسیرِ واقعیِ هندلرها با آبجکت‌های ساختگی).

سناریو: کسی در گروه می‌نویسد «۵ میلیون فروختم» → بات پیشنهادِ ثبت می‌دهد →
با «✅ ثبت کن» در دفترِ همان گروه ثبت می‌شود.
"""
from types import SimpleNamespace

from hesabyar.bot import handlers
from hesabyar.core import jalali
from hesabyar.db.models import Kind
from hesabyar.services import transactions as tx_service

CHAT = -100555  # شناسه‌ی گروه (تلگرام برای گروه‌ها منفی می‌دهد)
SENDER = 42


class _Msg:
    def __init__(self, text, chat_id=CHAT, message_id=1):
        self.text = text
        self.chat_id = chat_id
        self.message_id = message_id
        self.chat = SimpleNamespace(title="فروشگاه شریکی", type="group", id=chat_id)
        self.entities = []
        self.reply_to_message = None
        self.replies: list = []

    async def reply_text(self, text, **kw):
        self.replies.append({"text": text, **kw})
        return SimpleNamespace(message_id=999)


class _Query:
    def __init__(self, data):
        self.data = data
        self.edits: list = []

    async def answer(self):
        return None

    async def edit_message_text(self, text, **kw):
        self.edits.append(text)


def _ctx(store):
    app = SimpleNamespace(bot_data={"store": store}, bot=None)
    return SimpleNamespace(application=app, chat_data={}, user_data={})


def _update(message=None, query=None):
    return SimpleNamespace(
        message=message,
        callback_query=query,
        effective_user=SimpleNamespace(id=SENDER, full_name="علی", username="ali"),
        effective_chat=SimpleNamespace(id=CHAT, type="group", title="فروشگاه شریکی"),
    )


class TestGroupSale:
    async def test_sale_offers_confirm_then_records(self, store):
        ctx = _ctx(store)
        msg = _Msg("۵ میلیون فروختم")

        # ۱) پیامِ گروه ⇒ باید پیشنهادِ ثبت بدهد (نه سکوت)
        await handlers.on_group_message(_update(message=msg), ctx)
        assert len(msg.replies) == 1
        offer = msg.replies[0]["text"]
        assert "فروش/درآمد" in offer
        assert "۵٬۰۰۰٬۰۰۰" in offer
        assert offer.endswith("ثبتش کنم؟")
        # هنوز چیزی ثبت نشده است
        assert store.list("transactions", lambda t: True) == []

        # ۲) لمسِ «✅ ثبت کن» ⇒ ثبت در دفترِ گروه
        query = _Query(f"grp:ok:{msg.message_id}")
        await handlers.on_group_confirm(_update(query=query), ctx)

        txs = store.list("transactions", lambda t: True)
        assert len(txs) == 1
        assert txs[0].user_id == CHAT          # به دفترِ گروه رفته، نه کاربر
        assert txs[0].kind == Kind.INCOME
        assert txs[0].amount == 5_000_000
        # عنوانِ گروه به‌عنوان نامِ کسب‌وکارِ دفتر ذخیره شده است
        assert store.get("users", CHAT).business_name == "فروشگاه شریکی"
        assert "ثبت شد" in query.edits[-1]

    async def test_expense_recorded(self, store):
        ctx = _ctx(store)
        msg = _Msg("قبض برق ۳۲۰ هزار دادم", message_id=7)
        await handlers.on_group_message(_update(message=msg), ctx)
        assert "هزینه" in msg.replies[0]["text"]

        await handlers.on_group_confirm(
            _update(query=_Query("grp:ok:7")), ctx
        )
        txs = store.list("transactions", lambda t: True)
        assert len(txs) == 1 and txs[0].kind == Kind.EXPENSE

    async def test_reject_records_nothing(self, store):
        ctx = _ctx(store)
        msg = _Msg("۲ میلیون فروختم", message_id=3)
        await handlers.on_group_message(_update(message=msg), ctx)
        query = _Query("grp:no:3")
        await handlers.on_group_confirm(_update(query=query), ctx)
        assert store.list("transactions", lambda t: True) == []
        assert "ثبتش نکردم" in query.edits[-1]

    async def test_plain_chatter_is_ignored(self, store):
        """پیامِ غیرمالیِ گروه نباید پیشنهادِ ثبت بسازد (ضدِ نویز)."""
        ctx = _ctx(store)
        noise = [
            "سلام بچه‌ها، جلسه ساعت ۳ باشه؟",   # عدد دارد ولی مبلغ نیست
            "فردا ۲ تا مشتری میان",
            "ممنون بابت کمکت",
            "کانال رو ۵ تا شریک کردیم",
        ]
        for i, text in enumerate(noise):
            msg = _Msg(text, message_id=100 + i)
            await handlers.on_group_message(_update(message=msg), ctx)
            assert msg.replies == [], f"نویز پیشنهاد ساخت: {text!r}"
        assert store.list("transactions", lambda t: True) == []

    async def test_group_book_is_separate_from_personal(self, store):
        ctx = _ctx(store)
        # کاربر شخصی هم یک تراکنش دارد
        await tx_service.get_or_create_user(store, SENDER)
        await tx_service.add_transaction(
            store, SENDER, kind=Kind.INCOME, amount=111, category="x",
            description="", occurred_at=jalali.now(),
        )
        msg = _Msg("۹ میلیون فروختم", message_id=11)
        await handlers.on_group_message(_update(message=msg), ctx)
        await handlers.on_group_confirm(_update(query=_Query("grp:ok:11")), ctx)

        start, end = jalali.month_bounds(jalali.now())
        assert tx_service.summary(store, SENDER, start, end)["income"] == 111
        assert tx_service.summary(store, CHAT, start, end)["income"] == 9_000_000
