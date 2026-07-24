"""سرویس تبدیل گفتار به متن (ویس→متن) برای پیام‌های صوتی تلگرام.

مثل :mod:`hesabyar.services.ocr` بر پایه‌ی «پروتکل» طراحی شده تا بتوان بین
پیاده‌سازی‌ها جابه‌جا شد:

* :class:`NullSttProvider` — وقتی STT غیرفعال است؛ هر فراخوانی
  :class:`SttUnavailable` می‌دهد.
* :class:`WhisperSttProvider` — به یک درگاه سازگار با API نوع OpenAI (مسیر
  ``audio/transcriptions``، مالتی‌پارت) وصل می‌شود. برای فارسی بسیار خوب کار
  می‌کند.

انتخاب پیاده‌سازی با :func:`get_stt_provider` بر اساس تنظیمات انجام می‌شود.
متنِ خروجی سپس مثل یک پیام متنی معمولی توسط بات پردازش می‌شود.
"""
from __future__ import annotations

from typing import Any, Optional, Protocol

import httpx

#: مهلت پیش‌فرض درخواست شبکه (ثانیه). رونویسی صوت ممکن است کمی طول بکشد.
_DEFAULT_TIMEOUT = 90.0


class SttUnavailable(Exception):
    """وقتی سرویس تبدیل گفتار به متن در دسترس نیست یا پاسخ معتبر نمی‌دهد."""


class SttProvider(Protocol):
    """پروتکل مشترک ارائه‌دهنده‌های تبدیل گفتار به متن."""

    async def transcribe(
        self, audio_bytes: bytes, *, mime_type: str = "audio/ogg",
        filename: str = "voice.ogg",
    ) -> str:
        """متنِ گفتار را برمی‌گرداند؛ در صورت خطا ``SttUnavailable``."""
        ...


class NullSttProvider:
    """پیاده‌سازی تهی؛ وقتی STT پیکربندی نشده است."""

    async def transcribe(  # noqa: D401
        self, audio_bytes: bytes, *, mime_type: str = "audio/ogg",
        filename: str = "voice.ogg",
    ) -> str:
        """همیشه :class:`SttUnavailable` می‌اندازد."""
        raise SttUnavailable("سرویس تبدیل گفتار به متن فعال نیست.")


def _extract_transcript(response: httpx.Response) -> str:
    """متنِ رونویسی را از پاسخ استخراج می‌کند.

    درگاه‌های سازگار با OpenAI معمولاً ``{"text": "..."}`` برمی‌گردانند؛ برخی
    با ``response_format=text`` متنِ خام می‌دهند. هر دو حالت پشتیبانی می‌شود.
    """
    try:
        data: Any = response.json()
    except ValueError:
        return (response.text or "").strip()

    if isinstance(data, str):
        return data.strip()
    if isinstance(data, dict):
        text = data.get("text")
        if isinstance(text, str):
            return text.strip()
    raise SttUnavailable("پاسخ سرویس تبدیل گفتار به متن قالب معتبری ندارد.")


class WhisperSttProvider:
    """تبدیل گفتار به متن با یک مدل سازگار با API نوع OpenAI (whisper).

    :param base_url: نشانی پایه‌ی درگاه (مثل ``https://api.openai.com/v1``).
    :param api_key: کلید احراز هویت (به‌صورت ``Bearer``).
    :param model: نام مدل رونویسی (پیش‌فرض ``whisper-1``).
    :param language: کد زبان برای بهبود دقت (پیش‌فرض ``fa``).
    :param timeout: مهلت درخواست (ثانیه).
    :param client: کلاینت ``httpx.AsyncClient`` اختیاری؛ برای تزریق در تست.
        اگر داده شود، مالکیت و بستن آن با فراخواننده است.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str = "whisper-1",
        language: str = "fa",
        *,
        timeout: float = _DEFAULT_TIMEOUT,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._language = language
        self._timeout = timeout
        self._client = client

    async def transcribe(
        self, audio_bytes: bytes, *, mime_type: str = "audio/ogg",
        filename: str = "voice.ogg",
    ) -> str:
        """گفتارِ داخل بایت‌های صوتی را به متن تبدیل می‌کند."""
        if not audio_bytes:
            raise SttUnavailable("فایل صوتی خالی است.")

        headers = {"Authorization": f"Bearer {self._api_key}"}
        files = {"file": (filename, audio_bytes, mime_type)}
        data = {
            "model": self._model,
            "response_format": "json",
        }
        if self._language:
            data["language"] = self._language
        url = f"{self._base_url}/audio/transcriptions"

        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        owns_client = self._client is None
        try:
            response = await client.post(
                url, data=data, files=files, headers=headers
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:  # خطای شبکه/HTTP
            raise SttUnavailable(
                f"خطا در ارتباط با سرویس تبدیل گفتار به متن: {exc}"
            ) from exc
        finally:
            if owns_client:
                await client.aclose()

        return _extract_transcript(response)


def get_stt_provider(settings: Any) -> SttProvider:
    """انتخاب ارائه‌دهنده‌ی STT بر اساس تنظیمات.

    اگر ``settings.stt_enabled`` درست باشد یک :class:`WhisperSttProvider`،
    وگرنه :class:`NullSttProvider` برمی‌گرداند.
    """
    creds = getattr(settings, "stt_creds", None)
    if creds:
        base_url, api_key, model, language = creds
        return WhisperSttProvider(base_url, api_key, model, language)
    return NullSttProvider()
