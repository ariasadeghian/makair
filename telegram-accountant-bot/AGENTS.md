# AGENTS.md — orientation for an AI coding agent

You are working on **حسابیار (Hesabyar)**, a Persian-language Telegram
accounting bot for very small Iranian businesses. This file is the fastest
accurate path into the codebase. Read it before changing anything.

Written in English on purpose: the codebase itself is Persian (identifiers are
English, but every docstring, comment and user-facing string is Persian), and
the rules about *writing* Persian are clearest stated in English. Follow the
conventions here; do not convert the project to English.

---

## 0. Where you actually are

```
/home/user/makair/                 ← MakAir: an open-source COVID ventilator.
├── src/ res/ docs/ README.md         COMPLETELY UNRELATED. Ignore it.
└── telegram-accountant-bot/       ← YOU ARE HERE. This is Hesabyar.
```

The parent repository is an unrelated hardware project. Hesabyar exists only
inside `telegram-accountant-bot/`, and only on the branch
`claude/telegram-accountant-bot-5xz3io`. If `telegram-accountant-bot/` is
missing from disk, you are on the wrong branch — check `git branch` before
concluding anything is broken.

All paths below are relative to `telegram-accountant-bot/`.

---

## 1. What the product is

A shopkeeper writes — or speaks — a sentence in Telegram, and the bot books it:

> «۱٫۲ میلیون فروختم» → 🟢 فروش کالا — ۱٬۲۰۰٬۰۰۰ تومان ثبت شد

Three jobs, in the product's own words: **ثبت دخل و خرج** (income/expense),
**مدیریت طلب و بدهی** (receivables/payables + due reminders + cheques), and
**ساخت فاکتور** (invoices as image + PDF).

The competitor is a paper notebook, not accounting software. That framing
governs every design decision — see `docs/PRODUCT_SCOPE.md`, which also lists
five "out of band" triggers where a customer stops being the target user.
**Read that file before proposing any feature.**

---

## 2. Run and test

```bash
cd telegram-accountant-bot
pip install -r requirements.txt

python -m pytest                 # 1136 tests, ~11s, all green
python -m pytest tests/test_ledger.py -v
python -m hesabyar               # runs the bot (needs a real .env)
```

Config lives in `pytest.ini`: `pythonpath=.`, `testpaths=tests`,
`asyncio_mode=auto` (so `async def test_*` needs no decorator).

Tests never touch the network. Google Sheets is faked by `tests/fakes.py`;
HTTP is faked with `httpx.MockTransport`. **Keep it that way** — if you add a
test that needs network or a real model download, you did it wrong.

Python 3.11, `python-telegram-bot[job-queue]==21.6` (async), `gspread`.
If `cryptography` fails to import with a pyo3 panic, `pip install
--force-reinstall cffi` — that is an environment defect, not a code bug.

---

## 3. Architecture

```
hesabyar/
├── config.py        Settings dataclass, everything from env vars
├── plans.py         Subscription tiers and feature flags
├── core/            PURE logic. No I/O, no async, no Telegram.
│   ├── nlp.py            "۵۰۰ هزار خرید" → ParsedTransaction
│   ├── ledger_nlp.py     "از علی ۳ میلیون طلب دارم" → ParsedLedgerIntent
│   ├── invoice_nlp.py    "فاکتور برای علی، ۲ صندلی ۵۰۰ هزار" → items
│   ├── jalali.py         Persian calendar + period bounds
│   ├── money.py          Persian digits, amount parsing/formatting
│   ├── seller.py         Invoice letterhead field definitions
│   └── industries.py     Per-trade categories, examples, tips
├── db/
│   ├── models.py         Dataclasses with TABLE / COLUMNS / to_row / from_row
│   ├── store.py          In-memory store over Google Sheets
│   └── sheets_client.py  gspread wrapper, retries, schema migration
├── services/        Business logic. Async, takes `store`, returns data.
├── bot/
│   ├── handlers.py       3472 lines. Every Telegram handler. The monolith.
│   ├── keyboards.py      Every InlineKeyboardMarkup builder
│   ├── texts.py          Every user-facing Persian string
│   ├── reminders.py      Scheduled jobs (daily close, due reminders)
│   └── app.py            Application wiring, startup/shutdown
└── pdf/                  Invoice rendering + bundled Vazirmatn fonts
```

