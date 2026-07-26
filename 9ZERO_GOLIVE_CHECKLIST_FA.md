# چک‌لیست Go-Live نهایی 9zero

**تاریخ:** ۲۰۲۶/۰۷/۲۶ · **مبنا:** بررسی مستقیم ریپوی `ariasadeghian/9-zero` (برنچ پیش‌فرض `claude/loving-mayer-N7VcY`)
**کل زمان لازم:** ~۴ ساعت کار مفید در ۲–۳ روز · **کل هزینه:** ~۵$ اعتبار Anthropic + ~۵$/ماه Railway (بقیه رایگان)

> **یافته مهم قبل از شروع:** برنچ پیش‌فرض ریپو همین `claude/loving-mayer-N7VcY` است و هر ۴ ورک‌فلو (deploy-pages، reza-daily و…) روی آن موجودند. پس مرحله «merge به main» در `DEPLOY_REZA_FA.md` **منتفی است** — زمان‌بندی خودکار از همین برنچ اجرا می‌شود. فقط secrets مانده.

---

## فاز ۰ — بلاک‌کننده‌های محتوایی و امنیتی (~۳۰ دقیقه) 🔴

| # | کار | مرجع | معیار انجام |
|---|---|---|---|
| ۱ | جواب **Q1** (۶ کارت نقل‌قول لندینگ — واقعی/composite/ساختگی؟) و **Q2** (متریک‌های Before/After اسلاید ۰۷ دک) — دو مورد قرمزِ بلاک‌کننده انتشار | `QUESTIONS_FOR_FOUNDER.md` | گزینه A/B/C هر سوال علامت خورده؛ لندینگ و دک بدون ادعای تأییدنشده |
| ۲ | جواب Q3–Q5 (زرد: تعداد مصاحبه‌ها، اعداد CLAUDE.md، فریم pilot/cohort) — ترجیحاً همین جلسه | همان فایل | علامت خورده |
| ۳ | **Revoke توکن قدیمی بات دمو** (در هیستوری چت/ریپو لو رفته): `@BotFather` → `/revoke` → `testninezerobot` → توکن تازه فقط برای Railway نگه دار | `DEPLOY.md` §۲ | توکن قدیمی باطل، جدید جای امن |

## فاز ۱ — مسیر پول: تمپلیت ۷۹ دلاری (~۲ ساعت) 💰

| # | کار | مرجع | معیار انجام |
|---|---|---|---|
| ۴ | **ساخت تمپلیت عمومی در Notion** (~۴۵ دقیقه): صفحه top-level جدید «9zero OS — Template» → Duplicate پنج سطح از workspace دمو (یا `provision_customer.py`) → پاک‌سازی داده دمو (فقط یک ردیف `[EXAMPLE — delete me]` در هر DB) → چک فرمول‌ها (KPI Trend/Status، Experiment Score) → صفحه خانه طبق ساختار سند → **شمارنده خودکار روز چرخه** (دیتابیس Cycle با فرمول Day/Phase — تمایز اصلی، حتماً بساز) → Share → Publish + اجازه duplicate | `co_founder/launch/TEMPLATE_BUILD_CHECKLIST.md` | تست در مرورگر incognito: لینک باز می‌شود، Duplicate کار می‌کند، فرمول‌ها محاسبه می‌شوند |
| ۵ | **ضبط ویدیوی ۶۰ ثانیه‌ای** (Loom، اسکریپت زمان‌بندی‌شده آماده است) | `co_founder/launch/DEMO_VIDEO_SCRIPT.md` | لینک ویدیو آماده |
| ۶ | **Gumroad**: اکانت → محصول جدید $79 → متن/FAQ/تگ‌ها را از سند بچسبان → ویدیو + اسکرین‌شات‌ها → تحویلی = لینک تمپلیت → Publish (کارمزد ~۱۰٪) | `co_founder/launch/GUMROAD_LISTING.md` | صفحه فروش زنده و قابل خرید |

> اگر کانکتور **Notion** را در تنظیمات claude.ai برای این سشن authorize کنی، ساخت و تمیزکاری تمپلیت (بند ۴) را می‌توانم خودم انجام بدهم — الان متصل نیست.

## فاز ۲ — دیده‌شدن و رزرو (~۳۰ دقیقه) 🌐

| # | کار | مرجع | معیار انجام |
|---|---|---|---|
| ۷ | **GitHub Pages**: Settings → Pages → Source: `GitHub Actions` → تب Actions → ورک‌فلو «Deploy landing & demo» → Run روی برنچ پیش‌فرض | `DEPLOY.md` §۱ | `ariasadeghian.github.io/9-zero/` و `/demo` بالا هستند |
| ۸ | (اختیاری ولی توصیه‌شده) **دامنه 9zero.pro** روی Pages: Settings → Pages → Custom domain + CNAME در DNS نیم‌دات‌کام به `ariasadeghian.github.io` | `DEPLOY.md` §۱ | سایت روی دامنه اصلی با HTTPS |
| ۹ | **لینک Cal.com** ۱۵ دقیقه‌ای بساز (آنبلاک‌کننده تماس‌ها) | STATE §۵ | لینک قابل رزرو |
| ۱۰ | **DKIM زوهو** در DNS نیم‌دات‌کام (قبل از شروع outbound — deliverability): mail.zoho.eu → Settings → رکورد DKIM → TXT در name.com | STATE §۱۱ | زوهو DKIM را verified نشان می‌دهد |

