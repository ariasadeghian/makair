"""تست‌های ماژول :mod:`hesabyar.services.stt` (تبدیل گفتار به متن).

هیچ تستی به شبکه وصل نمی‌شود؛ :class:`WhisperSttProvider` فقط با
``httpx.MockTransport`` آزموده می‌شود، و :class:`LocalWhisperSttProvider`
با یک ماژولِ ساختگیِ ``faster_whisper`` در ``sys.modules`` — پکیجِ واقعی نه
لازم است نه در این محیط نصب می‌شود (دانلودِ مدل کند و شبکه‌محور است).
"""
import asyncio
import os
import sys
import types

import httpx
import pytest

from hesabyar.config import Settings
from hesabyar.services import stt


def _fake_faster_whisper_module(model_cls) -> types.ModuleType:
    """ماژولِ ساختگیِ ``faster_whisper`` با ``WhisperModel`` دلخواه."""
    module = types.ModuleType("faster_whisper")
    module.WhisperModel = model_cls
    return module


class _FakeSegment:
    def __init__(self, text: str):
        self.text = text


class _FakeWhisperModel:
    """جایگزینِ ``faster_whisper.WhisperModel``: شمارشِ بارگذاری + رونویسیِ ثابت."""

    load_count = 0
    last_language = None
    last_path_existed = None

    def __init__(self, model_size: str, device: str = "cpu", compute_type: str = "int8"):
        type(self).load_count += 1
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type

    def transcribe(self, path: str, language: str | None = None):
        type(self).last_language = language
        type(self).last_path_existed = os.path.exists(path)
        segments = [_FakeSegment(" امروز "), _FakeSegment("دو میلیون فروختم ")]
        return segments, object()


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


class TestLocalWhisperProvider:
    def setup_method(self):
        _FakeWhisperModel.load_count = 0
        _FakeWhisperModel.last_language = None
        _FakeWhisperModel.last_path_existed = None

    def test_missing_package_raises_clear_persian_message(self, monkeypatch):
        # وقتی faster_whisper اصلاً نصب نیست، sys.modules آن را None می‌کند
        # (رفتارِ استانداردِ پایتون: import بعدی بلافاصله ImportError می‌دهد).
        monkeypatch.setitem(sys.modules, "faster_whisper", None)
        with pytest.raises(stt.SttUnavailable, match="faster-whisper"):
            stt.LocalWhisperSttProvider()

    def test_empty_audio_raises_without_touching_model(self, monkeypatch):
        monkeypatch.setitem(
            sys.modules, "faster_whisper",
            _fake_faster_whisper_module(_FakeWhisperModel),
        )
        provider = stt.LocalWhisperSttProvider()
        with pytest.raises(stt.SttUnavailable):
            asyncio.run(provider.transcribe(b""))
        assert _FakeWhisperModel.load_count == 0

    def test_transcribe_joins_segments_and_writes_readable_temp_file(self, monkeypatch):
        monkeypatch.setitem(
            sys.modules, "faster_whisper",
            _fake_faster_whisper_module(_FakeWhisperModel),
        )
        provider = stt.LocalWhisperSttProvider(
            model_size="tiny", device="cpu", compute_type="int8", language="fa",
        )
        text = asyncio.run(
            provider.transcribe(b"OggS-fake-bytes", filename="voice.ogg")
        )
        assert text == "امروز دو میلیون فروختم"
        assert _FakeWhisperModel.last_language == "fa"
        assert _FakeWhisperModel.last_path_existed is True  # فایلِ موقت هنگام رونویسی موجود بود

    def test_temp_file_is_removed_after_transcribe(self, monkeypatch):
        captured_path: dict = {}
        real_transcribe = _FakeWhisperModel.transcribe

        def spying_transcribe(self, path, language=None):
            captured_path["path"] = path
            return real_transcribe(self, path, language=language)

        monkeypatch.setattr(_FakeWhisperModel, "transcribe", spying_transcribe)
        monkeypatch.setitem(
            sys.modules, "faster_whisper",
            _fake_faster_whisper_module(_FakeWhisperModel),
        )
        provider = stt.LocalWhisperSttProvider()
        asyncio.run(provider.transcribe(b"OggS-fake-bytes"))
        assert not os.path.exists(captured_path["path"])

    def test_model_loaded_once_across_multiple_transcriptions(self, monkeypatch):
        monkeypatch.setitem(
            sys.modules, "faster_whisper",
            _fake_faster_whisper_module(_FakeWhisperModel),
        )
        provider = stt.LocalWhisperSttProvider()
        asyncio.run(provider.transcribe(b"OggS-fake-1"))
        asyncio.run(provider.transcribe(b"OggS-fake-2"))
        assert _FakeWhisperModel.load_count == 1

    def test_empty_transcript_raises_unavailable(self, monkeypatch):
        class _EmptyModel(_FakeWhisperModel):
            def transcribe(self, path, language=None):
                return [], object()

        monkeypatch.setitem(
            sys.modules, "faster_whisper",
            _fake_faster_whisper_module(_EmptyModel),
        )
        provider = stt.LocalWhisperSttProvider()
        with pytest.raises(stt.SttUnavailable):
            asyncio.run(provider.transcribe(b"OggS-fake-bytes"))


class TestGetSttProviderLocal:
    def setup_method(self):
        _FakeWhisperModel.load_count = 0

    def test_local_provider_kind_selected_regardless_of_remote_creds(self, monkeypatch):
        monkeypatch.setattr(stt, "_local_provider_singleton", None)
        monkeypatch.setitem(
            sys.modules, "faster_whisper",
            _fake_faster_whisper_module(_FakeWhisperModel),
        )
        settings = Settings(
            bot_token="x", stt_provider="local",
            # اعتبارنامه‌ی ریموت هم ست شده؛ باید نادیده گرفته شود.
            stt_base_url="https://api.example.test/v1", stt_api_key="secret-key",
        )
        provider = stt.get_stt_provider(settings)
        assert isinstance(provider, stt.LocalWhisperSttProvider)

    def test_singleton_across_calls_does_not_reload_model(self, monkeypatch):
        monkeypatch.setattr(stt, "_local_provider_singleton", None)
        monkeypatch.setitem(
            sys.modules, "faster_whisper",
            _fake_faster_whisper_module(_FakeWhisperModel),
        )
        settings = Settings(bot_token="x", stt_provider="local")
        first = stt.get_stt_provider(settings)
        second = stt.get_stt_provider(settings)
        assert first is second

    def test_default_provider_kind_is_remote(self):
        settings = Settings(bot_token="x")
        assert settings.stt_provider == "remote"
        provider = stt.get_stt_provider(settings)
        assert isinstance(provider, stt.NullSttProvider)
