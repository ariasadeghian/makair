"""تست‌های ماژول :mod:`hesabyar.services.ocr`.

هیچ تستی به شبکه وصل نمی‌شود؛ :class:`VisionLLMOcrProvider` فقط با
``httpx.MockTransport`` آزموده می‌شود.
"""
import asyncio
import json

import httpx
import pytest

from hesabyar.config import Settings
from hesabyar.core.nlp import ParsedTransaction
from hesabyar.db.models import Kind
from hesabyar.services import ocr


def _settings(*, ocr_on: bool) -> Settings:
    """ساخت یک شیء تنظیمات با/بدون OCR فعال."""
    if ocr_on:
        return Settings(
            bot_token="x",
            ocr_base_url="https://api.example.test/v1",
            ocr_api_key="secret-key",
            ocr_model="vision-model",
        )
    return Settings(bot_token="x")


class TestNullProvider:
    def test_extract_text_raises(self):
        provider = ocr.NullOcrProvider()
        with pytest.raises(ocr.OcrUnavailable):
            asyncio.run(provider.extract_text(b"fake-image-bytes"))


class TestGetOcrProvider:
    def test_disabled_returns_null(self):
        provider = ocr.get_ocr_provider(_settings(ocr_on=False))
        assert isinstance(provider, ocr.NullOcrProvider)

    def test_enabled_returns_vision_llm(self):
        provider = ocr.get_ocr_provider(_settings(ocr_on=True))
        assert isinstance(provider, ocr.VisionLLMOcrProvider)


class TestVisionLLMProvider:
    def test_extract_text_with_mock_transport(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["auth"] = request.headers.get("Authorization")
            captured["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": "رسید خرید مواد اولیه مبلغ ۵۰۰ هزار تومان"
                            }
                        }
                    ]
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = ocr.VisionLLMOcrProvider(
            "https://api.example.test/v1",
            "secret-key",
            "vision-model",
            client=client,
        )
        text = asyncio.run(provider.extract_text(b"\x89PNG-fake-bytes"))
        asyncio.run(client.aclose())

        assert "۵۰۰ هزار تومان" in text
        # درخواست به مسیر درست و با هدر احراز هویت رفته است
        assert captured["url"].endswith("/chat/completions")
        assert captured["auth"] == "Bearer secret-key"
        # مدل و تصویرِ base64 در بدنه هستند
        assert captured["body"]["model"] == "vision-model"
        content = captured["body"]["messages"][0]["content"]
        image_part = next(p for p in content if p["type"] == "image_url")
        assert image_part["image_url"]["url"].startswith("data:image/jpeg;base64,")

    def test_multipart_content_is_joined(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": [
                                    {"type": "text", "text": "بخش اول "},
                                    {"type": "text", "text": "بخش دوم"},
                                ]
                            }
                        }
                    ]
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = ocr.VisionLLMOcrProvider(
            "https://api.example.test/v1", "k", "m", client=client
        )
        text = asyncio.run(provider.extract_text(b"img"))
        asyncio.run(client.aclose())
        assert text == "بخش اول بخش دوم"

    def test_http_error_raises_unavailable(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="server error")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = ocr.VisionLLMOcrProvider(
            "https://api.example.test/v1", "k", "m", client=client
        )
        with pytest.raises(ocr.OcrUnavailable):
            asyncio.run(provider.extract_text(b"img"))
        asyncio.run(client.aclose())

    def test_malformed_response_raises_unavailable(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"unexpected": "shape"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = ocr.VisionLLMOcrProvider(
            "https://api.example.test/v1", "k", "m", client=client
        )
        with pytest.raises(ocr.OcrUnavailable):
            asyncio.run(provider.extract_text(b"img"))
        asyncio.run(client.aclose())


class TestParseReceiptText:
    def test_parses_expense_receipt(self):
        parsed = ocr.parse_receipt_text("رسید خرید مواد اولیه مبلغ ۵۰۰ هزار تومان")
        assert isinstance(parsed, ParsedTransaction)
        assert parsed.kind == Kind.EXPENSE
        assert parsed.amount == 500_000
        assert parsed.category == "خرید کالا و مواد اولیه"

    def test_returns_none_without_amount(self):
        assert ocr.parse_receipt_text("رسیدی بدون مبلغ") is None
