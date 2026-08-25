# رِران‌بوکِ سرور (میزبانیِ چند محصول)

سندِ عملیاتی برای اجرای محصولات روی یک سرورِ مشترک. مخاطب: DevOps / کسی که سرور
را می‌گرداند. محصولِ نمونه در این سند: **حسابیار** (بات تلگرام حسابداری). ساختار
طوری است که محصولاتِ بعدی هم با همین الگو کنار هم بنشینند و ایزوله بمانند.

> این سند «چگونه روی سرور بیاوریم و بچرخانیم» است. جزئیاتِ مفهومیِ معماری در
> `DEPLOYMENT.md` و جدولِ کاملِ متغیرها در `.env.example` هست.

---

## ۱) پیش‌نیازهای سرور (یک‌بار)

| مورد | مقدار پیشنهادی |
|---|---|
| سیستم‌عامل | Ubuntu 22.04+ (یا هر لینوکسِ مدرن) |
| منابع (برای شروع) | ۱ vCPU / ۱–۲ GB RAM؛ هر محصولِ سبک ~۲۰۰–۵۰۰ MB |
| شبکه | فقط **outbound** لازم است (این محصول پورت ورودی ندارد) |
| موقعیت | ترجیحاً **خارج از ایران** تا Telegram و Google و سرویس‌های AI در دسترس باشند |

**نصبِ ابزارها (Ubuntu):**
```bash
# Docker Engine + Compose plugin
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"     # سپس یک‌بار logout/login
docker --version && docker compose version

# git
sudo apt-get update && sudo apt-get install -y git
```

**فایروال (اختیاری ولی توصیه‌شده):** چون محصول پورتِ ورودی ندارد، فقط SSH را باز بگذار:
```bash
sudo ufw allow OpenSSH && sudo ufw enable
```

---

## ۲) قراردادِ چیدمانِ چند محصول

- هر محصول در `/opt/<product>/` کلون می‌شود.
- هر محصول **`.env` مخصوصِ خودش** را دارد (با `chmod 600`).
- هر پوشه یک **compose project جدا** است (Docker با نامِ پوشه ایزوله می‌کند)؛ نامِ
  کانتینرها یکتا باشد.
- حسابیار **پورتِ ورودی ندارد** (worker)، پس تداخلِ پورت نمی‌سازد. برای محصولی که
  پورت می‌خواهد: یک پورتِ هاستِ **یکتا** بده و در آینده یک **nginx** جلوی همه‌شان
  به‌عنوان reverse proxy بگذار.

**جدولِ تخصیص (به‌روز نگه‌دار):**

| محصول | مسیر | پورت هاست | نوع |
|---|---|---|---|
| حسابیار | `/opt/hesabyar` | — | worker (long polling) |
| _(بعدی)_ | | | |

---

## ۳) متعلقات و دیپندنسی‌های «حسابیار» (Dependency Manifest)

### سیستمی
- **با Docker (توصیه‌شده):** هیچ دیپندنسیِ سیستمیِ دستی لازم نیست؛ همه‌چیز داخل
  ایمیج است (`python:3.11-slim`).
- **بدون Docker:** Python 3.11+ و `python3.11-venv`. کتابخانه‌های رندر
  (Pillow/matplotlib/reportlab/pymupdf) معمولاً wheel دارند؛ اگر buildِ wheel خطا
  داد، این‌ها را نصب کن: `sudo apt-get install -y build-essential libfreetype6 libjpeg-turbo8`.
  `tzdata` از requirements می‌آید.

### پایتون (`requirements.txt`)
`python-telegram-bot[job-queue]==21.6`, `gspread`, `google-auth`,
`google-api-python-client`, `jdatetime`, `reportlab`, `arabic-reshaper`,
`python-bidi`, `httpx`, `openpyxl`, `matplotlib`, `pymupdf`, `tzdata`
(Pillow به‌عنوان دیپندنسیِ matplotlib می‌آید).

### سرویس‌های خارجی (همه outbound)
| سرویس | الزامی؟ |
|---|---|
| Telegram Bot API | ✅ |
| Google Sheets API + Drive API (سرویس‌اکانت) | ✅ |
| endpoint سازگار با OpenAI برای OCR/LLM | اختیاری |
| endpoint سازگار با Whisper برای STT (ویس→متن) | اختیاری |
| زرین‌پال | فقط اگر `PAYMENT_METHOD=zarinpal` |

### حالتِ اجرا و state
- **Worker** (long polling)، **بدون پورتِ ورودی**، حتماً **`replicas=1`**.
- **State محلی: هیچ.** کلِ داده روی Google Sheets است ⇒ سرور **stateless**؛ نیازی
  به بکاپِ دیسک نیست.
- **SIGTERM لازم است:** هنگام توقف، بات صف نوشتن را روی شیت flush می‌کند
  (`stop_grace_period: 30s` در compose و `TimeoutStopSec=30` در systemd همین را
  تضمین می‌کنند). با `kill -9` صف را از دست می‌دهی.

