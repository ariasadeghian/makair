"""سرویس OCR برای استخراج متن از تصویر رسید.

طراحی این ماژول مبتنی بر «پروتکل» است تا بتوان بین چند پیاده‌سازی جابه‌جا شد:

* :class:`NullOcrProvider` — وقتی OCR غیرفعال است؛ هر فراخوانی خطای
  :class:`OcrUnavailable` می‌دهد.
* :class:`VisionLLMOcrProvider` — به یک درگاه سازگار با API نوع OpenAI (مسیر
  ``chat/completions`` با تصویرِ base64) وصل می‌شود.

انتخاب پیاده‌سازی با :func:`get_ocr_provider` بر اساس تنظیمات انجام می‌شود، و
:func:`parse_receipt_text` متنِ استخراج‌شده را به لایه‌ی
:mod:`hesabyar.core.nlp` می‌سپارد تا به یک تراکنش تبدیل شود.
"""
from __future__ import annotations

import base64
import datetime as dt
from typing import Any, Optional, Protocol

import httpx

from ..core.nlp import ParsedTransaction, parse_transaction

#: پرامپت استخراج متن رسید فارسی.
_OCR_PROMPT = (
    "این تصویر یک رسید یا فاکتور فارسی است. متن مهم و به‌ویژه مبلغ کل و شرح "
    "خرید را دقیق و خوانا استخراج کن. فقط متنِ استخراج‌شده را برگردان، بدون "
    "توضیح اضافه."
)

#: مهلت پیش‌فرض درخواست شبکه (ثانیه).
_DEFAULT_TIMEOUT = 60.0


class OcrUnavailable(Exception):
    """وقتی سرویس OCR در دسترس نیست یا پاسخ معتبر نمی‌دهد."""


class OcrProvider(Protocol):
    """پروتکل مشترک ارائه‌دهنده‌های OCR."""

    async def extract_text(self, image_bytes: bytes) -> str:
        """متن تصویر را استخراج می‌کند؛ در صورت خطا ``OcrUnavailable``."""
        ...


class NullOcrProvider:
    """پیاده‌سازی تهی؛ وقتی OCR پیکربندی نشده است."""

    async def extract_text(self, image_bytes: bytes) -> str:  # noqa: D401
        """همیشه :class:`OcrUnavailable` می‌اندازد."""
        raise OcrUnavailable("سرویس OCR فعال نیست.")


def _extract_content(data: dict[str, Any]) -> str:
    """استخراج متنِ پاسخ از بدنه‌ی JSON سازگار با OpenAI.

    ``content`` ممکن است رشته یا فهرستی از بخش‌ها باشد؛ هر دو حالت پشتیبانی
    می‌شود.
    """
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise OcrUnavailable("پاسخ سرویس OCR قالب معتبری ندارد.") from exc

    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):  # قالب چندبخشی
        parts = [
            part.get("text", "")
            for part in content
            if isinstance(part, dict)
        ]
        return "".join(parts).strip()
    return str(content).strip()


class VisionLLMOcrProvider:
    """OCR با یک مدل تصویری سازگار با API نوع OpenAI.

    :param base_url: نشانی پایه‌ی درگاه (مثل ``https://api.openai.com/v1``).
    :param api_key: کلید احراز هویت (به‌صورت ``Bearer``).
    :param model: نام مدل تصویری.
    :param timeout: مهلت درخواست (ثانیه).
    :param client: کلاینت ``httpx.AsyncClient`` اختیاری؛ برای تزریق در تست.
        اگر داده شود، مالکیت و بستن آن با فراخواننده است.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._client = client

    def _build_payload(self, image_bytes: bytes) -> dict[str, Any]:
        """ساخت بدنه‌ی درخواست chat/completions با تصویرِ base64."""
        b64 = base64.b64encode(image_bytes).decode("ascii")
        data_url = f"data:image/jpeg;base64,{b64}"
        return {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _OCR_PROMPT},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
        }

    async def extract_text(self, image_bytes: bytes) -> str:
        """متن رسید را از تصویر استخراج می‌کند."""
        payload = self._build_payload(image_bytes)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._base_url}/chat/completions"

        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        owns_client = self._client is None
        try:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:  # خطای شبکه/HTTP
            raise OcrUnavailable(f"خطا در ارتباط با سرویس OCR: {exc}") from exc
        finally:
            if owns_client:
                await client.aclose()

        return _extract_content(data)


def get_ocr_provider(settings: Any) -> OcrProvider:
    """انتخاب ارائه‌دهنده‌ی OCR بر اساس تنظیمات.

    اگر ``settings.ocr_enabled`` درست باشد یک :class:`VisionLLMOcrProvider`،
    وگرنه :class:`NullOcrProvider` برمی‌گرداند.
    """
    if getattr(settings, "ocr_enabled", False):
        return VisionLLMOcrProvider(
            base_url=settings.ocr_base_url,
            api_key=settings.ocr_api_key,
            model=settings.ocr_model,
        )
    return NullOcrProvider()


def parse_receipt_text(
    text: str, base: Optional[dt.datetime] = None
) -> Optional[ParsedTransaction]:
    """تبدیل متنِ استخراج‌شده‌ی رسید به یک تراکنش.

    این تابع صرفاً به :func:`hesabyar.core.nlp.parse_transaction` تفویض می‌کند.
    """
    return parse_transaction(text, base)
