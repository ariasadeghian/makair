"""پیکربندی برنامه از روی متغیرهای محیطی.

همه‌ی تنظیمات از فایل ``.env`` یا متغیرهای محیطی خوانده می‌شوند تا هیچ
مقدار حساسی (توکن بات، کلید سرویس‌ها) داخل کد قرار نگیرد.
"""
from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field

try:  # بارگذاری .env در صورت وجود (اختیاری)
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv همیشه نصب است ولی محض احتیاط
    pass


def _get(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def _get_int(name: str, default: int) -> int:
    raw = _get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    raw = _get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _get_bool(name: str, default: bool = False) -> bool:
    raw = _get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on", "بله")


@dataclass(frozen=True)
class Settings:
    """تنظیمات اجرای بات."""

    bot_token: str
    # داده‌ها روی Google Sheets ذخیره می‌شوند (نه دیتابیس محلی).
    google_service_account_json: str = ""  # کل محتوای JSON کلید سرویس‌اکانت
    google_sheet_id: str = ""  # شناسه‌ی اسپردشیت
    default_currency: str = "تومان"
    # ساعت محلی ارسال یادآوری روزانه‌ی سررسیدها (۰ تا ۲۳)
    reminder_hour: int = 9
    reminder_minute: int = 0
    # چند روز قبل از سررسید هم پیشاپیش یادآوری شود (۰ = فقط روز سررسید و معوق)
    reminder_lead_days: int = 2
    # خلاصه‌ی خودکار شبانه‌ی فعالیت مالی (فقط برای کاربرانِ فعالِ امروز)
    nightly_summary: bool = True
    nightly_summary_hour: int = 21
    # سرویس OCR اختیاری (سازگار با API نوع OpenAI برای مدل‌های تصویری)
    ocr_base_url: str | None = None
    ocr_api_key: str | None = None
    ocr_model: str = "gpt-4o-mini"
    # استخراج هوشمند با LLM (دسته‌بندی/فروشنده/تاریخ). اگر LLM_* تنظیم نشود،
    # از همان تنظیمات OCR استفاده می‌شود.
    use_llm_parser: bool = False
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    # تبدیل گفتار به متن (ویس→متن). سازگار با API نوع OpenAI (whisper). اگر
    # STT_* تنظیم نشود از همان تنظیمات OCR استفاده می‌شود.
    stt_base_url: str | None = None
    stt_api_key: str | None = None
    stt_model: str = "whisper-1"
    stt_language: str = "fa"
    admin_ids: tuple[int, ...] = field(default_factory=tuple)
    # کانالی که نرخ روزانه‌ی دلار را می‌گذارد. بات باید ادمینِ آن باشد تا
    # پست‌ها را ببیند. خالی = فقط ثبت دستی با /rate.
    rate_channel_id: int | None = None
    # نام کاربری بات (برای امضای پای فاکتور در سطح برنزی). اگر خالی بماند
    # هنگام اجرا خودکار از تلگرام گرفته می‌شود.
    bot_username: str = ""
    # پرداخت کارت‌به‌کارت اشتراک
    card_number: str = ""
    card_holder: str = ""
    trial_days: int = 14
    # روش پرداخت اشتراک: 'card' (کارت‌به‌کارت) یا 'zarinpal' (درگاه)
    payment_method: str = "card"
    # درگاه پرداخت زرین‌پال
    zarinpal_merchant_id: str | None = None
    zarinpal_sandbox: bool = False
    payment_callback_url: str = ""
    # سامانه‌ی مودیان (صورتحساب الکترونیکی)
    moadian_base_url: str | None = None
    moadian_token: str | None = None
    seller_tin: str = ""  # شماره اقتصادی/شناسه‌ی فروشنده
    economic_code: str = ""
    vat_rate: float = 0.10  # نرخ مالیات بر ارزش افزوده
    # پشتیبان‌گیری هفتگی خودکار (خروجی اکسل اسپردشیت و ارسال به ادمین‌ها)
    backup_weekly: bool = True

    @property
    def ocr_enabled(self) -> bool:
        return bool(self.ocr_base_url and self.ocr_api_key)

    @property
    def llm_creds(self) -> tuple[str, str, str] | None:
        """(base_url, api_key, model) برای LLM؛ با fallback به تنظیمات OCR."""
        base = self.llm_base_url or self.ocr_base_url
        key = self.llm_api_key or self.ocr_api_key
        model = self.llm_model or self.ocr_model
        if base and key:
            return (base, key, model)
        return None

    @property
    def llm_enabled(self) -> bool:
        return self.use_llm_parser and self.llm_creds is not None

    @property
    def stt_creds(self) -> tuple[str, str, str, str] | None:
        """(base_url, api_key, model, language) برای STT؛ با fallback به OCR."""
        base = self.stt_base_url or self.ocr_base_url
        key = self.stt_api_key or self.ocr_api_key
        if base and key:
            return (base, key, self.stt_model, self.stt_language)
        return None

    @property
    def stt_enabled(self) -> bool:
        return self.stt_creds is not None


def load_settings(require_token: bool = True) -> Settings:
    """ساخت شیء تنظیمات از محیط.

    اگر ``require_token`` درست باشد و توکن بات تنظیم نشده باشد، خطا می‌دهد.
    در تست‌ها می‌توان با ``require_token=False`` این بررسی را رد کرد.
    """
    token = _get("BOT_TOKEN") or _get("TELEGRAM_BOT_TOKEN")
    if require_token and not token:
        raise RuntimeError(
            "متغیر محیطی BOT_TOKEN تنظیم نشده است. مقدار توکن بات تلگرام را در "
            "فایل .env یا محیط سیستم قرار دهید."
        )

    google_json = _get_google_json()
    sheet_id = _get("GOOGLE_SHEET_ID", "")
    if require_token and (not google_json or not sheet_id):
        raise RuntimeError(
            "تنظیمات Google Sheets ناقص است: GOOGLE_SERVICE_ACCOUNT_JSON_B64 "
            "(یا GOOGLE_SERVICE_ACCOUNT_JSON) و GOOGLE_SHEET_ID را تنظیم کنید."
        )

    admin_raw = _get("ADMIN_IDS", "")
    admin_ids: tuple[int, ...] = tuple(
        int(part) for part in (admin_raw or "").replace(" ", "").split(",") if part
    )

    return Settings(
        bot_token=token or "",
        google_service_account_json=google_json,
        google_sheet_id=sheet_id,
        default_currency=_get("DEFAULT_CURRENCY", "تومان"),
        reminder_hour=_get_int("REMINDER_HOUR", 9),
        reminder_minute=_get_int("REMINDER_MINUTE", 0),
        reminder_lead_days=_get_int("REMINDER_LEAD_DAYS", 2),
        nightly_summary=_get_bool("NIGHTLY_SUMMARY", True),
        nightly_summary_hour=_get_int("NIGHTLY_SUMMARY_HOUR", 21),
        ocr_base_url=_get("OCR_BASE_URL"),
        ocr_api_key=_get("OCR_API_KEY"),
        ocr_model=_get("OCR_MODEL", "gpt-4o-mini"),
        use_llm_parser=_get_bool("USE_LLM_PARSER", False),
        llm_base_url=_get("LLM_BASE_URL"),
        llm_api_key=_get("LLM_API_KEY"),
        llm_model=_get("LLM_MODEL"),
        stt_base_url=_get("STT_BASE_URL"),
        stt_api_key=_get("STT_API_KEY"),
        stt_model=_get("STT_MODEL", "whisper-1"),
        stt_language=_get("STT_LANGUAGE", "fa"),
        admin_ids=admin_ids,
        rate_channel_id=_get_int("RATE_CHANNEL_ID", 0) or None,
        bot_username=(_get("BOT_USERNAME", "") or "").lstrip("@"),
        card_number=_get("CARD_NUMBER", ""),
        card_holder=_get("CARD_HOLDER", ""),
        trial_days=_get_int("TRIAL_DAYS", 14),
        payment_method=_get("PAYMENT_METHOD", "card"),
        zarinpal_merchant_id=_get("ZARINPAL_MERCHANT_ID"),
        zarinpal_sandbox=_get_bool("ZARINPAL_SANDBOX", False),
        payment_callback_url=_get("PAYMENT_CALLBACK_URL", ""),
        moadian_base_url=_get("MOADIAN_BASE_URL"),
        moadian_token=_get("MOADIAN_TOKEN"),
        seller_tin=_get("SELLER_TIN", ""),
        economic_code=_get("ECONOMIC_CODE", ""),
        vat_rate=_get_float("VAT_RATE", 0.10),
        backup_weekly=_get_bool("BACKUP_WEEKLY", True),
    )


def _get_google_json() -> str:
    """محتوای JSON کلید سرویس‌اکانت را از محیط می‌خواند.

    ترجیحاً از ``GOOGLE_SERVICE_ACCOUNT_JSON_B64`` (base64، امن‌تر برای
    Variables) و در صورت نبود از ``GOOGLE_SERVICE_ACCOUNT_JSON`` خام.
    """
    b64 = _get("GOOGLE_SERVICE_ACCOUNT_JSON_B64")
    if b64:
        try:
            return base64.b64decode(b64).decode("utf-8")
        except Exception:
            return ""
    return _get("GOOGLE_SERVICE_ACCOUNT_JSON", "") or ""
