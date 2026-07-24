"""تست‌های ماژول :mod:`hesabyar.services.stt` (تبدیل گفتار به متن).

هیچ تستی به شبکه وصل نمی‌شود؛ :class:`WhisperSttProvider` فقط با
``httpx.MockTransport`` آزموده می‌شود.
"""
import asyncio

import httpx
import pytest

from hesabyar.config import Settings
from hesabyar.services import stt


class TestNullProvider:
    def test_transcribe_raises(self):
        provider = stt.NullSttProvider()
        with pytest.raises(stt.SttUnavailable):
            asyncio.run(provider.transcribe(b"fake-audio"))


class TestGetSttProvider:
    def test_disabled_returns_null(self):
        provider = stt.get_stt_provider(Settings(bot_token="x"))
        assert isinstance(provider, stt.NullSttProvider)

    def test_explicit_stt_returns_whisper(self):
        settings = Settings(
            bot_token="x",
            stt_base_url="https://api.example.test/v1",
            stt_api_key="secret-key",
        )
        provider = stt.get_stt_provider(settings)
        assert isinstance(provider, stt.WhisperSttProvider)

    def test_falls_back_to_ocr_credentials(self):
        # اگر STT_* تنظیم نشود ولی OCR فعال باشد، از همان اعتبارنامه استفاده می‌شود.
        settings = Settings(
            bot_token="x",
            ocr_base_url="https://api.example.test/v1",
            ocr_api_key="secret-key",
        )
        provider = stt.get_stt_provider(settings)
        assert isinstance(provider, stt.WhisperSttProvider)


class TestWhisperProvider:
    def test_transcribe_with_mock_transport(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["auth"] = request.headers.get("Authorization")
            captured["content_type"] = request.headers.get("Content-Type", "")
            captured["body"] = request.content
            return httpx.Response(200, json={"text": "امروز دو میلیون فروختم"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = stt.WhisperSttProvider(
            "https://api.example.test/v1", "secret-key", "whisper-1", "fa",
            client=client,
        )
        text = asyncio.run(
            provider.transcribe(b"OggS-fake-bytes", mime_type="audio/ogg",
                                filename="voice.ogg")
        )
        asyncio.run(client.aclose())

        assert text == "امروز دو میلیون فروختم"
        assert captured["url"].endswith("/audio/transcriptions")
        assert captured["auth"] == "Bearer secret-key"
        assert captured["content_type"].startswith("multipart/form-data")
        # مدل، زبان و نام فایل در بدنه‌ی مالتی‌پارت هستند
        assert b"whisper-1" in captured["body"]
        assert b"voice.ogg" in captured["body"]
        assert b"fa" in captured["body"]

    def test_plain_text_response(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="سلام دنیا")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = stt.WhisperSttProvider(
            "https://api.example.test/v1", "k", "whisper-1", "fa", client=client
        )
        text = asyncio.run(provider.transcribe(b"audio"))
        asyncio.run(client.aclose())
        assert text == "سلام دنیا"

    def test_http_error_raises_unavailable(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="server error")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = stt.WhisperSttProvider(
            "https://api.example.test/v1", "k", client=client
        )
        with pytest.raises(stt.SttUnavailable):
            asyncio.run(provider.transcribe(b"audio"))
        asyncio.run(client.aclose())

    def test_empty_audio_raises(self):
        provider = stt.WhisperSttProvider("https://api.example.test/v1", "k")
        with pytest.raises(stt.SttUnavailable):
            asyncio.run(provider.transcribe(b""))
