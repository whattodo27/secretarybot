"""Regression test for the exact crash from the user's log:

    TypeError: can't compare offset-naive and offset-aware datetimes
    at  _render_reminders:  upcoming = [r for r in reminders if r.remind_at <= window]

Inserts a reminder with an *aware* UTC datetime (what the create-path stores),
reads it back (must be naive UTC after the UTCDateTime fix), then runs the real
dispatcher to confirm the 'My reminders' button no longer crashes with data present.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

os.environ["BOT_TOKEN"] = "000:test"
os.environ["DATA_DIR"] = "/tmp/bot_naive_test"
os.environ["LLM_API_KEY"] = ""

sys.path.insert(0, os.path.dirname(__file__))
from bot import main, db  # noqa: E402

from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.fsm.storage.memory import MemoryStorage  # noqa: E402
from aiogram.types import Update, CallbackQuery, Message, User as TGUser, Chat  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.methods import GetMe, SendMessage, EditMessageText, AnswerCallbackQuery  # noqa: E402


class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.edited = []

    async def make_request(self, bot, method, timeout=None):
        if isinstance(method, GetMe):
            return TGUser(id=0, is_bot=True, first_name="Bot")
        if isinstance(method, (SendMessage, EditMessageText)):
            chat = Chat(id=getattr(method, "chat_id", None) or 123, type="private")
            if isinstance(method, EditMessageText):
                self.edited.append(method)
            return Message(
                message_id=getattr(method, "message_id", None) or 1,
                date=datetime.now(), chat=chat, text=getattr(method, "text", None),
                reply_markup=getattr(method, "reply_markup", None),
            )
        if isinstance(method, AnswerCallbackQuery):
            return True
        return None

    async def stream_content(self, url, timeout=None, chunk_size=65536, **kwargs):
        raise NotImplementedError

    async def close(self):
        pass


async def run():
    await db.init_db()
    async with db.SessionFactory() as s:
        await db.get_user(s, 555)
        # Simulate what the create-path stores: an AWARE UTC datetime.
        aware = datetime.now(timezone.utc) + timedelta(hours=2)
        s.add(db.Reminder(user_id=555, text="позвонить маме", remind_at=aware))
        await s.commit()

        # Read back: must now be NAIVE UTC (the whole point of UTCDateTime).
        rem = (await db.list_active_reminders(s, 555))[0]
        assert rem.remind_at.tzinfo is None, (
            f"remind_at should be naive UTC, got tzinfo={rem.remind_at.tzinfo!r}"
        )
        print("read-back remind_at is naive UTC:", rem.remind_at)

    bot = Bot("000:test", session=FakeSession())
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(main.router)

    msg = Message(message_id=10, date=datetime.now(),
                  chat=Chat(id=555, type="private"), text="start",
                  reply_markup=main.keyboards.main_menu("en"))
    cbq = CallbackQuery(id="cb", from_user=TGUser(id=555, is_bot=False, first_name="T"),
                        chat_instance="x", message=msg, data="menu:reminders")
    await dp.feed_update(bot, Update(update_id=1, callback_query=cbq))

    assert len(bot.session.edited) == 1, "expected exactly one editMessageText"
    text = bot.session.edited[0].text
    assert "позвонить маме" in text, text
    print("'My reminders' with data present -> OK, no TypeError:")
    print("  ", text.replace("\n", " | ")[:120])


asyncio.run(run())
print("NAIVE-DATETIME REGRESSION TEST PASSED")