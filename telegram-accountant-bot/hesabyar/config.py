"""پیکربندی برنامه از روی متغیرهای محیطی.

همه‌ی تنظیمات از فایل ``.env`` یا متغیرهای محیطی خوانده می‌شوند تا هیچ
مقدار حساسی (توکن بات، کلید سرویس‌ها) داخل کد قرار نگیرد.
"""
from __future__ import annotations

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
    database_url: str = "sqlite:///hesabyar.db"
    default_currency: str = "تومان"
    # ساعت محلی ارسال یادآوری روزانه‌ی سررسیدها (۰ تا ۲۳)
    reminder_hour: int = 9
    reminder_minute: int = 0
    # سرویس OCR اختیاری (سازگار با API نوع OpenAI برای مدل‌های تصویری)
    ocr_base_url: str | None = None
    ocr_api_key: str | None = None
    ocr_model: str = "gpt-4o-mini"
    admin_ids: tuple[int, ...] = field(default_factory=tuple)
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
    # پشتیبان‌گیری
    backup_dir: str = ""  # پوشه‌ی نگه‌داری پشتیبان دیتابیس (خالی = کنار دیتابیس)
    backup_weekly: bool = True  # پشتیبان‌گیری هفتگی خودکار دیتابیس

    @property
    def ocr_enabled(self) -> bool:
        return bool(self.ocr_base_url and self.ocr_api_key)


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

    admin_raw = _get("ADMIN_IDS", "")
    admin_ids: tuple[int, ...] = tuple(
        int(part) for part in (admin_raw or "").replace(" ", "").split(",") if part
    )

    return Settings(
        bot_token=token or "",
        database_url=_get("DATABASE_URL", "sqlite:///hesabyar.db"),
        default_currency=_get("DEFAULT_CURRENCY", "تومان"),
        reminder_hour=_get_int("REMINDER_HOUR", 9),
        reminder_minute=_get_int("REMINDER_MINUTE", 0),
        ocr_base_url=_get("OCR_BASE_URL"),
        ocr_api_key=_get("OCR_API_KEY"),
        ocr_model=_get("OCR_MODEL", "gpt-4o-mini"),
        admin_ids=admin_ids,
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
        backup_dir=_get("BACKUP_DIR", ""),
        backup_weekly=_get_bool("BACKUP_WEEKLY", True),
    )