### متغیرهای محیطی (خلاصه؛ کامل در `.env.example`)
- **الزامی:** `BOT_TOKEN`, `GOOGLE_SERVICE_ACCOUNT_JSON_B64`, `GOOGLE_SHEET_ID`
- **مهم:** `ADMIN_IDS`, `PAYMENT_METHOD` (+ `CARD_*` یا `ZARINPAL_*`)
- **اختیاری:** `OCR_*`, `LLM_*`, `STT_*`, `REMINDER_*`, `NIGHTLY_SUMMARY*`, `BACKUP_WEEKLY`

---

## ۴) آوردنِ حسابیار روی سرور (Docker — توصیه‌شده)

```bash
sudo mkdir -p /opt/hesabyar && sudo chown "$USER" /opt/hesabyar
cd /opt/hesabyar
git clone <REPO_URL> .
git checkout claude/telegram-accountant-bot-5xz3io
cd telegram-accountant-bot

cp .env.example .env
nano .env                     # حداقل: BOT_TOKEN، GOOGLE_SERVICE_ACCOUNT_JSON_B64، GOOGLE_SHEET_ID، ADMIN_IDS
chmod 600 .env

docker compose up -d --build
docker compose logs -f        # باید ببینی: «حسابیار در حال اجراست…» و ثبتِ jobها
```
همین. در تلگرام به بات `/start` بده. (آماده‌سازیِ توکن و Google Sheet در
`docs/PILOT.md` بخش ۱ گام‌به‌گام آمده.)

---

## ۵) اجرای بدونِ Docker (venv + systemd) — جایگزین

```bash
cd /opt/hesabyar/telegram-accountant-bot
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && nano .env && chmod 600 .env

sudo cp deploy/hesabyar.service /etc/systemd/system/
# مسیرها/User را در فایل مطابق سرور ویرایش کن
sudo systemctl daemon-reload
sudo systemctl enable --now hesabyar
journalctl -u hesabyar -f
```

---

## ۶) عملیاتِ روزمره (Ops)

| کار | Docker | systemd |
|---|---|---|
| دیدن لاگ | `docker compose logs -f --tail=200` | `journalctl -u hesabyar -f` |
| ری‌استارت | `docker compose restart` | `sudo systemctl restart hesabyar` |
| توقفِ ایمن | `docker compose down` (تا ۳۰ثانیه صبر برای flush) | `sudo systemctl stop hesabyar` |
| آپدیت نسخه | `git pull && docker compose up -d --build` | `git pull && pip install -r requirements.txt && systemctl restart hesabyar` |
| وضعیت | `docker compose ps` / `docker stats hesabyar` | `systemctl status hesabyar` |

- **سنجه‌های محصول:** در تلگرام دستور `/pilot` (فقط ادمین).
- **بکاپ:** هفتگیِ خودکار به ادمین‌ها (`BACKUP_WEEKLY`) + History گوگل‌شیت. بکاپِ
  دیسکِ سرور لازم نیست (stateless).

---

## ۷) مهاجرتِ خودکارِ اسکیمای گوگل‌شیت (آپدیتِ نسخه)

از Phase 19 به بعد، هر بار Store بالا می‌آید — چه برای یک کاربرِ تازه، چه برای
یک کاربرِ قدیمی که از یک نسخه‌ی عقب‌تر (مثلاً Phase 18) آپدیت شده — اسکیمای
هر تب، **قبل از هر خواندنی**، با مدلِ فعلیِ کد هماهنگ می‌شود. برای آپدیت هیچ
اسکریپتِ مهاجرتِ دستی یا گامِ اضافه لازم نیست؛ همان `git pull` + ری‌استارتِ
معمولی (بخشِ ۶) کافی است.

### تغییراتِ اسکیمای Phase 19
| اسپردشیت | جدول | تغییر |
|---|---|---|
| اختصاصیِ کاربر | `retention_events` | **تبِ تازه** (رویدادهای نگه‌داشت: `daily_close_sent`, `daily_close_completed`, `due_reminder_sent`, `ledger_settled`) |
| اختصاصیِ کاربر | `ledger_entries` | ستونِ تازه: `snooze_until` |
| مرکزی | `users` | ستون‌های تازه: `notify_daily_close`, `notify_due_reminders`, `last_daily_close_date` |

### مکانیزم
هر بار Store بالا می‌آید (``Store.load()`` برای اسپردشیتِ مرکزی،
``Store.load_user()`` برای اسپردشیتِ اختصاصیِ هر کاربر)، تابعِ
``sheets_client.ensure_worksheets`` روی همان اسپردشیت اجرا می‌شود:

- **تبِ کلاً غایب** (مثلِ `retention_events` روی یک اسپردشیتِ Phase 18) همان‌جا
  با هدرِ مدلِ فعلی ساخته می‌شود.
- اگر هدرِ یک تبِ **موجود** پیشوندِ هدرِ فعلی باشد (فقط چند ستون در انتها کم
  دارد)، همان ستون‌های کم **اضافه** می‌شوند — بدونِ لمسِ ستون‌ها/ردیف‌های
  موجود؛ ترتیب و مقدارِ داده‌ی قدیمی دست‌نخورده می‌ماند.
