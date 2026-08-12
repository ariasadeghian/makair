"""پلن‌های اشتراک: سه سطح (برنزی/نقره‌ای/طلایی) در دو مدت.

منطق سطح‌بندی: هسته‌ی محصول (ثبت، گزارش، دفتر طلب و بدهی، یادآوری) در
**همه‌ی** سطح‌ها باز است تا کاربر از روز اول ارزش را حس کند؛ چیزهایی که هزینه‌ی
سرویس دارند (ویس، خواندن عکس) یا برای کسب‌وکار جدی‌ترند (گروه/شعبه، نمای دلاری)
در سطح‌های بالاتر باز می‌شوند.

در سطح برنزی، پای فاکتور و صورتحساب یک امضای کوچکِ بات می‌آید — هم انگیزه‌ی
ارتقا می‌سازد و هم بات را جلوی مشتریانِ کاربر معرفی می‌کند.
"""
from __future__ import annotations

#: مدت دوره‌ی آزمایشی رایگان (روز)
TRIAL_DAYS = 14


class Feature:
    """کلیدِ قابلیت‌هایی که بسته به سطحِ اشتراک باز/بسته می‌شوند."""

    NO_WATERMARK = "no_watermark"   # حذف امضای بات از فاکتور و صورتحساب
    VOICE = "voice"                 # ثبت با پیام صوتی
    OCR = "ocr"                     # خواندن عکس/فایل فاکتور
    STATEMENT = "statement"         # کارت صورتحساب طرف‌حساب
    DOLLAR = "dollar"               # نمای دلاری درآمد
    GROUP = "group"                 # دفتر مالی گروه/شعبه


#: سطح‌ها و قابلیت‌هایشان (هر سطح شاملِ سطح پایین‌تر است).
TIERS: dict[str, dict] = {
    "bronze": {
        "label": "🥉 برنزی",
        "tagline": "دفترداری روزمره",
        "features": frozenset(),
    },
    "silver": {
        "label": "🥈 نقره‌ای",
        "tagline": "بدون امضای بات + ویس و عکس فاکتور",
        "features": frozenset({
            Feature.NO_WATERMARK, Feature.VOICE, Feature.OCR, Feature.STATEMENT,
        }),
    },
    "gold": {
        "label": "🥇 طلایی",
        "tagline": "همه‌چیز + گروه/شعبه و نمای دلاری",
        "features": frozenset({
            Feature.NO_WATERMARK, Feature.VOICE, Feature.OCR, Feature.STATEMENT,
            Feature.DOLLAR, Feature.GROUP,
        }),
    },
}

#: ترتیب نمایش سطح‌ها (از پایین به بالا)
TIER_ORDER = ["bronze", "silver", "gold"]

#: کلید هر پلن به مشخصاتش. کلید = "{tier}_{duration}"
PLANS: dict[str, dict] = {
    "bronze_monthly": {"tier": "bronze", "label": "🥉 برنزی — ماهانه",
                       "days": 30, "price": 100_000},
    "bronze_yearly": {"tier": "bronze", "label": "🥉 برنزی — یک‌ساله",
                      "days": 365, "price": 900_000},
    "silver_monthly": {"tier": "silver", "label": "🥈 نقره‌ای — ماهانه",
                       "days": 30, "price": 200_000},
    "silver_yearly": {"tier": "silver", "label": "🥈 نقره‌ای — یک‌ساله",
                      "days": 365, "price": 1_800_000},
    "gold_monthly": {"tier": "gold", "label": "🥇 طلایی — ماهانه",
                     "days": 30, "price": 350_000},
    "gold_yearly": {"tier": "gold", "label": "🥇 طلایی — یک‌ساله",
                    "days": 365, "price": 3_200_000},
}

#: ترتیب نمایش پلن‌ها در کیبورد
PLAN_ORDER = [
    "bronze_monthly", "bronze_yearly",
    "silver_monthly", "silver_yearly",
    "gold_monthly", "gold_yearly",
]

#: سطحِ دوره‌ی آزمایشی — کاربر جدید همه‌چیز را می‌بیند تا ارزش را بچشد.
TRIAL_TIER = "gold"


# --- معماریِ سطحِ «رایگان» (آماده‌سازی — فعلاً هیچ‌جا اجرا نمی‌شود) --------------
#
# امروز هسته‌ی محصول (ثبت/گزارش/دفتر) روی هر سه پلنِ پولی نامحدود است؛ اگر
# اشتراکی فعال نباشد هم کاربر قطع نمی‌شود (``subscription.has_feature`` سطحِ
# برنزی را برمی‌گرداند، نه قطعِ کامل). این بخش فقط داده و یک تابعِ محاسبه
# برای یک سقفِ رایگانِ *احتمالی* در آینده آماده می‌کند — طبق درخواستِ محصول
# («فقط معماری، فعلاً اجرا نکن») هیچ هندلر/جریانی این‌ها را صدا نمی‌زند و
# هیچ کاربری با آن‌ها بلاک نمی‌شود.
FREE_LIMITS: dict = {
    "max_transactions_per_month": 30,
    "max_invoices_per_month": 10,
    "max_users": 1,  # بدون شعبه/کارمندِ اضافه
}


def get_plan(key: str) -> dict | None:
    """مشخصات یک پلن را برمی‌گرداند (یا ``None`` اگر نامعتبر باشد)."""
    return PLANS.get(key)


def tier_of(plan_key: str) -> str:
    """سطحِ یک پلن؛ برای «trial» سطحِ آزمایشی و برای نامعتبر «bronze»."""
    if plan_key == "trial":
        return TRIAL_TIER
    plan = PLANS.get(plan_key)
    return plan["tier"] if plan else "bronze"


def tier_features(tier: str) -> frozenset[str]:
    """قابلیت‌های یک سطح."""
    info = TIERS.get(tier)
    return info["features"] if info else frozenset()


def plan_has_feature(plan_key: str, feature: str) -> bool:
    """آیا این پلن قابلیتِ خواسته‌شده را دارد؟"""
    return feature in tier_features(tier_of(plan_key))


def tier_label(tier: str) -> str:
    info = TIERS.get(tier)
    return info["label"] if info else tier


def plans_for_tier(tier: str) -> list[str]:
    """کلیدِ پلن‌های یک سطح، به ترتیب نمایش."""
    return [k for k in PLAN_ORDER if PLANS[k]["tier"] == tier]
