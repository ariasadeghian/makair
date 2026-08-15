"""تست‌های هندلرِ ``on_voice``: مسیرِ رونویسی + اصلاحِ LLM قبل از مسیریابی.

اینجا خودِ هندلر با آبجکت‌های ساختگیِ Update/Context صدا زده می‌شود (مثل
الگوی ``TestFullReportButton`` در ``tests/test_daily_summary.py``)، نه
سرویس‌های زیرینش؛ ``_require_feature`` و ``_route_text`` مانک می‌شوند چون
موضوعِ این تست‌ها فقط سیمِ‌کشیِ رونویسی→اصلاح→مسیریابی است، نه اشتراک یا
مسیریابیِ خودِ متن.
"""
import asyncio
from types import SimpleNamespace

from hesabyar.bot import handlers, texts
from hesabyar.config import Settings

UID = 14_001


class _TgFile:
    async def download_as_bytearray(self):
        return bytearray(b"OggS-fake-audio-bytes")


class _Voice:
    def __init__(self, duration=3):
        self.duration = duration
        self.mime_type = "audio/ogg"
        self.file_name = None

    async def get_file(self):
        return _TgFile()


class _Msg:
    def __init__(self, voice=None):
        self.voice = voice
        self.audio = None
        self.replies: list = []

    async def reply_text(self, text, **kw):
        self.replies.append({"text": text, **kw})


class _FakeSttProvider:
    """جایگزینِ ``NullSttProvider``: همیشه یک متنِ خامِ ثابت برمی‌گرداند."""

    def __init__(self, raw_text):
        self._raw_text = raw_text
        self.calls = 0

    async def transcribe(self, audio_bytes, *, mime_type="audio/ogg", filename="voice.ogg"):
        self.calls += 1
        return self._raw_text


def _ctx(store, *, stt_provider, llm_creds=None):
    settings = Settings(
        bot_token="x",
        llm_base_url=llm_creds[0] if llm_creds else None,
        llm_api_key=llm_creds[1] if llm_creds else None,
        llm_model=llm_creds[2] if llm_creds else None,
        use_llm_parser=True,
    ) if llm_creds else Settings(bot_token="x")
    app = SimpleNamespace(
        bot_data={"store": store, "settings": settings, "stt": stt_provider},
    )
    return SimpleNamespace(application=app, user_data={}, chat_data={})


def _update(msg):
    return SimpleNamespace(
        message=msg,
        effective_user=SimpleNamespace(id=UID, full_name="ت", username="t"),
    )


async def _allow_feature(*a, **k):
    return True


def _run_on_voice(monkeypatch, *, raw_text, llm_creds=None, corrector_result=None,
                   corrector_raises=False):
    monkeypatch.setattr(handlers, "_require_feature", _allow_feature)

    routed: dict = {}

    async def fake_route_text(update, context, text):
        routed["text"] = text

    monkeypatch.setattr(handlers, "_route_text", fake_route_text)

    if corrector_raises:
        # به‌جای مانک‌کردنِ خودِ correct_transcript، فقط لایه‌ی زیرینش
        # (LlmSttCorrector) را خراب می‌کنیم تا correct_transcuriptِ *واقعی*
        # هم امتحان شود: باید خودش خطا را بگیرد و متنِ خام را برگرداند.
        class _Boom:
            def __init__(self, *a, **k):
                pass

            async def correct(self, text):
                raise handlers.stt_correct_service.SttCorrectionError("boom")

        monkeypatch.setattr(handlers.stt_correct_service, "LlmSttCorrector", _Boom)
    elif corrector_result is not None:
        async def fake_correct(settings, text):
            return corrector_result

        monkeypatch.setattr(
            handlers.stt_correct_service, "correct_transcript", fake_correct
        )
    # وگرنه پیاده‌سازیِ واقعیِ correct_transcript صدا زده می‌شود (که چون
    # llm_enabled=False است، خودش متنِ خام را بدون تغییر برمی‌گرداند).

    from hesabyar.db.store import Store
    from tests.fakes import FakeClient, FakeSpreadsheet

    async def build():
        store = Store(FakeSpreadsheet(), client=FakeClient(), folder_id="f")
        await store.load()
        provider = _FakeSttProvider(raw_text)
        ctx = _ctx(store, stt_provider=provider, llm_creds=llm_creds)
        msg = _Msg(voice=_Voice())
        update = _update(msg)
        await handlers.on_voice(update, ctx)
        return msg, provider

    msg, provider = asyncio.run(build())
    return msg, provider, routed


class TestVoiceCorrectionWiring:
    def test_llm_correction_reaches_route_text(self, monkeypatch):
        """وقتی اصلاح‌کننده متن را تغییر می‌دهد، متنِ اصلاح‌شده به _route_text می‌رود."""
        msg, provider, routed = _run_on_voice(
            monkeypatch,
            raw_text="۲۰ میلیون چوب فروش",
            llm_creds=("http://x/v1", "k", "gpt-4o-mini"),
            corrector_result="۲۰ میلیون چوب فروختم",
        )
        assert provider.calls == 1
        assert routed["text"] == "۲۰ میلیون چوب فروختم"
        # پیامِ «شنیدم» هم باید متنِ نهاییِ اصلاح‌شده را نشان بدهد.
        heard = next(r for r in msg.replies if r["text"].startswith("🎙 شنیدم"))
        assert heard["text"] == texts.VOICE_HEARD.format(text="۲۰ میلیون چوب فروختم")

    def test_llm_disabled_keeps_raw_text(self, monkeypatch):
        """بدون LLM، متنِ خامِ STT بدون تغییر به _route_text می‌رود."""
        msg, provider, routed = _run_on_voice(
            monkeypatch, raw_text="۲۰ میلیون چوب فروش", llm_creds=None,
        )
        assert routed["text"] == "۲۰ میلیون چوب فروش"

    def test_correction_error_falls_back_to_raw_text(self, monkeypatch):
        """اگر اصلاح‌کننده خطا بدهد، روند متوقف نمی‌شود و متنِ خام استفاده می‌شود."""
        msg, provider, routed = _run_on_voice(
            monkeypatch,
            raw_text="۲۰ میلیون چوب فروش",
            llm_creds=("http://x/v1", "k", "gpt-4o-mini"),
            corrector_raises=True,
        )
        assert routed["text"] == "۲۰ میلیون چوب فروش"
        assert not any("خطا" in r["text"] for r in msg.replies if r is not None)
