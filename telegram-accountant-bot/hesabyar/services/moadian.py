"""اسکلتِ اتصال به «سامانه‌ی مودیان» (صورتحساب الکترونیکی).

.. warning::

    این ماژول یک **اسکلت** است و **گواهی‌شده نیست**. یکپارچگی واقعی با
    «سامانه‌ی مودیانِ» سازمان امور مالیاتی به گواهی/کلید اختصاصی، امضای
    دیجیتال و دست‌دادنِ رمزنگاری (رمزنگاری کلید عمومی و دریافت «شناسه‌ی
    یکتای حافظه‌ی مالیاتی») نیاز دارد که اینجا پیاده‌سازی نشده است.

هدف این نسخه فقط **آماده‌سازی نگاشت داده و کلاینت** به‌شکلی تمیز و
تست‌پذیر است تا بعداً بتوان لایه‌ی رمزنگاری واقعی را روی آن سوار کرد:

* :func:`compute_totals` — محاسبه‌ی جمع، مالیات بر ارزش افزوده و مبلغ نهایی.
* :func:`build_invoice_payload` — نگاشت یک :class:`~hesabyar.db.models.Invoice`
  به ساختار دیکشنریِ نزدیک به استاندارد مودیان (کلیدها ساده‌شده‌اند).
* :class:`MoadianClient` — کلاینت واقعی (HTTP) برای ارسال صورتحساب.
* :class:`DryRunMoadianClient` — «اجرای آزمایشی»؛ بدون شبکه و کاملاً قطعی.
* :func:`get_moadian_client` — انتخاب کلاینت بر اساس تنظیمات.

قواعد مشترک پروژه رعایت شده‌اند: همه‌ی مبالغ عدد صحیح و به «تومان»‌اند و
تاریخ‌ها با :mod:`hesabyar.core.jalali` قالب‌بندی می‌شوند.
"""
from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any, Optional

import httpx

from ..core import jalali

if TYPE_CHECKING:  # فقط برای type hint؛ در زمان اجرا وابستگی ایجاد نمی‌کند.
    from ..db.models import Invoice, User

#: مهلت پیش‌فرض درخواست شبکه (ثانیه).
_DEFAULT_TIMEOUT = 60.0

#: نرخ پیش‌فرض مالیات بر ارزش افزوده (۹٪).
DEFAULT_VAT_RATE = 0.09


class MoadianUnavailable(Exception):
    """وقتی سامانه‌ی مودیان در دسترس نیست یا پاسخ معتبری نمی‌دهد."""


# --- نگاشت داده --------------------------------------------------------------


def compute_totals(invoice: "Invoice", vat_rate: float) -> dict[str, int]:
    """جمع کل، مالیات و مبلغ نهاییِ یک فاکتور را محاسبه می‌کند.

    :param invoice: شیئی با ویژگی ``total`` (جمع اقلام به تومان).
    :param vat_rate: نرخ مالیات بر ارزش افزوده (مثلاً ``0.09`` برای ۹٪).
    :returns: دیکشنری ``{'subtotal': int, 'vat': int, 'total': int}`` که در آن
        ``subtotal`` جمع پیش از مالیات، ``vat`` مالیات گرد‌شده و ``total``
        مجموع این دو است. همه‌ی مقادیر عدد صحیح و به «تومان»‌اند.
    """
    subtotal = int(invoice.total)
    vat = round(subtotal * vat_rate)
    total = subtotal + vat
    return {"subtotal": subtotal, "vat": vat, "total": total}


