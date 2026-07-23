"""تست‌های ماژول :mod:`hesabyar.services.gateway`.

هیچ تستی به شبکه وصل نمی‌شود؛ :class:`ZarinpalGateway` فقط با
``httpx.MockTransport`` آزموده می‌شود و متدهای async با ``asyncio.run`` اجرا
می‌شوند. برای تنظیماتِ ساختگی از :class:`types.SimpleNamespace` استفاده می‌شود.
"""
import asyncio
import json
import types

import httpx
import pytest

from hesabyar.config import Settings
from hesabyar.services import gateway

#: یک ``authority`` نمونه به همان قالب زرین‌پال (۳۶ کاراکتر).
_AUTHORITY = "A00000000000000000000000000000012345"


def _client(handler) -> httpx.AsyncClient:
    """ساخت کلاینت async با ترابری ساختگی (بدون هیچ تماس شبکه‌ای)."""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestRequestPayment:
    def test_returns_authority_and_pay_url(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={"data": {"authority": _AUTHORITY, "code": 100}, "errors": []},
            )

        client = _client(handler)
        gw = gateway.ZarinpalGateway("merchant-xyz", client=client)
        result = asyncio.run(
            gw.request_payment(
                amount_toman=5000,
                description="اشتراک یک‌ماهه",
                callback_url="https://bot.example/callback",
            )
        )
        asyncio.run(client.aclose())

        # خروجی درست است و pay_url شاملِ authority است.
        assert result["authority"] == _AUTHORITY
        assert result["pay_url"] == f"https://www.zarinpal.com/pg/StartPay/{_AUTHORITY}"
        assert _AUTHORITY in result["pay_url"]
        # مسیر درست و مبلغِ ارسالی به سرور = تومان×۱۰ (ریال).
        assert captured["url"].endswith("/pg/v4/payment/request.json")
        assert captured["body"]["amount"] == 5000 * 10
        assert captured["body"]["merchant_id"] == "merchant-xyz"
        assert captured["body"]["callback_url"] == "https://bot.example/callback"

    def test_metadata_carries_mobile_and_email(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={"data": {"authority": _AUTHORITY, "code": 100}, "errors": []},
            )

        client = _client(handler)
        gw = gateway.ZarinpalGateway("m", client=client)
        asyncio.run(
            gw.request_payment(
                1000,
                "شرح",
                "https://cb",
                mobile="09120000000",
                email="user@example.com",
            )
        )
        asyncio.run(client.aclose())
        assert captured["body"]["metadata"] == {
            "mobile": "09120000000",
            "email": "user@example.com",
        }

    def test_sandbox_uses_sandbox_start_pay(self):
        def handler(request: httpx.Request) -> httpx.Response:
            # در sandbox باید مسیرِ درخواست هم روی دامنه‌ی sandbox باشد.
            assert str(request.url).startswith("https://sandbox.zarinpal.com/")
            return httpx.Response(
                200,
                json={"data": {"authority": _AUTHORITY, "code": 100}, "errors": []},
            )

        client = _client(handler)
        gw = gateway.ZarinpalGateway("m", sandbox=True, client=client)
        result = asyncio.run(gw.request_payment(1000, "شرح", "https://cb"))
        asyncio.run(client.aclose())
        assert result["pay_url"] == (
            f"https://sandbox.zarinpal.com/pg/StartPay/{_AUTHORITY}"
        )

    def test_business_error_raises(self):
        # کد منفی به همراه errors → درخواست ردشده → GatewayError.
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "data": [],
                    "errors": {"code": -9, "message": "merchant_id نامعتبر است"},
                },
            )

        client = _client(handler)
        gw = gateway.ZarinpalGateway("bad-merchant", client=client)
        with pytest.raises(gateway.GatewayError):
            asyncio.run(gw.request_payment(1000, "شرح", "https://cb"))
        asyncio.run(client.aclose())

    def test_http_error_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="server error")

        client = _client(handler)
        gw = gateway.ZarinpalGateway("m", client=client)
        with pytest.raises(gateway.GatewayError):
            asyncio.run(gw.request_payment(1000, "شرح", "https://cb"))
        asyncio.run(client.aclose())


class TestVerify:
    def test_successful_verify_returns_ref_id(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={"data": {"code": 100, "ref_id": 111}, "errors": []},
            )

        client = _client(handler)
        gw = gateway.ZarinpalGateway("m", client=client)
        result = asyncio.run(gw.verify(_AUTHORITY, amount_toman=5000))
        asyncio.run(client.aclose())

        assert result["ok"] is True
        # ref_id همیشه رشته است، حتی اگر سرور عدد بفرستد.
        assert result["ref_id"] == "111"
        assert isinstance(result["ref_id"], str)
        # مسیر درست و مبلغِ تأیید = تومان×۱۰ (ریال).
        assert captured["url"].endswith("/pg/v4/payment/verify.json")
        assert captured["body"]["amount"] == 5000 * 10
        assert captured["body"]["authority"] == _AUTHORITY

    def test_code_101_already_verified_is_ok(self):
        # کد ۱۰۱ یعنی «قبلاً تأیید شده» و باز هم موفق است.
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"data": {"code": 101, "ref_id": 222}, "errors": []},
            )

        client = _client(handler)
        gw = gateway.ZarinpalGateway("m", client=client)
        result = asyncio.run(gw.verify(_AUTHORITY, 100))
        asyncio.run(client.aclose())
        assert result == {"ok": True, "ref_id": "222"}

    def test_failed_verify_returns_ok_false(self):
        # پاسخِ معتبر ولی ناموفق (کد -۵۱) → خطا نمی‌دهد، ok=False برمی‌گرداند.
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "data": {"code": -51, "message": "پرداخت ناموفق بود"},
                    "errors": [],
                },
            )

        client = _client(handler)
        gw = gateway.ZarinpalGateway("m", client=client)
        result = asyncio.run(gw.verify(_AUTHORITY, 100))
        asyncio.run(client.aclose())
        assert result == {"ok": False, "ref_id": None}

    def test_http_error_raises(self):
        # خطای قطعیِ شبکه/HTTP → GatewayError.
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(502, text="bad gateway")

        client = _client(handler)
        gw = gateway.ZarinpalGateway("m", client=client)
        with pytest.raises(gateway.GatewayError):
            asyncio.run(gw.verify(_AUTHORITY, 100))
        asyncio.run(client.aclose())


class TestNullGateway:
    def test_request_payment_raises(self):
        gw = gateway.NullGateway()
        with pytest.raises(gateway.GatewayError):
            asyncio.run(gw.request_payment(1000, "شرح", "https://cb"))

    def test_verify_raises(self):
        gw = gateway.NullGateway()
        with pytest.raises(gateway.GatewayError):
            asyncio.run(gw.verify(_AUTHORITY, 1000))


class TestGetGateway:
    def test_without_merchant_returns_null(self):
        # تنظیماتِ ساختگی بدون فیلد zarinpal → NullGateway.
        settings = types.SimpleNamespace()
        assert isinstance(gateway.get_gateway(settings), gateway.NullGateway)

    def test_with_merchant_returns_zarinpal(self):
        settings = types.SimpleNamespace(
            zarinpal_merchant_id="merchant-xyz", zarinpal_sandbox=True
        )
        assert isinstance(gateway.get_gateway(settings), gateway.ZarinpalGateway)

    def test_real_settings_without_zarinpal_returns_null(self):
        # getattr دفاعی روی Settings واقعی (merchant پیش‌فرض None) هم کار می‌کند.
        assert isinstance(
            gateway.get_gateway(Settings(bot_token="x")), gateway.NullGateway
        )
