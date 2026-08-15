"""اصلاحِ متنِ خروجیِ رونویسیِ صوت (STT) با یک مدل زبانی.

Whisper (و مشابه‌هایش) گاهی کلماتِ فارسیِ هم‌آوا/مشابه را اشتباه تشخیص
می‌دهد (مثلاً «۲۰ میلیون چوب فروختم» → «۲۰ میلیون چوب فروش»). این ماژول
متنِ خامِ STT را از یک مدلِ زبانی (سازگار با API نوع OpenAI، همان
اعتبارنامه‌ی :mod:`hesabyar.services.extract`) عبور می‌دهد تا **فقط** همین
نوع خطاهای شنیداری اصلاح شوند — بدون افزودنِ اطلاعات، بدون تغییرِ معنی،
بدون خلاصه‌سازی یا بازنویسیِ سبکی.

:class:`LlmSttCorrector` — پیاده‌سازیِ واقعی.
:func:`correct_transcript` — نقطه‌ی ورودِ واحد: اگر LLM فعال باشد اصلاح
می‌کند؛ در هر خطایی (شبکه، پاسخ نامعتبر، غیرفعال بودنِ LLM) متنِ خام را
بدون تغییر برمی‌گرداند — این مرحله هرگز نباید ثبتِ تراکنش را متوقف کند.
"""
from __future__ import annotations

from typing import Optional

import httpx

#: مهلتِ کوتاه تا تجربه‌ی کاربر (ویس→متن) کند نشود.
_DEFAULT_TIMEOUT = 15.0

_SYSTEM_PROMPT = (
    "تو یک ویراستارِ متنِ رونویسیِ صوت به فارسی هستی، مخصوصِ یک بات حسابداری "
    "که کاربران با ویس تراکنشِ مالی ثبت می‌کنند (فعل‌های رایج: فروختم، "
    "خریدم، پرداخت کردم، گرفتم، هزینه کردم). فقط خطاهای احتمالیِ رونویسیِ "
    "صوت به متن را اصلاح کن — کلماتِ هم‌آوا یا مشابه که موتورِ تشخیصِ گفتار "
    "اشتباه شنیده است.\n"
    "- هیچ اطلاعاتِ جدیدی اضافه نکن، معنیِ جمله را عوض نکن، خلاصه یا "
    "بازنویسیِ سبکی نکن.\n"
    "- ارقام و مبلغ‌ها را دست نزن، مگر اینکه خودِ عدد بخشی از خطای شنیداری "
    "باشد (مثلاً یکی‌شدنِ دو کلمه با یک عدد)؛ در حالتِ شک، عدد را دقیقاً "
    "همان‌طور که هست نگه دار.\n"
    "- جمله باید در بافتِ حسابداری/فروش/خریدِ فارسی معنی داشته باشد.\n"
    "- اگر متن از قبل درست به نظر می‌رسد، همان را بدون تغییر برگردان.\n"
    "فقط متنِ اصلاح‌شده را برگردان — بدون توضیح، بدون گیومه، بدون JSON."
)


class SttCorrectionError(Exception):
    """وقتی اصلاح با LLM شکست می‌خورد (برای بازگشت به متنِ خامِ STT)."""


class LlmSttCorrector:
    """اصلاحِ متنِ رونویسی با یک مدلِ زبانیِ سازگار با API نوع OpenAI.

    :param base_url: نشانی پایه‌ی درگاه.
    :param api_key: کلید احراز هویت (به‌صورت ``Bearer``).
    :param model: نامِ مدل.
    :param client: کلاینتِ ``httpx.AsyncClient`` اختیاری؛ برای تزریق در تست.
        اگر داده شود، مالکیت و بستنش با فراخواننده است.
    :param timeout: مهلتِ درخواست (ثانیه).
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        client: Optional[httpx.AsyncClient] = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._client = client
        self._timeout = timeout

    async def correct(self, text: str) -> str:
        """متنِ اصلاح‌شده را برمی‌گرداند؛ در صورتِ خطا :class:`SttCorrectionError`."""
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            "temperature": 0,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/chat/completions"
        own = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError) as exc:
            raise SttCorrectionError(
                "خطا در تماس با LLM برای اصلاحِ متنِ صوت."
            ) from exc
        finally:
            if own:
                await client.aclose()

        corrected = (content or "").strip()
        return corrected or text


async def correct_transcript(settings, text: str) -> str:
    """نقطه‌ی ورودِ واحد: اگر LLM فعال باشد متنِ STT را اصلاح می‌کند.

    هیچ خطایی از این تابع بیرون نمی‌رود: LLM غیرفعال، بدون اعتبارنامه، یا
    هر خطای شبکه/پاسخ یعنی همان متنِ ورودی بدون تغییر برگردد — این مرحله
    هرگز نباید باعثِ توقفِ روندِ ثبتِ تراکنش شود.
    """
    if not text:
        return text
    if not getattr(settings, "llm_enabled", False):
        return text
    creds = settings.llm_creds
    if not creds:
        return text
    try:
        return await LlmSttCorrector(*creds).correct(text)
    except SttCorrectionError:
        return text
