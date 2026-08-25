"""دریافت فاکتور/رسید از منابع گوناگون.

کسب‌وکارهای کوچک فاکتورها را به شکل‌های مختلف می‌فرستند: عکس دوربین/گالری،
فایل (عکس یا PDF)، یا لینک. این ماژول همه را به «بایت‌های تصویر» تبدیل می‌کند
تا به سرویس OCR (:mod:`hesabyar.services.ocr`) داده شود.

نکته‌ی امنیتی: دریافت لینک از ورودی کاربر مستعد حمله‌ی SSRF است؛ بنابراین
پیش از دریافت، میزبان به IP تبدیل و بررسی می‌شود که عمومی باشد و تغییر مسیر
(redirect) دنبال نمی‌شود.
"""
from __future__ import annotations

import ipaddress
import re
import socket
from typing import Optional
from urllib.parse import urlparse

import httpx

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_MAX_BYTES = 8 * 1024 * 1024  # ۸ مگابایت
_TIMEOUT = 20.0


class IngestError(Exception):
    """خطای قابل‌نمایش به کاربر هنگام دریافت فاکتور."""


def find_url(text: str) -> Optional[str]:
    """اولین لینک http(s) را از متن پیدا می‌کند (بدون علائم انتهایی)."""
    if not text:
        return None
    match = _URL_RE.search(text)
    if not match:
        return None
    return match.group(0).rstrip(").,؛;!؟‌")


def _ip_is_safe(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _host_is_safe(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    return bool(infos) and all(_ip_is_safe(info[4][0]) for info in infos)


def is_safe_url(url: str) -> bool:
    """آیا لینک برای دریافت امن است؟ (فقط http/https و میزبان عمومی)"""
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    return _host_is_safe(parsed.hostname)


async def fetch_bytes(
    url: str,
    *,
    client: Optional[httpx.AsyncClient] = None,
    check_safety: bool = True,
    timeout: float = _TIMEOUT,
    max_bytes: int = _MAX_BYTES,
) -> tuple[bytes, str]:
    """محتوای یک لینک را دریافت می‌کند و ``(bytes, content_type)`` می‌دهد.

    برای جلوگیری از مصرف حافظه، به‌صورت جریانی و با سقف اندازه خوانده می‌شود.
    تغییر مسیر دنبال نمی‌شود (امنیت SSRF).
    """
    if check_safety and not is_safe_url(url):
        raise IngestError("آدرس نامعتبر یا غیرمجاز است.")
    own_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=timeout, follow_redirects=False)
    try:
        async with client.stream("GET", url) as resp:
            if resp.status_code >= 400:
                raise IngestError(f"دریافت لینک ناموفق بود ({resp.status_code}).")
            content_type = resp.headers.get("content-type", "")
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise IngestError("فایل خیلی بزرگ است.")
                chunks.append(chunk)
            return b"".join(chunks), content_type
    except httpx.HTTPError as exc:
        raise IngestError("خطا در دریافت لینک.") from exc
    finally:
        if own_client:
            await client.aclose()


def looks_like_pdf(raw: bytes, content_type: str = "") -> bool:
    return raw[:5] == b"%PDF-" or "pdf" in (content_type or "").lower()


def pdf_to_image_bytes(pdf_bytes: bytes, dpi: int = 150) -> bytes:
    """نخستین صفحه‌ی PDF را به تصویر PNG تبدیل می‌کند (با pymupdf)."""
    try:
        import fitz  # pymupdf
    except ImportError as exc:  # pragma: no cover - بسته نصب است
        raise IngestError("پشتیبانی از PDF در دسترس نیست.") from exc
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            if doc.page_count == 0:
                raise IngestError("PDF خالی است.")
            pix = doc[0].get_pixmap(dpi=dpi)
            return pix.tobytes("png")
    except IngestError:
        raise
    except Exception as exc:
        raise IngestError("خواندن PDF ناموفق بود.") from exc


def prepare_image(raw: bytes, content_type: str = "") -> bytes:
    """ورودی خام را به بایت‌های تصویر آماده‌ی OCR تبدیل می‌کند.

    اگر PDF باشد، صفحه‌ی اول به تصویر تبدیل می‌شود؛ در غیر این صورت خودِ
    بایت‌ها (تصویر) برگردانده می‌شوند.
    """
    if not raw:
        raise IngestError("محتوایی دریافت نشد.")
    if looks_like_pdf(raw, content_type):
        return pdf_to_image_bytes(raw)
    return raw
