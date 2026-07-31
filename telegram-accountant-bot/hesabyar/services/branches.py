"""شعبه‌ها: چند نقطه‌ی فروش زیر یک کسب‌وکار.

صاحب کسب‌وکار برای هر شعبه یک **کد پیوستن** می‌گیرد و به مسئولِ همان شعبه
می‌دهد. کارمند کد را برای بات می‌فرستد و از آن پس هر چه ثبت کند، در دفترِ
**صاحب کسب‌وکار** و با برچسبِ همان شعبه می‌نشیند. آخر روز صاحب‌کار می‌بیند هر
شعبه چقدر فروخته و جمعِ کل چقدر بوده است.

عمداً ساده نگه داشته شده: نه ماتریسِ نقش و دسترسی، نه تأیید چندمرحله‌ای —
آن‌ها آن‌سوی «باندِ تلگرام» هستند (نگاه کنید به ``docs/PRODUCT_SCOPE.md``).
"""
from __future__ import annotations

import datetime as dt
import secrets
import string
from typing import Optional

from ..core import jalali, money
from ..db.models import Branch, BranchMember, Kind
from ..db.store import Store

#: طول کد پیوستن (حروف بزرگ و رقم، بدون کاراکترهای گیج‌کننده)
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LEN = 6


def new_code() -> str:
    """کد پیوستنِ یکتا و خوانا (بدون O/0 و I/1 که اشتباه خوانده می‌شوند)."""
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LEN))


async def create_branch(store: Store, owner_id: int, name: str) -> Branch:
    """یک شعبه‌ی جدید با کد پیوستنِ یکتا می‌سازد."""
    existing = {b.code for b in store.list("branches", lambda b: True)}
    code = new_code()
    while code in existing:
        code = new_code()
    branch = Branch(owner_id=owner_id, name=name.strip()[:100] or "شعبه", code=code)
    await store.add("branches", branch)
    return branch


def list_branches(store: Store, owner_id: int) -> list[Branch]:
    """شعبه‌های فعالِ یک کسب‌وکار (قدیمی‌تر اول)."""
    rows = store.list(
        "branches", lambda b: b.owner_id == owner_id and b.is_active
    )
    return sorted(rows, key=lambda b: b.id or 0)


def get_branch(store: Store, branch_id: int) -> Optional[Branch]:
    return store.get("branches", branch_id)


def branch_by_code(store: Store, code: str) -> Optional[Branch]:
    """شعبه را با کد پیوستن پیدا می‌کند (کد بدون حساسیت به بزرگی/کوچکی)."""
    wanted = (code or "").strip().upper()
    if len(wanted) != _CODE_LEN:
        return None
    rows = store.list(
        "branches", lambda b: b.is_active and b.code.upper() == wanted
    )
    return rows[0] if rows else None


async def deactivate_branch(
    store: Store, owner_id: int, branch_id: int
) -> Optional[Branch]:
    """شعبه را غیرفعال می‌کند (کدش دیگر کار نمی‌کند). داده‌ها می‌مانند."""
    branch = store.get("branches", branch_id)
    if branch is None or branch.owner_id != owner_id:
        return None
    branch.is_active = False
    await store.update("branches", branch)
    return branch


# --- عضویت کارمند --------------------------------------------------------------


def membership_for(store: Store, user_id: int) -> Optional[BranchMember]:
    """اگر این کاربر کارمندِ شعبه‌ای باشد، عضویتش را برمی‌گرداند."""
    rows = store.list("branch_members", lambda m: m.user_id == user_id)
    return rows[0] if rows else None


def members_of(store: Store, branch_id: int) -> list[BranchMember]:
    return store.list("branch_members", lambda m: m.branch_id == branch_id)


async def join_with_code(
    store: Store, user_id: int, code: str, name: str = ""
) -> Optional[BranchMember]:
    """کارمند را با کد به شعبه می‌پیوندد؛ ``None`` اگر کد معتبر نباشد.

    اگر قبلاً عضو جای دیگری بوده، عضویتش به شعبه‌ی جدید منتقل می‌شود تا یک
    نفر هم‌زمان از دو شعبه ثبت نکند.
    """
    branch = branch_by_code(store, code)
    if branch is None or branch.owner_id == user_id:
        return None  # صاحب کسب‌وکار لازم نیست به شعبه‌ی خودش بپیوندد

    current = membership_for(store, user_id)
    if current is not None:
        current.branch_id = branch.id
        current.owner_id = branch.owner_id
        current.name = name[:100] or current.name
        await store.update("branch_members", current)
        return current

    member = BranchMember(
        branch_id=branch.id, owner_id=branch.owner_id,
        user_id=user_id, name=name[:100],
    )
    await store.add("branch_members", member)
    return member