## فاز ۳ — لانچ و outbound (روز ۱ تا ۳) 📣

| # | کار | مرجع | معیار انجام |
|---|---|---|---|
| ۱۱ | **آپلود دارایی‌های LinkedIn** (بنر + ۲ متن پروفایل + ۳۴ گرافیک پست، همه آماده) | `design/handoff-linkedin/` | پروفایل به‌روز |
| ۱۲ | **پست لانچ #1** (EN/FA) در X و LinkedIn با لینک Gumroad + دمو | `co_founder/launch/LAUNCH_POSTS.md` | دو پست منتشر |
| ۱۳ | **۱۵ ایمیل سرد آماده را بفرست** از `aria@9zero.pro` (کپی/پیست، Subject مشترک) و Stage را `C1 Sent` بزن | `co_founder/deliverables/2026-07-05_SEND_TODAY.md` | ۱۵ ارسال ثبت‌شده |
| ۱۴ | **۵ پیام گرم** به شبکه نزدیک | `co_founder/deliverables/2026-07-05_warm_outreach_kit.md` | ۵ ارسال |
| ۱۵ | **پست ارزش در کامیونیتی‌ها** (Indie Hackers، r/startups، گروه‌های تلگرام فاندرها) | استراتژی، کانال ۳ | ۱ پست |

## فاز ۴ — اتوماسیون (~۲۰ دقیقه) 🤖

| # | کار | مرجع | معیار انجام |
|---|---|---|---|
| ۱۶ | **Secrets رضا** در `github.com/ariasadeghian/9-zero/settings/secrets/actions`: `ANTHROPIC_API_KEY` (از console.anthropic.com + حداقل ۵$ شارژ) · `ZOHO_USER` = aria@9zero.pro · `ZOHO_PASS` = App Password زوهو · `FOUNDER_EMAIL` = aryasadeghian47@gmail.com — **merge لازم نیست** (برنچ پیش‌فرض همین است) | `DEPLOY_REZA_FA.md` | — |
| ۱۷ | **تست رضا**: Actions → «Reza — daily sales run» → Run workflow → سبز → ایمیل digest رسید. از فردا روزی ۱۰ draft خودکار | همان | run سبز + ایمیل |
| ۱۸ | **دیپلوی Demo Bot روی Railway** (~۵ دقیقه): New Project → repo `9-zero` → Root Directory `bot/demo` → Branch `claude/loving-mayer-N7VcY` → متغیرها: `DEMO_TELEGRAM_BOT_TOKEN` (توکن تازه بند ۳)، `DEFAULT_LANG=en`، `TZ=Europe/London` | `DEPLOY.md` §۲ | `t.me/testninezerobot` به `/start` با ۶ دکمه جواب می‌دهد؛ `/tour` کار می‌کند |
| ۱۹ | (اختیاری) Founder Bot روی Railway | `DEPLOY.md` §۳ | — |
| ۲۰ | **بهداشت ریپو**: دو برنچ دیگر (`claude/sellability-fixes`، `claude/automated-outreach-tool-u11c0q`) را چک کن — اگر کار merge‌نشده دارند به برنچ پیش‌فرض بیاور تا Pages/رضا/Railway از آخرین نسخه build کنند | GitHub → branches/PRs | برنچ پیش‌فرض جلوتر یا برابر همه |

## فاز ۵ — آماده تحویل، برای لحظه اولین پول 🎁

| # | کار | مرجع |
|---|---|---|
| ۲۱ | `ops-manual.html` → همین حالا PDF کن (قولش در هر ایمیل سرد داده شده — با اولین «بله» فوراً لازم می‌شود) | `web/assets/` |
| ۲۲ | لینک‌های Stripe را در `pricing.html` جای `{{STRIPE_LINK_*}}` بگذار (پله‌های $950/$2,500؛ پله $79 با Gumroad پوشش داده شده) | `web/assets/pricing.html` |
| ۲۳ | با اولین فروش $950: ایمیل خوش‌آمد → اجندای کیک‌آف → چک‌لیست هفته صفر → `provision_customer.py --customer "..."` (نیاز به `NOTION_API_KEY`) | `co_founder/delivery/onboarding/` |
| ۲۴ | ایمیل upsell روز ۷ برای خریداران تمپلیت ($79 → $950) — متن آماده است | `co_founder/launch/LAUNCH_POSTS.md` |

---

## ✅ تعریف «زنده» — هر ۵ تیک یعنی go-live کامل

1. لینک Gumroad قابل خرید است ($79)
2. لندینگ + `/demo` روی Pages بالا هستند
3. بات دمو به `/start` جواب می‌دهد
4. رضا run سبز دارد و digest روزانه می‌رسد
5. ۲۰ تماس outbound رفته (۱۵ سرد + ۵ گرم)

**KPI هفته اول:** اولین فروش تمپلیت + اولین reply + ۱–۳ تماس رزروشده. **هدف ۳۰ روزه (سند استراتژی):** ۱۰ فروش تمپلیت + ۱ نصب $950 یا ۱ اسپرینت $2,500 = **$1,600–3,200**.

**قانون طلایی که در همه اسناد تکرار شده:** رضا فقط draft می‌سازد — دکمه Send همیشه دست خودت است؛ و هیچ عدد/نقل‌قول تأییدنشده‌ای منتشر نمی‌شود (به همین دلیل فاز ۰ اول است).
