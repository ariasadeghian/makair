"""سرویس تبدیل گفتار به متن (ویس→متن) برای پیام‌های صوتی تلگرام.

مثل :mod:`hesabyar.services.ocr` بر پایه‌ی «پروتکل» طراحی شده تا بتوان بین
پیاده‌سازی‌ها جابه‌جا شد:

* :class:`NullSttProvider` — وقتی STT غیرفعال است؛ هر فراخوانی
  :class:`SttUnavailable` می‌دهد.
* :class:`WhisperSttProvider` — به یک درگاه سازگار با API نوع OpenAI (مسیر
  ``audio/transcriptions``، مالتی‌پارت) وصل می‌شود. برای فارسی بسیار خوب کار
  می‌کند.
* :class:`LocalWhisperSttProvider` — رونویسیِ کاملاً محلی/آفلاین با
  ``faster-whisper``؛ بدون تماس با هیچ API خارجی.

انتخاب پیاده‌سازی با :func:`get_stt_provider` بر اساس تنظیمات انجام می‌شود.
متنِ خروجی سپس مثل یک پیام متنی معمولی توسط بات پردازش می‌شود.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
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


class LocalWhisperSttProvider:
    """رونویسیِ کاملاً محلی/آفلاین با ``faster-whisper`` (بدون API خارجی).

    مدل واقعی (``faster_whisper.WhisperModel``) تنبل (lazy) بارگذاری
    می‌شود — نه در همین‌جا، چون بارگذاری sync/blocking است و ساختنِ این
    شیء (در :func:`get_stt_provider`) قبل از اجرای event loop رخ می‌دهد؛
    اولین فراخوانیِ :meth:`transcribe` آن را یک‌بار، از میان
    :func:`asyncio.to_thread`، بارگذاری و برای فراخوانی‌های بعدی روی خودِ
    شیء کش می‌کند.

    :param model_size: اندازه‌ی مدل ویسپر (``tiny``/``base``/``small``/…)؛
        ``small`` برای فارسی روی CPU تعادلِ منطقیِ سرعت/دقت است.
    :param device: ``"cpu"`` یا ``"cuda"``.
    :param compute_type: کوانتیزیشنِ ctranslate2 (``int8`` روی CPU سریع است).
    :param language: کد زبان برای رونویسی (پیش‌فرض ``fa``).
    """

    def __init__(
        self,
        model_size: str = "small",
        device: str = "cpu",
        compute_type: str = "int8",
        language: str = "fa",
    ) -> None:
        try:
            import faster_whisper  # noqa: F401
        except ImportError as exc:
            raise SttUnavailable(
                "برای STT محلی باید پکیجِ «faster-whisper» نصب شود؛ با دستورِ "
                "«pip install faster-whisper» نصبش کن."
            ) from exc
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._language = language
        self._model: Any = None
        self._model_lock = asyncio.Lock()

    def _load_model(self) -> Any:
        """ساختِ ``WhisperModel`` — sync/blocking؛ فقط از میانِ یک ترد صدا زده شود."""
        from faster_whisper import WhisperModel

        return WhisperModel(
            self._model_size, device=self._device, compute_type=self._compute_type
        )

    async def _ensure_model(self) -> Any:
        if self._model is not None:
            return self._model
        async with self._model_lock:
            if self._model is None:  # رقابتِ هم‌زمانِ چند ویسِ اول
                self._model = await asyncio.to_thread(self._load_model)
        return self._model

    def _transcribe_file(self, model: Any, path: str) -> str:
        """رونویسیِ فایل — sync/blocking؛ فقط از میانِ یک ترد صدا زده شود."""
        segments, _info = model.transcribe(path, language=self._language)
        return " ".join(seg.text.strip() for seg in segments).strip()

    async def transcribe(
        self, audio_bytes: bytes, *, mime_type: str = "audio/ogg",
        filename: str = "voice.ogg",
    ) -> str:
        """گفتارِ داخل بایت‌های صوتی را به‌صورت محلی به متن تبدیل می‌کند."""
        if not audio_bytes:
            raise SttUnavailable("فایل صوتی خالی است.")

        model = await self._ensure_model()

        suffix = os.path.splitext(filename)[1] or ".ogg"
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        try:
            tmp.write(audio_bytes)
            tmp.close()
            text = await asyncio.to_thread(self._transcribe_file, model, tmp.name)
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:  # pragma: no cover - پاک‌سازی، شکستش بی‌خطر است
                pass

        if not text:
            raise SttUnavailable("رونویسیِ صوت خالی برگشت.")
        return text


#: نمونه‌ی singleton؛ چون بارگذاریِ مدل چند ثانیه طول می‌کشد، در کل عمرِ
#: پروسه فقط یک‌بار ساخته می‌شود (نه هر بار که :func:`get_stt_provider` صدا
#: زده می‌شود).
_local_provider_singleton: Optional["LocalWhisperSttProvider"] = None


def _get_local_provider(settings: Any) -> LocalWhisperSttProvider:
    global _local_provider_singleton
    if _local_provider_singleton is None:
        _local_provider_singleton = LocalWhisperSttProvider(
            model_size=getattr(settings, "stt_local_model_size", "small"),
            device=getattr(settings, "stt_local_device", "cpu"),
            compute_type=getattr(settings, "stt_local_compute_type", "int8"),
            language=getattr(settings, "stt_language", "fa"),
        )
    return _local_provider_singleton


def get_stt_provider(settings: Any) -> SttProvider:
    """انتخاب ارائه‌دهنده‌ی STT بر اساس تنظیمات.

    اگر ``settings.stt_provider == "local"`` باشد یک
    :class:`LocalWhisperSttProvider` (singleton) برمی‌گرداند — مستقل از
    اینکه اعتبارنامه‌ی ریموت (``stt_creds``) تنظیم شده یا نه. وگرنه رفتارِ
    قبلی: اگر ``stt_creds`` باشد :class:`WhisperSttProvider`، وگرنه
    :class:`NullSttProvider`.
    """
    if getattr(settings, "stt_provider", "remote") == "local":
        return _get_local_provider(settings)

    creds = getattr(settings, "stt_creds", None)
    if creds:
        base_url, api_key, model, language = creds
        return WhisperSttProvider(base_url, api_key, model, language)
    return NullSttProvider()
