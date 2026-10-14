"""Smoke test: verify imports, i18n completeness, DB persistence, and timezone math
without needing a real bot token, network, or LLM key."""
import os
import sys

# Provide a dummy token so config imports cleanly.
os.environ["BOT_TOKEN"] = "000000:test"
os.environ["DATA_DIR"] = "/tmp/bot_test_data"
os.environ["LLM_API_KEY"] = ""  # LLM client disabled -> graceful fallbacks

sys.path.insert(0, os.path.dirname(__file__))
from bot import config, db, i18n, timezones  # noqa: E402

import asyncio
from datetime import datetime, timezone  # noqa: E402


def test_i18n_complete():
    keys_en = set(i18n.STRINGS["en"].keys())
    for lang, table in i18n.STRINGS.items():
        missing = keys_en - set(table.keys())
        assert not missing, f"{lang} missing keys: {missing}"
    assert i18n.t("ru", "start") != i18n.t("en", "start")
    print("i18n complete:", sorted(i18n.LANGUAGES))


def test_timezone():
    # "tomorrow 10:00" in Moscow == 07:00 UTC (RTZ2 -> MSK is UTC+3).
    naive = datetime(2026, 10, 15, 10, 0, 0)
    utc = timezones.to_utc(naive, "Europe/Moscow")
    assert utc.hour == 7, utc
    assert timezones.resolve_timezone("moscow") == "Europe/Moscow"
    assert timezones.resolve_timezone("Europe/Berlin") == "Europe/Berlin"
    assert timezones.resolve_timezone("totally-not-a-city") is None
    print("timezone ok: MSK 10:00 ->", utc)


async def test_db():
    await db.init_db()
    async with db.SessionFactory() as s:
        u = await db.get_user(s, 123456)
        assert u.id == 123456
        u.timezone = "Europe/Moscow"
        await s.commit()

        s.add(db.Reminder(user_id=u.id, text="call mom",
                          remind_at=datetime.now(timezone.utc), recurrence="none"))
        await s.commit()

        rem = await db.list_active_reminders(s, u.id)
        assert len(rem) == 1 and rem[0].text == "call mom"

        stats = await db.count_stats(s, u.id)
        assert stats["total"] == 1 and stats["active"] == 1

        # delete + clear
        from sqlalchemy import delete
        await s.execute(delete(db.Reminder).where(db.Reminder.user_id == u.id))
        await s.commit()
        assert await db.list_active_reminders(s, u.id) == []
    print("db persistence ok")


async def test_imports():
    from bot import keyboards, main, scheduler, llm  # noqa: F401
    print("all modules import cleanly")


async def run():
    test_i18n_complete()
    test_timezone()
    await test_imports()
    await test_db()
    print("\nALL SMOKE TESTS PASSED")


asyncio.run(run())