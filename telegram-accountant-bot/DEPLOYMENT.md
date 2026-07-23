# راهنمای استقرار حسابیار (Technical Handoff)

سندِ فنی برای راه‌اندازی بات روی سرور. مخاطب: CTO / DevOps.

---

## ۱) در یک نگاه

- **زبان/استک:** Python 3.11، `python-telegram-bot` v21 (async)، SQLAlchemy 2،
  SQLite (پیش‌فرض) یا PostgreSQL.
- **ورودی/خروجی:** فقط **long polling** به `api.telegram.org` — نیازی به
  دامنه، پورت باز یا وب‌هوک نیست.
- **نقطه‌ی اجرا:** `python -m hesabyar`
- **بدون state خارجی اجباری:** یک فرایند + یک فایل دیتابیس کافی است.

> ⚠️ **مهم:** فرایند بات باید بتواند به `api.telegram.org` وصل شود. توصیه:
> سرور **خارج از ایران** (هم تلگرام هم سرویس‌های AI در دسترس‌اند). پرداخت
> کارت‌به‌کارت/زرین‌پال به موقعیت سرور وابسته نیست.

---

## ۲) پیش‌نیازها (چیزهایی که باید فراهم شود)

| مورد | الزامی؟ | توضیح |
|---|---|---|
| توکن بات | ✅ | از [@BotFather](https://t.me/BotFather) |
| سرور (VPS) | ✅ | ۱ vCPU / ۱GB RAM کافی است؛ ترجیحاً خارج از ایران |
| شماره‌کارت یا مرچنت زرین‌پال | برای فروش | یکی از دو روش پرداخت اشتراک |
| Endpoint سرویس تصویری/LLM | اختیاری | برای خواندن عکس فاکتور و استخراج هوشمند (سازگار با API نوع OpenAI، روی سرور خارجی) |
| شناسه عددی تلگرامِ ادمین‌ها | برای تأیید پرداخت | با `/start` روی بات [@userinfobot] پیدا می‌شود |

---

## ۳) شروع سریع (۵ دقیقه، با Docker)

```bash
git clone <REPO_URL> makair
cd makair
git checkout claude/telegram-accountant-bot-5xz3io
cd telegram-accountant-bot

cp .env.example .env
# فقط BOT_TOKEN را داخل .env بگذارید تا اولین اجرا انجام شود
nano .env

docker compose up -d --build
docker compose logs -f            # باید ببینید: «حسابیار در حال اجراست…»
```

همین. حالا در تلگرام به بات `/start` بدهید.

---

## ۴) اجرا بدون Docker (venv + systemd)

```bash
cd telegram-accountant-bot
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && nano .env
python -m hesabyar                 # اجرای دستی برای تست
```

سرویس دائمی با systemd (فایل آماده در `deploy/hesabyar.service`):

```bash
sudo cp deploy/hesabyar.service /etc/systemd/system/
# مسیرها و User را در فایل مطابق سرور خود ویرایش کنید
sudo systemctl daemon-reload
sudo systemctl enable --now hesabyar
sudo systemctl status hesabyar
journalctl -u hesabyar -f
```

---

## ۵) متغیرهای محیطی (.env)

| متغیر | پیش‌فرض | توضیح |
|---|---|---|
| `BOT_TOKEN` | — | **الزامی.** توکن بات تلگرام |
| `DATABASE_URL` | `sqlite:///hesabyar.db` | SQLite یا `postgresql+psycopg://user:pass@host/db` |
| `DEFAULT_CURRENCY` | `تومان` | واحد پول |
| `REMINDER_HOUR` / `REMINDER_MINUTE` | `9` / `0` | ساعت یادآوری روزانه‌ی سررسیدها (به وقت ایران) |
| `ADMIN_IDS` | — | شناسه‌های عددی ادمین‌ها، با کاما. تأییدکننده‌ی پرداخت‌ها |
| `PAYMENT_METHOD` | `card` | `card` (کارت‌به‌کارت) یا `zarinpal` (درگاه) |
| `CARD_NUMBER` / `CARD_HOLDER` | — | برای روش کارت‌به‌کارت |
| `ZARINPAL_MERCHANT_ID` | — | برای روش زرین‌پال |
| `ZARINPAL_SANDBOX` | `false` | حالت تست درگاه |
| `PAYMENT_CALLBACK_URL` | `https://t.me` | لازم نیست وب‌سرور بالا بیاورید؛ تأیید پرداخت با دکمه‌ی «بررسی پرداخت» انجام می‌شود |
| `TRIAL_DAYS` | `14` | طول دوره‌ی آزمایشی رایگان |
| `OCR_BASE_URL` / `OCR_API_KEY` / `OCR_MODEL` | — | سرویس تصویری برای خواندن عکس فاکتور (اختیاری) |
| `USE_LLM_PARSER` | `false` | استخراج هوشمند (نوع/دسته/فروشنده/تاریخ) با LLM |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | = مقادیر OCR | اگر خالی بماند از همان endpoint OCR استفاده می‌شود |
| `MOADIAN_BASE_URL` / `MOADIAN_TOKEN` | — | سامانه‌ی مودیان (فعلاً **اسکلت/dry-run**؛ ارسال گواهی‌شده پیاده نشده) |
| `SELLER_TIN` / `ECONOMIC_CODE` / `VAT_RATE` | — / — / `0.10` | اطلاعات مالیاتیِ فروشنده برای payload مودیان |
| `BACKUP_DIR` | کنار دیتابیس | مقصد پشتیبانِ دیتابیس |
| `BACKUP_WEEKLY` | `true` | پشتیبان‌گیری هفتگی خودکار + اطلاع به ادمین‌ها |

> بدون `OCR_*`، خواندن عکس غیرفعال است ولی همه‌چیز دیگر کار می‌کند. بدون
> `USE_LLM_PARSER`، دسته‌بندی قاعده‌محور (کلیدواژه‌ای) کار می‌کند.

---

## ۶) دیتابیس

- پیش‌فرض **SQLite** (فایل `hesabyar.db`). برای تک‌سرور و حجم متوسط کافی است؛
  جدول‌ها خودکار در اولین اجرا ساخته می‌شوند (`init_db`).
- **پرحجم/چند نمونه؟** به PostgreSQL مهاجرت کنید: فقط `DATABASE_URL` را عوض
  کنید (مثلاً `postgresql+psycopg://...`) و `psycopg[binary]` را نصب کنید.
  کد ORM است و وابسته به SQLite نیست.
- **پشتیبان:** فایل SQLite را نگه دارید (در Docker روی volume `./data`) و/یا
  پشتیبان هفتگیِ داخلی (`BACKUP_WEEKLY`) را روشن بگذارید.

---

## ۷) سرویس‌های خارجی

- **خواندن فاکتور (OCR) و استخراج هوشمند (LLM):** یک endpoint سازگار با
  chat/completions نوع OpenAI (متن و تصویر). چون از داخل ایران محدود است،
  روی سرور خارج از ایران میزبانی یا پراکسی کنید و در `OCR_*`/`LLM_*` بگذارید.
- **پرداخت:** کارت‌به‌کارت (تأیید دستیِ ادمین با دکمه) یا زرین‌پال (کاربر
  لینک می‌گیرد، «بررسی پرداخت» را می‌زند، اشتراک خودکار فعال می‌شود). هیچ‌کدام
  به وب‌هوک یا وب‌سرور نیاز ندارند.
- **مودیان:** فعلاً اسکلت است و در نبود گواهی، حالت آزمایشی (dry-run) اجرا
  می‌شود. ارسال واقعی نیازمند کلید/گواهی رسمی و امضای دیجیتال است.

---

## ۸) کارهای زمان‌بندی‌شده (داخل خود فرایند)

با `JobQueue`ی `python-telegram-bot` اجرا می‌شوند؛ نیازی به cron جدا نیست:

- **`due_reminders`** — روزانه؛ یادآوری سررسید طلب/بدهی به کاربران.
- **`weekly_backup`** — هفتگی؛ پشتیبانِ دیتابیس + پیام به ادمین‌ها.

---

## ۹) امنیت و ملاحظات عملیاتی

- **اسرار** فقط از `.env` خوانده می‌شوند؛ در لاگ یا کد نیستند. `.env` را
  commit نکنید (در `.gitignore` هست).
- **SSRF:** خواندنِ فاکتور از «لینک» محافظت دارد — میزبان باید به IP عمومی
  برسد، ریدایرکت دنبال نمی‌شود، و سقف اندازه/زمان دارد.
- **منابع:** رندر داشبورد (matplotlib) و PDF فاکتور CPU-bound و کوتاه‌اند؛
  فایل‌های موقت پس از ارسال حذف می‌شوند.
- **تک‌فرایند:** با long polling فقط **یک** نمونه‌ی بات باید هم‌زمان اجرا شود
  (دو نمونه با یک توکن → تداخل getUpdates).

---

## ۱۰) سلامت و تست

```bash
pip install -r requirements.txt
python -m pytest -q            # باید سبز باشد (منطق خالص + سرویس‌ها + یکپارچگی)
python -c "import hesabyar.bot.app"   # اسموک import
```

اجرای موفق در لاگ: `حسابیار در حال اجراست…` و ثبت دو job زمان‌بندی‌شده.

---

## ۱۱) مقیاس و محدودیت‌ها

- مناسب تک‌سرور و رشدِ اولیه. برای مقیاس بالاتر: PostgreSQL + جداسازی
  worker یادآوری/بکاپ + احتمالاً مهاجرت از polling به webhook (نیازمند دامنه
  و TLS) — همگی افزایشی و بدون بازنویسی.
- SQLite در نوشتن هم‌زمانِ سنگین قفل می‌گیرد؛ برای بار بالا Postgres.

---

## ۱۲) عیب‌یابی رایج

| نشانه | علت/راه‌حل |
|---|---|
| بات جواب نمی‌دهد | دسترسی سرور به `api.telegram.org` را چک کنید؛ `BOT_TOKEN` درست باشد |
| `Conflict: terminated by other getUpdates` | دو نمونه‌ی هم‌زمان اجراست؛ فقط یکی را نگه دارید |
| خواندن عکس کار نمی‌کند | `OCR_*` تنظیم نشده یا endpoint از سرور در دسترس نیست |
| خطای build چرخ‌ها (wheel) | از image کامل `python:3.11` به‌جای `slim` استفاده کنید یا `build-essential`/`libffi`/`libfreetype6` را نصب کنید |
| دیتابیس بعد از restart خالی شد | در Docker مطمئن شوید `./data` روی volume mount است و `DATABASE_URL` به همان مسیر اشاره می‌کند |