async def leave(store: Store, user_id: int) -> bool:
    """کارمند از شعبه خارج می‌شود."""
    member = membership_for(store, user_id)
    if member is None:
        return False
    await store.delete("branch_members", member.id)
    return True


def routing_for(store: Store, user_id: int) -> tuple[int, int]:
    """(صاحبِ دفتر، شناسه‌ی شعبه) برای ثبتِ یک تراکنش.

    برای کاربر عادی: خودش و شعبه‌ی ۰. برای کارمندِ شعبه: صاحب کسب‌وکار و
    شعبه‌ی خودش.
    """
    member = membership_for(store, user_id)
    if member is None:
        return user_id, 0
    return member.owner_id, member.branch_id


# --- گزارش ---------------------------------------------------------------------


def branch_totals(
    store: Store, owner_id: int, start: dt.datetime, end: dt.datetime
) -> list[dict]:
    """جمعِ درآمد/هزینه‌ی هر شعبه در یک بازه (به‌علاوه‌ی ثبت‌های خودِ صاحب‌کار)."""
    buckets: dict[int, dict] = {}

    def _in_range(t) -> bool:
        return (
            t.user_id == owner_id
            and t.occurred_at is not None
            and start <= t.occurred_at <= end
        )

    for t in store.list("transactions", _in_range):
        b = buckets.setdefault(
            int(t.branch_id or 0), {"income": 0, "expense": 0, "count": 0}
        )
        if t.kind == Kind.INCOME:
            b["income"] += int(t.amount)
        else:
            b["expense"] += int(t.amount)
        b["count"] += 1

    names = {b.id: b.name for b in store.list("branches", lambda b: b.owner_id == owner_id)}
    out = []
    for branch_id, data in buckets.items():
        out.append({
            "branch_id": branch_id,
            "name": names.get(branch_id, "خودِ من") if branch_id else "خودِ من",
            "income": data["income"],
            "expense": data["expense"],
            "balance": data["income"] - data["expense"],
            "count": data["count"],
        })
    return sorted(out, key=lambda r: r["income"], reverse=True)


def build_branch_report(
    store: Store, owner_id: int, start: dt.datetime, end: dt.datetime,
    title: str = "امروز",
) -> str:
    """گزارش مقایسه‌ای شعبه‌ها."""
    rows = branch_totals(store, owner_id, start, end)
    if not rows:
        return f"🏬 در بازه‌ی «{title}» هنوز ثبتی نداشته‌اید."

    total_in = sum(r["income"] for r in rows)
    total_out = sum(r["expense"] for r in rows)
    lines = [f"🏬 <b>گزارش شعبه‌ها — {title}</b>", ""]
    for r in rows:
        lines.append(
            f"• <b>{r['name']}</b>: 🟢 {money.format_amount(r['income'])}"
            f" | 🔴 {money.format_amount(r['expense'])}"
        )
    lines += [
        "",
        f"جمع درآمد: <b>{money.format_amount(total_in)}</b>",
        f"جمع هزینه: {money.format_amount(total_out)}",
        f"مانده: <b>{money.format_amount(total_in - total_out)}</b>",
    ]
    return "\n".join(lines)


def build_branch_list(store: Store, owner_id: int) -> str:
    """فهرست شعبه‌ها با کد پیوستن و تعداد کارمند."""
    branches = list_branches(store, owner_id)
    if not branches:
        return (
            "هنوز شعبه‌ای نساخته‌اید. 🏬\n"
            "با «➕ شعبه‌ی جدید» یکی بسازید و کدش را به مسئولِ آن شعبه بدهید."
        )
    lines = ["🏬 <b>شعبه‌های شما</b>", ""]
    for b in branches:
        count = len(members_of(store, b.id))
        lines.append(
            f"• <b>{b.name}</b> — کد پیوستن: <code>{b.code}</code> "
            f"({money.to_persian_digits(str(count))} کارمند)"
        )
    lines.append("\nکد را به مسئولِ شعبه بدهید تا با <code>/join کد</code> بپیوندد.")
    return "\n".join(lines)
