"""Background scheduler: a polling loop that fires due reminders.

Everything lives in the DB, so a restart never loses a reminder — the loop just
re-reads whatever is due on every tick. Simple and crash-safe.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from aiogram import Bot

from . import config, db, i18n
from .db import Reminder, SessionFactory


def _next_occurrence(dt: datetime, recurrence: str) -> datetime | None:
    if recurrence == "daily":
        return dt + timedelta(days=1)
    if recurrence == "weekly":
        return dt + timedelta(weeks=1)
    if recurrence == "monthly":
        # Add ~30 days; good enough for a personal secretary.
        return dt + timedelta(days=30)
    return None


async def tick(bot: Bot) -> None:
    """Send every reminder that has come due (and reschedule recurring ones)."""
    now = datetime.now(timezone.utc)
    async with SessionFactory() as session:
        due = await db.list_due_reminders(session, now)
        for r in due:
            user = await db.get_user(session, r.user_id)
            if not user.notifications_enabled:
                # Still advance the reminder so it doesn't spam forever.
                nxt = _next_occurrence(r.remind_at, r.recurrence)
                if nxt is None:
                    await db.mark_done(session, r.id, now)
                else:
                    r.remind_at = nxt
                    await session.commit()
                continue

            lang = db.effective_language(user)
            text = i18n.t(lang, "notif", text=r.text)
            try:
                await bot.send_message(r.user_id, text)
            except Exception as exc:  # network / user blocked the bot
                print(f"[scheduler] send failed for {r.id}: {exc}")

            nxt = _next_occurrence(r.remind_at, r.recurrence)
            if nxt is None:
                await db.mark_done(session, r.id, now)
            else:
                r.remind_at = nxt
                r.last_notified = now
                await session.commit()


async def run_scheduler(bot: Bot) -> None:
    """Infinite loop; keep a reference to the task so it can be cancelled."""
    while True:
        try:
            await tick(bot)
        except Exception as exc:
            print(f"[scheduler] tick error: {exc}")
        await asyncio.sleep(config.POLL_INTERVAL_SEC)