"""درگاه پرداخت آنلاین «زرین‌پال» برای دریافت هزینه‌ی اشتراک.

این ماژول جایگزینِ روش «کارت‌به‌کارت» است و مبلغ اشتراک را از طریق درگاه
زرین‌پال دریافت می‌کند. طراحی مبتنی بر «پروتکل» است تا بتوان بین درگاه واقعی و
درگاهِ تهی (وقتی پیکربندی نشده) جابه‌جا شد:

* :class:`ZarinpalGateway` — به API نسخه‌ی ۴ زرین‌پال وصل می‌شود
  (``payment/request`` و ``payment/verify``).
* :class:`NullGateway` — وقتی merchant تنظیم نشده؛ هر فراخوانی
  :class:`GatewayError` می‌دهد.

انتخاب پیاده‌سازی با :func:`get_gateway` بر اساس تنظیمات انجام می‌شود.

.. note::

    زرین‌پال مبالغ را به **ریال** می‌گیرد، اما همه‌ی مبالغ داخلیِ حسابیار به
    **تومان** است؛ بنابراین هنگام ارسال به درگاه در همه‌ی متدها مبلغ در ``۱۰``
    ضرب می‌شود (``amount_toman * 10``).
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional, Protocol

import httpx

#: مهلت پیش‌فرض درخواست شبکه (ثانیه).
_DEFAULT_TIMEOUT = 30.0

#: کدهای موفقیت زرین‌پال هنگام «تأیید» پرداخت (۱۰۰ تازه، ۱۰۱ قبلاً تأییدشده).
_VERIFY_OK_CODES = (100, 101)

#: کد موفقیت زرین‌پال هنگام «درخواست» پرداخت.
_REQUEST_OK_CODE = 100


class GatewayError(Exception):
    """خطای درگاه پرداخت (پیکربندی‌نشده، خطای شبکه/HTTP، یا ردِ درخواست)."""


class PaymentGateway(Protocol):
    """پروتکل مشترک درگاه‌های پرداخت."""

    async def request_payment(
        self,
        amount_toman: int,
        description: str,
        callback_url: str,
        mobile: str = "",
        email: str = "",
    ) -> dict[str, Any]:
        """درخواست یک پرداخت جدید و برگرداندن ``authority`` و نشانی پرداخت."""
        ...

    async def verify(self, authority: str, amount_toman: int) -> dict[str, Any]:
        """تأیید یک پرداخت پس از بازگشت کاربر از درگاه."""
        ...


class ZarinpalGateway:
    """درگاه پرداخت زرین‌پال (API نسخه‌ی ۴).

    :param merchant_id: شناسه‌ی پذیرنده (Merchant ID) زرین‌پال.
    :param sandbox: اگر ``True`` باشد از محیط آزمایشیِ ``sandbox`` استفاده
        می‌شود؛ در غیر این صورت محیط عملیاتی.
    :param client: کلاینت ``httpx.AsyncClient`` اختیاری؛ برای تزریق در تست.
        اگر داده شود، مالکیت و بستن آن با فراخواننده است و متدها آن را
        نمی‌بندند؛ وگرنه هر متد یک کلاینت موقت می‌سازد و می‌بندد.
    """

    def __init__(
        self,
        merchant_id: str,
        sandbox: bool = False,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._merchant_id = merchant_id
        self._sandbox = sandbox
        self._client = client
        # نشانی پایه‌ی API (درخواست/تأیید) با نشانی صفحه‌ی پرداخت (StartPay)
        # متفاوت است؛ در محیط عملیاتی دامنه‌ها فرق دارند.
        self._base = (
            "https://sandbox.zarinpal.com"
            if sandbox
            else "https://payment.zarinpal.com"
        )
        self._startpay_base = (
            "https://sandbox.zarinpal.com" if sandbox else "https://www.zarinpal.com"
        )

    def _start_pay_url(self, authority: str) -> str:
        """ساخت نشانی صفحه‌ی پرداخت که کاربر باید به آن هدایت شود."""
        return f"{self._startpay_base}/pg/StartPay/{authority}"

    @asynccontextmanager
    async def _acquire_client(self) -> AsyncIterator[httpx.AsyncClient]:
        """کلاینت مناسب را به‌صورت context manager فراهم می‌کند.

        اگر کلاینتی تزریق شده باشد همان بازگردانده و **بسته نمی‌شود**؛ وگرنه یک
        کلاینت موقت با ``async with`` ساخته می‌شود که در پایان بسته می‌شود.
        """
        if self._client is not None:
            yield self._client
        else:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                yield client

    async def _post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        """ارسال ``POST`` به درگاه و برگرداندن بدنه‌ی JSON پاسخ.

        خطای شبکه، وضعیت HTTP نامعتبر یا پاسخِ غیرِJSON به
        :class:`GatewayError` تبدیل می‌شود.
        """
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        try:
            async with self._acquire_client() as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as exc:  # خطای شبکه/HTTP
            raise GatewayError(f"خطا در ارتباط با درگاه پرداخت: {exc}") from exc
        except ValueError as exc:  # پاسخِ غیرِ JSON (json.JSONDecodeError)
            raise GatewayError("پاسخ درگاه پرداخت قالب معتبری ندارد.") from exc

    @staticmethod
    def _error_message(body: dict[str, Any], fallback: str) -> str:
        """پیام خطای خوانا از بدنه‌ی پاسخ استخراج می‌کند.

        در پاسخِ ناموفق، ``errors`` معمولاً یک دیکشنری با ``code``/``message``
        است و ``data`` هم می‌تواند ``code`` منفی داشته باشد.
        """
        errors = body.get("errors")
        if isinstance(errors, dict) and errors:
            code = errors.get("code")
            message = errors.get("message") or fallback
            return f"{message} (کد {code})"
        data = body.get("data")
        if isinstance(data, dict) and data.get("code") is not None:
            message = data.get("message") or fallback
            return f"{message} (کد {data.get('code')})"
        return fallback

    async def request_payment(
        self,
        amount_toman: int,
        description: str,
        callback_url: str,
        mobile: str = "",
        email: str = "",
    ) -> dict[str, Any]:
        """درخواست یک پرداخت جدید از زرین‌پال.

        :param amount_toman: مبلغ به **تومان** (پیش از ارسال در ۱۰ ضرب می‌شود).
        :returns: دیکشنری ``{"authority": ..., "pay_url": ...}`` که ``pay_url``
            نشانی صفحه‌ی پرداخت برای هدایت کاربر است.
        :raises GatewayError: در صورت خطای شبکه/HTTP یا ردِ درخواست از سوی درگاه
            (کد منفی یا وجود ``errors``).
        """
        url = f"{self._base}/pg/v4/payment/request.json"
        payload: dict[str, Any] = {
            "merchant_id": self._merchant_id,
            "amount": amount_toman * 10,  # تومان → ریال
            "callback_url": callback_url,
            "description": description,
            "metadata": {"mobile": mobile, "email": email},
        }
        body = await self._post(url, payload)

        data = body.get("data")
        if (
            isinstance(data, dict)
            and data.get("code") == _REQUEST_OK_CODE
            and data.get("authority")
        ):
            authority = str(data["authority"])
            return {"authority": authority, "pay_url": self._start_pay_url(authority)}

        raise GatewayError(self._error_message(body, "درخواست پرداخت ناموفق بود."))

    async def verify(self, authority: str, amount_toman: int) -> dict[str, Any]:
        """تأیید یک پرداخت پس از بازگشت کاربر از درگاه.

        :param authority: کد ``authority`` که در مرحله‌ی درخواست گرفته شده بود.
        :param amount_toman: همان مبلغ به **تومان** (در ۱۰ ضرب می‌شود).
        :returns: در صورت موفقیت ``{"ok": True, "ref_id": "..."}`` و در صورت
            ناموفق‌بودنِ *معتبر* (مثلاً کد ``-51``) ``{"ok": False, "ref_id":
            None}``.
        :raises GatewayError: تنها در خطای قطعی شبکه/HTTP؛ یک پاسخِ معتبرِ
            ناموفق خطا محسوب نمی‌شود بلکه ``ok=False`` برمی‌گرداند.
        """
        url = f"{self._base}/pg/v4/payment/verify.json"
        payload: dict[str, Any] = {
            "merchant_id": self._merchant_id,
            "amount": amount_toman * 10,  # تومان → ریال
            "authority": authority,
        }
        body = await self._post(url, payload)

        data = body.get("data")
        if isinstance(data, dict) and data.get("code") in _VERIFY_OK_CODES:
            return {"ok": True, "ref_id": str(data.get("ref_id"))}
        return {"ok": False, "ref_id": None}


class NullGateway:
    """درگاه تهی؛ وقتی زرین‌پال پیکربندی نشده است.

    هر دو متد :class:`GatewayError` می‌دهند تا لایه‌ی بالادست بتواند کاربر را به
    روش کارت‌به‌کارت هدایت کند.
    """

    async def request_payment(
        self,
        amount_toman: int,
        description: str,
        callback_url: str,
        mobile: str = "",
        email: str = "",
    ) -> dict[str, Any]:
        """همیشه :class:`GatewayError` می‌اندازد (درگاه پیکربندی نشده)."""
        raise GatewayError("درگاه پرداخت پیکربندی نشده است.")

    async def verify(self, authority: str, amount_toman: int) -> dict[str, Any]:
        """همیشه :class:`GatewayError` می‌اندازد (درگاه پیکربندی نشده)."""
        raise GatewayError("درگاه پرداخت پیکربندی نشده است.")


def get_gateway(settings: Any) -> PaymentGateway:
    """انتخاب درگاه پرداخت بر اساس تنظیمات.

    تنظیمات به‌صورت دفاعی با :func:`getattr` خوانده می‌شوند تا نبودِ فیلدهای
    زرین‌پال خطا ندهد. اگر ``zarinpal_merchant_id`` موجود باشد یک
    :class:`ZarinpalGateway` (با توجه به ``zarinpal_sandbox``)، وگرنه یک
    :class:`NullGateway` برگردانده می‌شود.
    """
    mid = getattr(settings, "zarinpal_merchant_id", None)
    sb = bool(getattr(settings, "zarinpal_sandbox", False))
    if mid:
        return ZarinpalGateway(mid, sb)
    return NullGateway()
