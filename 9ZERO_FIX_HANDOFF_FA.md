# دستور کار اصلاح 9zero — برای چت مخصوص پروژه

**تاریخ راستی‌آزمایی:** ۲۰۲۶/۰۷/۲۶ · **مبنا:** کلون کامل ریپو (HEAD = `72b145f` روی برنچ پیش‌فرض `claude/loving-mayer-N7VcY`) + وضعیت GitHub Actions

> زمینه برای تو (چت پروژه): یک بررسی go-live مستقل انجام شده. اتوماسیون رضا سبز است (اجراهای زمان‌بندی‌شده موفق، secrets ست شده)، merge دو برنچ معلق با `git cherry` تأیید شد، و PDFهای فروش ساخته شده‌اند. موارد زیر مشکلات باز هستند — به ترتیب اولویت. هر مورد شواهد و اقدام دارد.

---

## P1 🔴 — دیپلوی GitHub Pages از ۸ جولای تا امروز fail می‌شود (خرابی فعال)

- **شواهد:** هر ۵ اجرای ورک‌فلوی «Deploy landing & demo to GitHub Pages» شکست خورده. آخرین: run `30200312798` (۲۶ جولای، ۱۱:۳۲). مرحله «Assemble site» سبز است؛ شکست در `actions/configure-pages@v5`:
  ```
  Get Pages site failed. Error: Not Found
  Create Pages site failed. Error: Resource not accessible by integration
  ```
- **ریشه:** Pages در Settings ریپو فعال نشده و توکن ورک‌فلو اجازه ساخت سایت Pages را ندارد (با وجود `enablement: true`).
- **اقدام فاندر (۲ کلیک):** Settings → Pages → Source: `GitHub Actions` → سپس Re-run آخرین run.
- **اقدام تو:** بعد از فعال‌شدن، سبز شدن run و بالا آمدن لندینگ + `/demo` را تأیید کن. تا وقتی P2 حل نشده انتشار را جلو نینداز (ترتیب مهم است).

## P2 🔴 — لندینگ با ادعاهای تأییدنشده لایو می‌شود (بلاک‌کننده محتوایی انتشار)

- **شواهد:** `QUESTIONS_FOR_FOUNDER.md` — هر ۱۵ چک‌باکس خالی است؛ هیچ سوالی جواب داده نشده. Q1 (شش کارت نقل‌قول لندینگ با attribution از نوع «SAAS · 11 PPL · $420K ARR» — `web/landing/index.html` خطوط ~۱۴۶–۱۷۲ و `design/03 Website Landing.html` خطوط ~۶۹–۹۵) و Q2 (متریک‌های Before/After اسلاید ۰۷ دک فروش) هر دو قرمزند. قانون خود ریپو: هیچ ادعای تأییدنشده‌ای منتشر نمی‌شود.
- **اقدام تو:** از فاندر جواب Q1–Q5 را بگیر (گزینه A/B/C هر سوال). تا وقتی جواب نیامده، **گزینه امن Q1-B را پیش‌فرض اعمال کن** (حذف attribution badge ها، تغییر تیتر بخش به «Patterns we keep hearing») تا P1 بدون ریسک قابل فعال‌سازی باشد؛ اگر فاندر بعداً گفت A، برگردان. برای Q2 تا تعیین‌تکلیف، اسلاید را با برچسب ILLUSTRATIVE ایمن کن.

## P3 🟠 — مستندات دیپلوی با واقعیت نمی‌خواند (فاندر غیرفنی را گمراه می‌کند)

- **شواهد:**
  - `DEPLOY_REZA_FA.md` مرحله ۳ می‌گوید «برنچ را به main مرج کن چون زمان‌بندی فقط روی برنچ اصلی کار می‌کند» — منسوخ است: برنچ پیش‌فرض ریپو خودِ `claude/loving-mayer-N7VcY` است و اجراهای schedule از همان انجام می‌شوند (و موفق‌اند).
  - سیستم رضا عوض شده: ورک‌فلوی زنده الان `reza-agent.yml` («Reza — autonomous agent»، دو کادنس، ۷ روز هفته) است؛ `reza-daily.yml` به «draft-only batch (manual)» و `reza-autopilot.yml` به «deterministic engine (manual fallback)» تبدیل شده‌اند. راهنمای فارسی هنوز روال قدیمی reza-daily را توضیح می‌دهد.
- **اقدام تو:** `DEPLOY_REZA_FA.md` را با وضعیت فعلی بازنویسی کن (کدام ورک‌فلو زنده است، چه کادنسی، فاندر روزانه دقیقاً چه می‌بیند و چه می‌کند)، و ارجاع‌های `README.md`/`DEPLOY.md` را چک کن.

## P4 🟠 — STATE.md پنج روز عقب است (قانون خود ریپو نقض شده)

