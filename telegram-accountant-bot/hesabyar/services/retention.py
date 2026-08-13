"""رویدادهای سبکِ ماندگاری (Retention Core).

سکوی آنالیتیکسِ جدا **نیست** — فقط ثبتِ چند رخدادِ کوچک روی همان Store، برای
جمع‌زدن در ``/pilot`` (فاز ۱۹): جمع‌بندیِ روزانه فرستاده/تمام‌شد، یادآوریِ
سررسید فرستاده شد، ردیفِ دفتر تسویه شد. هیچ‌کدام جای رکوردِ مالی را نمی‌گیرند
و خودشان هیچ‌جا چیزی را اجرا/بلاک نمی‌کنند — فقط شمارش.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Optional

from ..db.models import RetentionEvent, RetentionEventKind
from ..db.store import Store


async def log_event(
    store: Store, user_id: int, kind: str, meta: str = ""
) -> RetentionEvent:
    """یک رخداد ثبت می‌کند. هیچ‌وقت رکوردِ مالی نمی‌سازد یا چیزی را بلاک نمی‌کند."""
    event = RetentionEvent(user_id=user_id, kind=kind, meta=str(meta or ""))
    await store.add("retention_events", event)
    return event


def events_since(
    store: Store, kind: str, since: dt.datetime, until: Optional[dt.datetime] = None
) -> list[RetentionEvent]:
    """رویدادهای یک نوع، از ``since`` تا ``until`` (پیش‌فرض: بدون سقفِ بالا)."""

    def _match(e: RetentionEvent) -> bool:
        if e.kind != kind or e.created_at is None:
            return False
        if e.created_at < since:
            return False
        if until is not None and e.created_at > until:
            return False
        return True

    return store.list("retention_events", _match)


def distinct_users(events: list[RetentionEvent]) -> set[int]:
    return {e.user_id for e in events}


def reminder_driven_settlements(
    store: Store, since: dt.datetime, until: dt.datetime
) -> int:
    """تخمینِ زیرِحدی از تسویه‌هایی که یادآوری پشتشان بوده.

    «همان روز یا فردای یک یادآوریِ فرستاده‌شده به همان کاربر» را می‌شمارد —
    هم‌زمانی است، نه ردیابیِ دقیقِ علّیت (که نیازمندِ زیرساختِ اضافه‌تری
    است که این فاز عمداً نمی‌سازد).
    """
    sent = events_since(store, RetentionEventKind.DUE_REMINDER_SENT, since, until)
    settled = events_since(store, RetentionEventKind.LEDGER_SETTLED, since, until)

    sent_windows: dict[int, set] = defaultdict(set)
    for e in sent:
        day = e.created_at.date()
        sent_windows[e.user_id].add(day)
        sent_windows[e.user_id].add(day + dt.timedelta(days=1))

    return sum(
        1 for e in settled
        if e.created_at is not None
        and e.created_at.date() in sent_windows.get(e.user_id, set())
    )
