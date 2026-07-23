"""استخراج ساختاریافته‌ی تراکنش از متن (پیام کاربر یا متن OCR فاکتور).

دو پیاده‌سازی:

* :class:`LlmExtractor` — با یک مدل زبانی (سازگار با API نوع OpenAI) نوع،
  مبلغ، دسته، تاریخ، **فروشنده** و **شماره فاکتور** را درمی‌آورد.
* :func:`rule_extract` — بدون شبکه؛ از پارسر قاعده‌محور
  (:func:`hesabyar.core.nlp.parse_transaction`) به‌علاوه‌ی چند heuristic برای
  فروشنده و شماره فاکتور استفاده می‌کند.

:func:`extract_transaction` نقطه‌ی ورود واحد است: اگر LLM فعال باشد از آن
استفاده می‌کند و در صورت خطا به روش قاعده‌محور برمی‌گردد.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from typing import Optional

import httpx

from ..core import jalali, money, nlp
from ..core.categories import (
    DEFAULT_EXPENSE,
    DEFAULT_INCOME,
    EXPENSE_CATEGORIES,
    INCOME_CATEGORIES,
)
from ..db.models import Kind


class ExtractError(Exception):
    """خطای استخراج با LLM (برای بازگشت به روش قاعده‌محور)."""


@dataclass
class ExtractedReceipt:
    kind: str
    amount: int
    category: str
    description: str
    occurred_at: dt.datetime
    vendor: str = ""
    invoice_number: str = ""
    raw: str = ""


_ALLOWED_CATEGORIES = (
    [label for label, _ in EXPENSE_CATEGORIES]
    + [DEFAULT_EXPENSE]
    + [label for label, _ in INCOME_CATEGORIES]
    + [DEFAULT_INCOME]
)

_VENDOR_LABEL = re.compile(
    r"(?:فروشنده|نام فروشنده|به ?نام|فروشگاه|شرکت|مغازه)\s*[:\-–]?\s*([^\n]{2,60})"
)
_VENDOR_WORDS = (
    "فروشگاه", "شرکت", "بوتیک", "رستوران", "کافه", "سوپرمارکت",
    "داروخانه", "نانوایی", "قنادی", "هایپر",
)
_INVOICE_NO = re.compile(
    r"(?:شماره ?فاکتور|فاکتور ?شماره|شماره سریال|شماره)\s*[:\-–]?\s*([0-9۰-۹][0-9۰-۹\-/]{2,})"
)


def _guess_vendor(text: str) -> str:
    if not text:
        return ""
    match = _VENDOR_LABEL.search(text)
    if match:
        return match.group(1).strip(" .:،-–")[:60]
    for line in text.splitlines():
        line = line.strip()
        if any(word in line for word in _VENDOR_WORDS):
            return line[:60]
    return ""


def _guess_invoice_number(text: str) -> str:
    if not text:
        return ""
    match = _INVOICE_NO.search(text)
    return match.group(1).strip() if match else ""


def _combine(date: Optional[dt.date], base: dt.datetime) -> dt.datetime:
    if date is None:
        return base
    return dt.datetime(
        date.year, date.month, date.day, base.hour, base.minute, tzinfo=base.tzinfo
    )


def rule_extract(text: str, base: Optional[dt.datetime] = None) -> Optional[ExtractedReceipt]:
    """استخراج قاعده‌محور (بدون شبکه)."""
    base = base or jalali.now()
    parsed = nlp.parse_transaction(text, base=base)
    if parsed is None:
        return None
    return ExtractedReceipt(
        kind=parsed.kind,
        amount=parsed.amount,
        category=parsed.category,
        description=parsed.description,
        occurred_at=parsed.occurred_at,
        vendor=_guess_vendor(text),
        invoice_number=_guess_invoice_number(text),
        raw=text,
    )


def _to_int(value) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    digits = re.sub(r"[^\d]", "", money.to_english_digits(str(value)))
    return int(digits) if digits else None


def _parse_json(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    try:
        obj = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise ExtractError("پاسخ LLM قابل‌تحلیل نبود.") from exc
    if not isinstance(obj, dict):
        raise ExtractError("پاسخ LLM ساختار درستی نداشت.")
    return obj


def _to_receipt(obj: dict, raw: str, base: dt.datetime) -> Optional[ExtractedReceipt]:
    amount = _to_int(obj.get("amount"))
    if amount is None:
        return None
    kind = Kind.INCOME if str(obj.get("type", "")).lower() == "income" else Kind.EXPENSE
    category = (obj.get("category") or "").strip() or (
        DEFAULT_INCOME if kind == Kind.INCOME else DEFAULT_EXPENSE
    )
    date_str = (obj.get("date") or "").strip()
    occurred = jalali.parse_relative_date(date_str, base) if date_str else None
    return ExtractedReceipt(
        kind=kind,
        amount=amount,
        category=category,
        description=(obj.get("description") or "").strip(),
        occurred_at=_combine(occurred, base),
        vendor=(obj.get("vendor") or "").strip()[:60],
        invoice_number=(obj.get("invoice_number") or "").strip()[:40],
        raw=raw,
    )


class LlmExtractor:
    """استخراج با مدل زبانی سازگار با API نوع OpenAI (chat/completions)."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        client: Optional[httpx.AsyncClient] = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._client = client
        self._timeout = timeout

    def _system_prompt(self) -> str:
        cats = "، ".join(dict.fromkeys(_ALLOWED_CATEGORIES))
        return (
            "تو یک دستیار حسابداری فارسی هستی. از متنِ ورودی (پیام کاربر یا متن "
            "OCR یک فاکتور) اطلاعات را استخراج کن و فقط یک شیء JSON برگردان با "
            "این کلیدها: "
            "type (یکی از 'income' یا 'expense')، "
            "amount (مبلغ به تومان، عدد صحیح؛ اگر مبلغ به ریال بود تقسیم بر ۱۰ کن؛ "
            "اگر مبلغی نبود null)، "
            f"category (یکی از این‌ها: {cats})، "
            "date (تاریخ شمسی به شکل YYYY/MM/DD اگر در متن بود، وگرنه رشته‌ی خالی)، "
            "description (توضیح کوتاه)، "
            "vendor (نام فروشنده/طرف‌حساب اگر بود)، "
            "invoice_number (شماره فاکتور اگر بود). "
            "فقط JSON خروجی بده، بدون توضیح اضافه."
        )

    async def extract(
        self, text: str, base: Optional[dt.datetime] = None
    ) -> Optional[ExtractedReceipt]:
        base = base or jalali.now()
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": text},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
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
            raise ExtractError("خطا در تماس با LLM.") from exc
        finally:
            if own:
                await client.aclose()
        return _to_receipt(_parse_json(content), text, base)


async def extract_transaction(
    settings, text: str, base: Optional[dt.datetime] = None
) -> Optional[ExtractedReceipt]:
    """نقطه‌ی ورود واحد؛ اگر LLM فعال باشد از آن، وگرنه از روش قاعده‌محور."""
    base = base or jalali.now()
    if getattr(settings, "llm_enabled", False):
        creds = settings.llm_creds
        if creds:
            try:
                return await LlmExtractor(*creds).extract(text, base)
            except ExtractError:
                pass  # بازگشت به روش قاعده‌محور
    return rule_extract(text, base)
