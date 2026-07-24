"""تست‌های تشخیص رویداد مالی در پیام گروه (خالص، بدون I/O)."""
from hesabyar.core.group_nlp import detect_group_event
from hesabyar.db.models import GroupEventKind


class TestDetectRequest:
    def test_request_with_amount_and_reason(self):
        ev = detect_group_event("@علی لطفاً ۲ میلیون بابت خرید پرینتر پرداخت کن")
        assert ev is not None
        assert ev.kind == GroupEventKind.REQUEST
        assert ev.amount == 2_000_000
        assert "خرید" in ev.reason and "پرینتر" in ev.reason

    def test_request_imperative_variants(self):
        for text in ("۵۰۰ هزار واریز کن", "لطفاً ۱ میلیون بپرداز", "پرداختش کن ۳۰۰ هزار"):
            ev = detect_group_event(text)
            assert ev is not None and ev.kind == GroupEventKind.REQUEST

    def test_request_without_amount_still_detected(self):
        ev = detect_group_event("پرداخت کن دیگه")
        assert ev is not None
        assert ev.kind == GroupEventKind.REQUEST
        assert ev.amount is None


class TestDetectPayment:
    def test_payment_past_tense(self):
        ev = detect_group_event("پرداخت شد")
        assert ev is not None
        assert ev.kind == GroupEventKind.PAYMENT
        assert ev.amount is None

    def test_payment_with_amount_and_reason(self):
        ev = detect_group_event("۵۰۰ هزار واریز کردم بابت اجاره")
        assert ev is not None
        assert ev.kind == GroupEventKind.PAYMENT
        assert ev.amount == 500_000
        assert "اجاره" in ev.reason

    def test_payment_beats_request_when_both_present(self):
        # «کردم» گذشته است؛ نباید با «کن» اشتباه شود
        ev = detect_group_event("پرداخت کردم")
        assert ev is not None and ev.kind == GroupEventKind.PAYMENT


class TestNoDetection:
    def test_plain_chatter_is_none(self):
        assert detect_group_event("سلام خوبی؟ جلسه ساعت ۳ باشه") is None

    def test_thanks_without_cue_is_none(self):
        # «بابت» هست ولی هیچ فعلِ پرداخت/درخواست نیست
        assert detect_group_event("ممنون بابت کمکت") is None

    def test_empty_is_none(self):
        assert detect_group_event("") is None
        assert detect_group_event("   ") is None