- عملیات **idempotent** است: در هر ری‌استارت دوباره چک می‌شود؛ اگر چیزی کم
  نباشد کاری انجام نمی‌شود.
- اگر هدرِ یک تب نه برابرِ مدلِ فعلی است نه پیشوندش (مثلاً یک ستون دستی
  جابه‌جا/حذف/تغییرِنام شده)، بات **حدس نمی‌زند** — ``SchemaMismatchError``
  می‌دهد و دقیقاً نامِ تب + هدرِ رویِ شیت + هدرِ موردِ انتظار را لاگ می‌کند؛
  هیچ داده‌ای بازنویسی نمی‌شود.

### اثرِ عملیاتی
- **مرکزی:** اگر اسپردشیتِ رجیستری دچارِ این ناسازگاری باشد، راه‌اندازیِ بات
  همان مسیرِ retry-then-exit موجود در بخشِ ۸ (سلامت و پایش) را طی می‌کند —
  چند تلاش، سپس خروج و restart-loop تا وقتی دستی درستش کنی؛ دنبالِ
  ``SchemaMismatchError`` در لاگ بگرد.
- **اختصاصیِ یک کاربر:** فقط همان کاربر تحتِ‌تأثیر است. خطا توسطِ
  error-handlerِ سراسریِ بات گرفته می‌شود؛ آن کاربر یک پیامِ خطای عمومی
  می‌بیند و لاگِ کامل (با نامِ تب/هدرها) ثبت می‌شود، ولی بقیه‌ی کاربران و
  jobهای زمان‌بندی‌شده (یادآوری/خلاصه‌ی شب/`/pilot`) که هر کاربر را جدا
  بارگذاری می‌کنند بی‌تأثیرند.
- **کاربرانِ قدیمی** به‌صورتِ پیش‌فرض ``notify_daily_close=True`` و
  ``notify_due_reminders=True`` می‌گیرند — یعنی رفتارِ قبل از Phase 19
  (یادآورها/خلاصه‌ی شب روشن) برایشان حفظ می‌شود.

---

## ۸) سلامت و پایش

- سالم = در `docker compose ps` وضعیت **Up** باشد و لاگ **restart-loop** نداشته باشد.
- **هشدارِ خودکار:** اگر نوشتن روی شیت چند بار پیاپی شکست بخورد، بات خودش به
  `ADMIN_IDS` پیام می‌دهد.
- اگر اتصال اولیه به گوگل‌شیت برقرار نشود، بات با backoff تلاش و سپس خارج می‌شود تا
  Docker/systemd دوباره بالا بیاورد (نه فرایندِ نیمه‌کاره).

---

## ۹) عیب‌یابیِ سریع

| نشانه | راه‌حل |
|---|---|
| بات جواب نمی‌دهد | دسترسی سرور به `api.telegram.org` و درستیِ `BOT_TOKEN` را چک کن |
| `Conflict: terminated by other getUpdates` | دو نمونه هم‌زمان اجراست؛ فقط یکی را نگه دار (`replicas=1`) |
| بالا نیامدن با خطای گوگل‌شیت | `GOOGLE_SHEET_ID` و کلید را چک کن؛ اسپردشیت باید با ایمیل سرویس‌اکانت **Editor** شده و Sheets+Drive API فعال باشند |
| خطای buildِ wheel | از ایمیج کامل `python:3.11` به‌جای slim استفاده کن یا `build-essential`/`libfreetype6` را نصب کن |
| مصرفِ حافظه بالا | `mem_limit` در compose هست؛ اگر restart خورد، کمی بالاترش ببر |
| لاگِ `SchemaMismatchError` | هدرِ یک تب دستی روی گوگل‌شیت تغییر کرده (نه برابرِ مدلِ فعلی، نه پیشوندش). خودکار درست نمی‌شود؛ تب/هدرِ گزارش‌شده در لاگ را با مدلِ فعلیِ کد مقایسه و دستی اصلاح کن — بخشِ ۷ را ببین |

---

## ۱۰) افزودنِ محصولِ بعدی به همین سرور (چک‌لیستِ تکرارشونده)

- [ ] `/opt/<product>/` بساز و مخزن را clone کن.
- [ ] `.env` مخصوصِ محصول (`chmod 600`).
- [ ] اگر پورت می‌خواهد: یک پورتِ **یکتا** بده و در جدولِ بخش ۲ ثبت کن؛ برای دامنه،
      یک nginx به‌عنوان reverse proxy جلوی محصولاتِ پورت‌دار بگذار.
- [ ] در `docker-compose.yml` محصول: `restart: unless-stopped`، `logging` (چرخش)،
      و `mem_limit` بگذار (مثل حسابیار) تا روی سرورِ مشترک مؤدب باشد.
- [ ] `docker compose up -d --build` و بررسیِ لاگ.
- [ ] در جدولِ تخصیصِ بخش ۲ ثبتش کن.
