"""لوگو و مهر: آوردنِ تصویر از تلگرام و نگه‌داشتنش برای رندرِ فاکتور.

گوگل‌شیت جای فایلِ باینری نیست، پس روی پروفایلِ کاربر فقط ``file_id`` تلگرام
ذخیره می‌شود — یک رشته‌ی کوتاه که برای همین بات دائمی است. اینجا آن رشته به
یک فایلِ PNG روی دیسک تبدیل می‌شود تا :mod:`hesabyar.pdf.invoice_pdf` بتواند
آن را روی سند بنشاند.

هر فاکتور یعنی دو رندر (عکس + PDF) و هر رندر یعنی دو تصویر؛ بدون کش، صدورِ
یک فاکتور چهار بار همان لوگو را از تلگرام می‌گرفت. پس نتیجه روی دیسک کش
می‌شود و دفعه‌ی بعد فقط یک ``isfile`` هزینه دارد. کش با ``file_id`` کلید
می‌خورد و ``file_id`` با هر آپلودِ تازه عوض می‌شود، پس هرگز کهنه نمی‌ماند.

قاعده‌ی کلی: **هیچ خطایی نباید صدورِ فاکتور را زمین بزند.** اگر تلگرام جواب
نداد یا فایل خراب بود، تابع رشته‌ی خالی برمی‌گرداند و فاکتور بدون لوگو صادر
می‌شود — نه اینکه کاربر پیغام خطا بگیرد.
"""
from __future__ import annotations

import hashlib
import io
import logging
import os
import tempfile
from collections import OrderedDict

from ..core import seller

log = logging.getLogger(__name__)

#: بیشترین ضلعِ تصویرِ ذخیره‌شده. لوگو روی کاغذ چند سانتی‌متر است؛ بزرگ‌تر از
#: این فقط حجمِ PDF را باد می‌کند.
MAX_SIDE = 900

#: سقفِ حجمِ فایلِ ورودی (تلگرام خودش هم محدودیت دارد؛ این کمربندِ دوم است).
MAX_BYTES = 5 * 1024 * 1024

#: چند تصویر در کش بماند (لوگو و مهرِ ۳۲ کسب‌وکار).
MAX_ENTRIES = 64

#: ``file_id`` ← مسیرِ فایلِ PNG روی دیسک.
_CACHE: "OrderedDict[str, str]" = OrderedDict()


def _cache_path(file_id: str) -> str:
    digest = hashlib.sha1(file_id.encode("utf-8")).hexdigest()[:16]
    return os.path.join(tempfile.gettempdir(), f"hesabyar-img-{digest}.png")


def normalize(raw: bytes) -> bytes | None:
    """بایت‌های خام را به PNGِ اندازه‌شده تبدیل می‌کند؛ ``None`` اگر تصویر نبود.

    شفافیت (کانالِ آلفا) حفظ می‌شود — لوگویی که پس‌زمینه‌ی شفاف دارد نباید
    روی کاغذ یک مربعِ سفید شود.
    """
    if not raw or len(raw) > MAX_BYTES:
        return None
    try:
        from PIL import Image

        with Image.open(io.BytesIO(raw)) as img:
            img.load()
            img = img.convert("RGBA" if _has_alpha(img) else "RGB")
            if max(img.size) > MAX_SIDE:
                img.thumbnail((MAX_SIDE, MAX_SIDE))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
    except Exception:  # فایلِ خراب، فرمتِ ناشناخته، یا نبودِ Pillow
        log.warning("normalize image failed", exc_info=True)
        return None


def _has_alpha(img) -> bool:
    return img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info


async def path_for(bot, file_id: str) -> str:
    """``file_id`` را به مسیرِ یک فایلِ PNG تبدیل می‌کند (یا رشته‌ی خالی).

    خطا هرگز بالا نمی‌رود؛ نبودِ لوگو دلیلِ نرسیدنِ فاکتور نیست.
    """
    file_id = (file_id or "").strip()
    if not file_id or bot is None:
        return ""

    cached = _CACHE.get(file_id)
    if cached and os.path.isfile(cached):
        _CACHE.move_to_end(file_id)
        return cached
    _CACHE.pop(file_id, None)  # کش داشتیم ولی فایلش پاک شده بود

    try:
        tg_file = await bot.get_file(file_id)
        raw = bytes(await tg_file.download_as_bytearray())
    except Exception:
        log.warning("could not download file_id=%s", file_id[:16], exc_info=True)
        return ""

    data = normalize(raw)
    if data is None:
        return ""

    path = _cache_path(file_id)
    try:
        with open(path, "wb") as fh:
            fh.write(data)
    except OSError:
        log.warning("could not write image cache", exc_info=True)
        return ""

    _CACHE[file_id] = path
    while len(_CACHE) > MAX_ENTRIES:
        _, stale = _CACHE.popitem(last=False)
        try:
            os.remove(stale)
        except OSError:
            pass
    return path


async def seller_images(bot, source) -> dict:
    """مسیرِ لوگو و مهر برای رندر — آماده‌ی پاس‌دادن به رندرکننده.

    ``source`` یا فاکتور است (با اسنپ‌شاتِ ``seller_*``) یا کاربر؛ اولویت با
    اسنپ‌شات است تا فاکتورِ قدیمی همان لوگویی را داشته باشد که مشتری دیده.
    """
    return {
        "logo_path": await path_for(bot, seller.image_of(source, "logo_file_id")),
        "stamp_path": await path_for(bot, seller.image_of(source, "stamp_file_id")),
    }


def clear_cache() -> None:
    """خالی‌کردنِ کش (برای تست‌ها و ری‌استارتِ نرم)."""
    _CACHE.clear()