The dependency direction is strict: `bot → services → db → core`. `core` never
imports anything above it. Put pure logic in `core` and test it directly —
that is where the cheap, fast tests live.

---

## 4. The data layer — read this before touching persistence

There is **no database**. Data lives in Google Sheets, held in memory:

- One **central** spreadsheet (the registry): `users`, `subscriptions`,
  `payments`, `rates`, `branches`, `branch_members`, `sequences`.
- One **dedicated spreadsheet per business**: `transactions`,
  `ledger_entries`, `invoices`, `invoice_items`, `products`, `group_events`,
  `customers`, `retention_events`.

Reads are from memory. Writes apply in memory, mark the table dirty, and a
background task flushes every 5s. `Store.flush()` rewrites each dirty table
**in full** (clear + rewrite) using the current code's `COLUMNS`.

Per-user data loads lazily on first access (`Store.load_user`), cached in
`_loaded_users`. IDs come from a central `sequences` counter so two users'
rows never collide in the shared in-memory dict.

**Schema migration is automatic and load-time.** `sheets_client.ensure_worksheets`
runs before any read: it creates missing worksheets and, when an existing
header is a strict *prefix* of the current `COLUMNS`, appends only the new
trailing columns — never reordering or deleting. Anything else raises
`SchemaMismatchError` naming the worksheet and both headers rather than
corrupting data. It is idempotent. So:

- **Adding a field** = add it to the dataclass, to `COLUMNS` (at the **end**),
  to `to_row()`, and read it in `from_row()` with a `.get()` default. Nothing
  else. Existing sheets self-upgrade on next load.
- **Never reorder or remove a column.** That turns a safe prefix into a
  mismatch and hard-fails for every existing user.
- `from_row` must always tolerate a missing key — old rows lack new columns.
  For a boolean that must default to `True` for legacy rows, use
  `_pbool_default_true`, not `_pbool`.

---

## 5. The bot layer

**Multi-step flows do not use PTB's `ConversationHandler`.** They use a
hand-rolled state machine in `context.user_data["flow"]`, a string like
`"invoice_items"` or `"ledger_amount"`. Related scratch keys are listed in
`handlers._FLOW_KEYS` and wiped together by `_clear_flow()`.

Two established patterns worth matching rather than reinventing:

- **Ask-then-confirm for anything destructive or financial.** Two callbacks:
  `thing:ask:{id}` renders a confirmation keyboard, `thing:yes:{id}` performs
  the mutation. Nothing mutates before the second tap. See `on_invoice_void`
  and `on_invoice_paid`.
- **`_CallbackUpdate`** adapts a `CallbackQuery` into something with
  `.message`, so command-style handlers can be reused from menu buttons
  without rewriting them.

All user-facing strings belong in `texts.py`. Never inline a Persian string in
`handlers.py`.

---

## 6. Conventions that will bite you

- **Money is an `int` in تومان.** No floats, no currency objects, no rials.
- **Dates are Jalali** for display, `datetime` internally, via `core/jalali.py`.
- **Persian digits** on output (`money.to_persian_digits`), and parsers accept
  both Persian and ASCII digits on input.
- **Docstrings and comments are Persian.** Match the surrounding density and
  tone. Do not add English comments to a Persian file.
- **Never commit the Google service-account JSON.** It is read from
  `os.environ` only. No credentials in code, tests, or docs — ever.

---

## 7. Traps — things that look like bugs but are not

**`jalali.day_bounds()` returns `(start, base)`, not `(start, end_of_day)`.**
Same for `week_bounds` / `month_bounds`. They mean "period start → *this
instant*". Consequence: a test that captures `now = jalali.now()`, then
creates a record (which stamps a *fresh* `now` microseconds later), then
queries with the stale `now`, will miss its own record. Call `jalali.now()`
fresh at assertion time.