def build_invoice_payload(
    invoice: "Invoice",
    business: "User | None",
    *,
    economic_code: str = "",
    seller_tin: str = "",
    buyer_tin: str = "",
    vat_rate: float = DEFAULT_VAT_RATE,
) -> dict[str, Any]:
    """یک :class:`~hesabyar.db.models.Invoice` را به ساختار صورتحساب مودیان نگاشت می‌کند.

    نام کلیدها ساده‌شده ولی نزدیک به استاندارد سامانه‌ی مودیان است
    (مثلاً ``inno`` شماره‌ی صورتحساب، ``indati2m`` تاریخ صدور، ``tin``
    شناسه‌ی مالیاتی، ``fee`` مبلغ واحد، ``vam`` مالیات ردیف).

    :param invoice: فاکتور مبدأ (با ویژگی‌های ``number``/``issue_date``/
        ``customer_name`` و فهرست ``items``).
    :param business: کسب‌وکار فروشنده (:class:`~hesabyar.db.models.User`) یا
        ``None``؛ اگر ``None`` باشد نام فروشنده خالی می‌ماند.
    :param economic_code: کد اقتصادی فروشنده.
    :param seller_tin: شناسه‌ی ملی/مالیاتی فروشنده.
    :param buyer_tin: شناسه‌ی ملی/مالیاتی خریدار.
    :param vat_rate: نرخ مالیات بر ارزش افزوده.
    :returns: دیکشنری ``{'header': ..., 'body': [...], 'totals': ...}``.
    """
    header: dict[str, Any] = {
        "inno": invoice.number,  # شماره‌ی صورتحساب
        "indati2m": jalali.format_date(invoice.issue_date),  # تاریخ صدور (شمسی)
        "inty": 1,  # نوع صورتحساب (۱ = اصلی)
        "setm": 1,  # روش تسویه (۱ = نقدی)
        "seller": {
            "tin": seller_tin,
            "economic_code": economic_code,
            "name": getattr(business, "business_name", "") or "",
        },
        "buyer": {
            "tin": buyer_tin,
            "name": invoice.customer_name,
        },
    }

    body: list[dict[str, Any]] = []
    for item in invoice.items:
        body.append(
            {
                "sstid": "",  # شناسه‌ی کالا/خدمت (در این نسخه خالی)
                "sstt": item.title,  # شرح کالا/خدمت
                "am": int(item.quantity),  # تعداد/مقدار
                "fee": int(item.unit_price),  # مبلغ واحد
                "prdis": 0,  # مبلغ تخفیف پیش از مالیات
                "dis": 0,  # مبلغ تخفیف
                "vra": vat_rate,  # نرخ مالیات بر ارزش افزوده
                "vam": round(item.line_total * vat_rate),  # مبلغ مالیات ردیف
                "tsstam": int(item.line_total),  # مبلغ کل ردیف (پیش از مالیات)
            }
        )

    totals = compute_totals(invoice, vat_rate)
    return {"header": header, "body": body, "totals": totals}


# --- کلاینت‌ها ----------------------------------------------------------------


class MoadianClient:
    """کلاینت HTTP برای ارسال صورتحساب به یک درگاهِ سازگار با مودیان.

    .. note::

        این کلاینت صرفاً بدنه‌ی صورتحساب را به‌صورت JSON و با هدر
        ``Authorization: Bearer`` می‌فرستد؛ **امضای دیجیتال و رمزنگاری واقعیِ
        موردنیاز سازمان مالیاتی را انجام نمی‌دهد.**

    :param base_url: نشانی پایه‌ی درگاه.
    :param token: توکن احراز هویت (به‌صورت ``Bearer``).
    :param client: کلاینت ``httpx.AsyncClient`` اختیاری؛ برای تزریق در تست.
        اگر داده شود، مالکیت و بستن آن با فراخواننده است و :meth:`submit`
        آن را نمی‌بندد.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._client = client

    async def submit(self, payload: dict) -> dict:
        """صورتحساب را به سامانه می‌فرستد و پاسخ JSON را برمی‌گرداند.

        در صورت خطای HTTP یا شبکه، :class:`MoadianUnavailable` می‌اندازد.
        """
        url = f"{self._base_url}/invoices"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

        client = self._client or httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT)
        owns_client = self._client is None
        try:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:  # خطای شبکه/HTTP
            raise MoadianUnavailable(
                f"خطا در ارتباط با سامانه‌ی مودیان: {exc}"
            ) from exc
        finally:
            # کلاینتِ تزریق‌شده را نمی‌بندیم؛ فقط کلاینت خودمان را.
            if owns_client:
                await client.aclose()


class DryRunMoadianClient:
    """کلاینت «اجرای آزمایشی»؛ بدون شبکه و کاملاً قطعی.

    برای آزمایش گردش کار بدون گواهی و بدون تماس با سازمان مالیاتی به کار
    می‌رود. خروجی هیچ عنصر تصادفی یا وابسته به زمان ندارد تا نتیجه برای یک
    ورودی ثابت همیشه یکسان باشد.
    """

    async def submit(self, payload: dict) -> dict:
        """یک مرجع قطعی برمی‌گرداند بدون آنکه چیزی به‌جایی ارسال شود.

        مرجع از هشِ پایدارِ (SHA-1) شماره‌ی صورتحساب ساخته می‌شود، چون
        ``hash`` داخلی پایتون بین اجراهای مختلف قطعی نیست.
        """
        inno = payload["header"]["inno"]
        digest = hashlib.sha1(str(inno).encode()).hexdigest()[:8]
        return {"status": "dry-run", "reference": f"DRYRUN-{digest}"}


def get_moadian_client(settings: Any) -> "MoadianClient | DryRunMoadianClient":
    """کلاینت مودیان را بر اساس تنظیمات انتخاب می‌کند.

    تنظیمات به‌صورت دفاعی با :func:`getattr` خوانده می‌شوند تا نبودِ فیلدهای
    مودیان خطا ندهد. اگر **هم** ``moadian_base_url`` و **هم** ``moadian_token``
    موجود باشند یک :class:`MoadianClient` واقعی، وگرنه یک
    :class:`DryRunMoadianClient` برگردانده می‌شود.
    """
    base = getattr(settings, "moadian_base_url", None)
    token = getattr(settings, "moadian_token", None)
    if base and token:
        return MoadianClient(base, token)
    return DryRunMoadianClient()
