"""تست‌های سرویس دفتر مالی گروه (روی Store ساختگی)."""
from hesabyar.db.models import GroupEventStatus
from hesabyar.services import group_ledger as grp

CHAT = -1001234567


async def _request(store, **kw):
    base = dict(
        requester_id=1, requester_name="الف", payer_id=2, payer_name="ب",
        amount=2_000_000, reason="پرینتر",
    )
    base.update(kw)
    return await grp.add_request(store, CHAT, **base)


class TestRequests:
    async def test_add_and_open(self, store):
        ev = await _request(store)
        assert ev.id is not None
        opens = grp.open_requests(store, CHAT)
        assert len(opens) == 1
        assert grp.totals(store, CHAT)["open"] == 2_000_000

    async def test_find_open_request_for_payer(self, store):
        req = await _request(store)
        found = grp.find_open_request_for(store, CHAT, payer_id=2, amount=2_000_000)
        assert found is not None and found.id == req.id
        # پرداخت‌کننده‌ی دیگر یا مبلغ دیگر → پیدا نمی‌شود
        assert grp.find_open_request_for(store, CHAT, payer_id=9) is None
        assert grp.find_open_request_for(store, CHAT, payer_id=2, amount=999) is None


class TestPayments:
    async def test_payment_settles_request(self, store):
        req = await _request(store)
        pay = await grp.add_payment(
            store, CHAT, payer_id=2, payer_name="ب", payee_id=1, payee_name="الف",
            amount=2_000_000, reason="پرینتر", request_id=req.id,
        )
        assert pay.status == GroupEventStatus.SETTLED
        # درخواست بسته شد
        assert grp.open_requests(store, CHAT) == []
        settled = store.get("group_events", req.id)
        assert settled.status == GroupEventStatus.SETTLED
        assert settled.settled_at is not None
        assert len(grp.recent_payments(store, CHAT)) == 1

    async def test_standalone_payment_logged(self, store):
        pay = await grp.add_payment(
            store, CHAT, payer_id=5, payer_name="ج", amount=300_000, reason="تنخواه",
        )
        assert pay.status == GroupEventStatus.LOGGED
        assert pay.request_id is None
        assert grp.totals(store, CHAT)["paid"] == 300_000


class TestScopingAndReport:
    async def test_scoped_by_chat(self, store):
        await _request(store)
        assert grp.open_requests(store, 999) == []
        assert grp.totals(store, 999)["open"] == 0

    async def test_report_contains_names(self, store):
        await _request(store, payer_name="بهنام", amount=500_000, reason="خرید")
        rep = grp.build_group_report(store, CHAT)
        assert "بهنام" in rep and "الف" in rep
        assert "درخواست‌های باز" in rep

    async def test_report_empty(self, store):
        assert "ثبت نشده" in grp.build_group_report(store, CHAT)