**Two different functions are named `_parse_item`.**
`core.invoice_nlp._parse_item` parses one-sentence invoices.
`handlers._parse_item` / `_parse_item_free` serve the manual step-by-step
invoice builder (`flow == "invoice_items"`). They are independent. Fixing one
does not fix the other, and testing one does not test the other.

**Two tests read the source code and will fail on unrelated-looking changes:**

- `tests/test_cancel.py` regex-scans `handlers.py` for every
  `user_data["flow"] = "..."` literal and asserts the set equals a hardcoded
  `COVERED_FLOWS`. Add a new flow → update that set **and** add a real
  cancel test for it. This is deliberate: it guarantees every flow is
  cancellable.
- `tests/test_menu.py::test_every_action_has_a_dispatch_path` checks every
  `act:*` callback in every submenu keyboard against a hardcoded map. Add a
  menu button → update it.

When these fail, the test is usually right and your change is incomplete.

**Several tests assert exact keyboard shapes** (button counts, callback-data
order). If you intentionally add a button, update the expectation — but never
weaken the assertion into something vague. These are safety nets.

**`get_stt_provider` returns a process-wide singleton** for the local
faster-whisper provider, because loading the model takes seconds. Tests that
select it must reset `stt._local_provider_singleton`.

---

## 8. Subscriptions — how gating actually works

Two independent mechanisms, easy to confuse:

- `sub_service.is_active(store, uid)` — is the subscription unexpired?
  Gates the **write** paths: logging a transaction, repeating one, previewing
  and issuing invoices, reading a receipt photo.
- `sub_service.has_feature(store, uid, feature)` — does the tier include this
  feature? Gates voice, OCR, statement cards, the invoice watermark, group
  mode, dollar view. An expired subscription degrades to bronze (empty
  feature set) rather than cutting access entirely, so users can still read
  their data.

New users get a 14-day trial at **gold** (everything unlocked).
`plans.FREE_LIMITS` exists but is **deliberately not enforced anywhere** — do
not wire it up without an explicit decision. `docs/REVENUE_STRATEGY.md`
analyses the consequences of this gating layout; read it before changing
tiers.

---

## 9. What not to build

`docs/PRODUCT_SCOPE.md` is a decision document, not a wish list. In short:

- No inventory/stock control, no payroll, no tax filing, no ERP features.
- No accountant-facing multi-client panel, no roles/approval hierarchies —
  multi-user is an explicit exit trigger.
- **سامانه مودیان (Iranian tax e-invoicing) stays a dry-run skeleton.** Real
  integration needs an official spec that is not publicly fetchable; the
  reasoning is in the README. Do not implement signing or payload structure
  from guesswork — wrong invoices filed with the tax authority are not a
  recoverable error.
- The standing rule: *"محصول را کامل‌تر نکن؛ آن را «به‌اندازه»‌تر کن."*
  Do not make the product more complete; make it more right-sized.

---

## 10. Where the documentation is

| File | What it answers |
|---|---|
| `docs/README.md` | Index of every doc, with audience |
| `docs/PRODUCT_SCOPE.md` | What to build and what to refuse |
| `docs/USER_GUIDE.md` | What the end user sees (+ PDF/HTML) |
| `docs/REVENUE_STRATEGY.md` | Pricing, gating, go-to-market |
| `docs/SERVER_RUNBOOK.md` | Running it on a server; schema migration in ops terms |
| `docs/PILOT.md` | Pilot setup, smoke test, success metrics |
| `DEPLOYMENT.md` / `.env.example` | Deploy architecture, full env var table |

---

## 11. Working agreement

1. Read `docs/PRODUCT_SCOPE.md` before adding a feature.
2. Put pure logic in `core/` and unit-test it there.
3. Run the **full** suite before claiming done — these tests catch
   cross-module breakage, and a targeted run will miss it.
4. When a source-scanning test fails, fix your change, not the test.
5. Report results honestly: exact pass/fail counts, and say plainly what you
   did not do.
