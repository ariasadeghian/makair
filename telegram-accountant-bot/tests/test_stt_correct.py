"""تست‌های ماژول :mod:`hesabyar.services.stt_correct` (اصلاح متنِ STT با LLM).

هیچ تستی به شبکه وصل نمی‌شود؛ :class:`~hesabyar.services.stt_correct.LlmSttCorrector`
فقط با ``httpx.MockTransport`` آزموده می‌شود (مثل الگوی ``tests/test_extract.py``
و ``tests/test_stt.py``).
"""
import asyncio
from types import SimpleNamespace

import httpx
import pytest

from hesabyar.services import stt_correct


def _mock_client(content=None, *, status=200, raise_error=False):
    def handler(request: httpx.Request) -> httpx.Response:
        if raise_error:
            raise httpx.ConnectError("شبکه در دسترس نیست")
        return httpx.Response(
            status, json={"choices": [{"message": {"content": content}}]}
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _run_correct(text, content=None, **mock_kwargs):
    async def run():
        client = _mock_client(content, **mock_kwargs)
        try:
            corrector = stt_correct.LlmSttCorrector(
                "http://x/v1", "k", "gpt-4o-mini", client=client
            )
            return await corrector.correct(text)
        finally:
            await client.aclose()

    return asyncio.run(run())


class TestLlmSttCorrector:
    def test_fixes_the_misheard_example(self):
        # مثال دقیقِ تیکت: «چوب فروش» → «چوب فروختم».
        corrected = _run_correct(
            "۲۰ میلیون چوب فروش", content="۲۰ میلیون چوب فروختم"
        )
        assert corrected == "۲۰ میلیون چوب فروختم"

    def test_sends_text_as_user_message_and_uses_zero_temperature(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json as _json
            captured["body"] = _json.loads(request.content)
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "متنِ تصحیح‌شده"}}]}
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        async def run():
            corrector = stt_correct.LlmSttCorrector(
                "http://x/v1", "k", "gpt-4o-mini", client=client
            )
            try:
                return await corrector.correct("متنِ خام")
            finally:
                await client.aclose()

        asyncio.run(run())
        assert captured["body"]["temperature"] == 0
        assert captured["body"]["messages"][1] == {
            "role": "user", "content": "متنِ خام",
        }
        # هیچ اجباری به قالبِ JSON نیست؛ خروجی باید متنِ ساده باشد.
        assert "response_format" not in captured["body"]

    def test_empty_llm_response_falls_back_to_original_text(self):
        corrected = _run_correct("متنِ خام", content="")
        assert corrected == "متنِ خام"

    def test_http_error_raises_correction_error(self):
        with pytest.raises(stt_correct.SttCorrectionError):
            _run_correct("متنِ خام", status=500)

    def test_network_error_raises_correction_error(self):
        with pytest.raises(stt_correct.SttCorrectionError):
            _run_correct("متنِ خام", raise_error=True)


class TestCorrectTranscript:
    def test_disabled_llm_returns_raw_text(self):
        settings = SimpleNamespace(llm_enabled=False, llm_creds=None)
        result = asyncio.run(stt_correct.correct_transcript(settings, "متنِ خام"))
        assert result == "متنِ خام"

    def test_no_creds_returns_raw_text_even_if_enabled(self):
        settings = SimpleNamespace(llm_enabled=True, llm_creds=None)
        result = asyncio.run(stt_correct.correct_transcript(settings, "متنِ خام"))
        assert result == "متنِ خام"

    def test_empty_text_short_circuits_without_calling_llm(self, monkeypatch):
        def boom(*a, **k):
            raise AssertionError("نباید برای متنِ خالی به LLM سر بزند")

        monkeypatch.setattr(stt_correct, "LlmSttCorrector", boom)
        settings = SimpleNamespace(llm_enabled=True, llm_creds=("u", "k", "m"))
        result = asyncio.run(stt_correct.correct_transcript(settings, ""))
        assert result == ""

    def test_uses_the_corrector_when_enabled_with_creds(self, monkeypatch):
        class FakeCorrector:
            def __init__(self, *a, **k):
                pass

            async def correct(self, text):
                return text.replace("چوب فروش", "چوب فروختم")

        monkeypatch.setattr(stt_correct, "LlmSttCorrector", FakeCorrector)
        settings = SimpleNamespace(llm_enabled=True, llm_creds=("u", "k", "m"))
        result = asyncio.run(
            stt_correct.correct_transcript(settings, "۲۰ میلیون چوب فروش")
        )
        assert result == "۲۰ میلیون چوب فروختم"

    def test_falls_back_to_raw_text_on_correction_error(self, monkeypatch):
        class Boom:
            def __init__(self, *a, **k):
                pass

            async def correct(self, text):
                raise stt_correct.SttCorrectionError("boom")

        monkeypatch.setattr(stt_correct, "LlmSttCorrector", Boom)
        settings = SimpleNamespace(llm_enabled=True, llm_creds=("u", "k", "m"))
        result = asyncio.run(stt_correct.correct_transcript(settings, "متنِ خام"))
        assert result == "متنِ خام"