- **شواهد:** آخرین تغییر `docs/STATE.md` مربوط به ۲۱ جولای است. این موارد در آن منعکس نیست: رضا autonomous زنده با secrets ست‌شده، PDFهای فروش (`web/assets/pdf/` — one-pager/ops-manual/pricing)، merge دو برنچ، LICENSE اختصاصی، کیت YC co-founder (`co_founder/recruiting/YC_COFOUNDER_PROFILE.md`).
- **اقدام تو:** جدول‌های STATE.md را به‌روز کن (Deployed/Live ها، مسیرهای جدید) طبق بخش «How to update this file» خود فایل.

## P5 🟡 — بهداشت برنچ‌ها

- **شواهد:** `claude/sellability-fixes` و `claude/automated-outreach-tool-u11c0q` کاملاً patch-equivalent داخل برنچ پیش‌فرض‌اند (تأیید با `git cherry` — هر دو کامیت یکتایشان «-» است و diff محتوایی صفر) ولی هنوز روی remote هستند؛ `main` هم ancestor برنچ پیش‌فرض و عقب است.
- **اقدام تو:** دو برنچ merged را حذف کن. برای `main` یکی از دو کار: یا fast-forward به HEAD فعلی (تا ورک‌فلوی Pages که به push روی main هم گوش می‌دهد بی‌معنا نماند)، یا در README یک خط بنویس که برنچ فعال کدام است. **برنچ پیش‌فرض را بدون هماهنگی عوض نکن** — تنظیم Branch در Railway (`bot/demo`) و مستندات به نام فعلی اشاره دارند.

## P6 🟡 — قیف پول پله ۱ هنوز وصل نیست

- **شواهد:** هیچ لینک Gumroad/Cal.com/تمپلیت Notion در هیچ فایل `web/` نیست. `web/assets/pricing.html` خط ~۴۱۷ هنوز کامنت «Replace the mailto: hrefs below with the buy.stripe.com URLs» دارد و دکمه‌ها mailto هستند. لینک `https://9zero.pro` در فوتر pricing به سایتی اشاره می‌کند که هنوز بالا نیست (وابسته به P1 + ست‌کردن Custom domain).
- **اقدام فاندر:** ساخت تمپلیت عمومی در Notion (طبق `co_founder/launch/TEMPLATE_BUILD_CHECKLIST.md`)، ضبط ویدیوی ۶۰ ثانیه‌ای، ساخت اکانت Gumroad و لیست $79 (متن آماده در `GUMROAD_LISTING.md`)، ساخت لینک Cal.com.
- **اقدام تو:** به‌محض اینکه فاندر لینک‌ها را داد، آن‌ها را در لندینگ/pricing/پست‌های لانچ جاگذاری کن و تست کن.

## P7 🟢 — چک‌های بیرون از ریپو که باید از فاندر گرفته شود (از این‌جا قابل راستی‌آزمایی نبود)

از فاندر یکی‌یکی تأیید بگیر و در STATE.md ثبت کن:
- [ ] توکن قدیمی `testninezerobot` در BotFather **revoke** شده؟ (در هیستوری لو رفته بود)
- [ ] بات دمو روی Railway بالاست و `/start` و `/tour` جواب می‌دهند؟
- [ ] DKIM زوهو در DNS نیم‌دات‌کام اضافه و verified شده؟ (قبل از موج outbound)
- [ ] Custom domain `9zero.pro` روی Pages ست شده؟ (بعد از P1)
- [ ] ۱۵ ایمیل سرد `SEND_TODAY` و ۵ پیام گرم ارسال شده‌اند؟

## P8 🟢 — جزئی / کم‌اولویت

- هشدار Node 20 deprecation روی `actions/checkout@v4` و `actions/configure-pages@v5` در ران‌ها — فعلاً فقط warning است؛ در فرصت بعدی نسخه اکشن‌ها را به‌روز کن.
- در `web/assets/pricing.html` فونت‌ها از CDN گوگل لود می‌شوند — برای نسخه چاپی/آفلاین مهم نیست، فقط بدان.

---

## ترتیب پیشنهادی اجرا

۱) P2 (اعمال گزینه امن Q1-B + ایمن‌سازی Q2) → ۲) فاندر P1 را فعال کند → ۳) تأیید سبز شدن Pages → ۴) P3 و P4 (مستندات و STATE) → ۵) P5 → ۶) P6 با لینک‌های فاندر → ۷) P7 را از فاندر بگیر و ثبت کن.

**معیار تمام‌شدن:** run سبز Pages + لندینگ بدون ادعای تأییدنشده + STATE.md هم‌سطح واقعیت + برنچ‌های merged حذف‌شده + لینک خرید $79 زنده در سایت.
