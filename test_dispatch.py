"""Faithful dispatch test: feed a REAL CallbackQuery update through aiogram's
Dispatcher and record what it sends to Telegram. This catches routing/filter
and bot-call bugs that direct handler calls miss."""
import asyncio
import os
import sys
from datetime import datetime

os.environ["BOT_TOKEN"] = "000:test"
os.environ["DATA_DIR"] = "/tmp/bot_dispatch_test"
os.environ["LLM_API_KEY"] = ""

sys.path.insert(0, os.path.dirname(__file__))
from bot import main, db  # noqa: E402

from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.fsm.storage.memory import MemoryStorage  # noqa: E402
from aiogram.types import (  # noqa: E402
    Update, CallbackQuery, Message, User as TGUser, Chat,
)
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.methods import (  # noqa: E402
    GetMe, SendMessage, EditMessageText, AnswerCallbackQuery,
)


class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.sent: list = []
        self.edited: list = []
        self.answered: list = []

    async def make_request(self, bot, method, timeout=None):
        if isinstance(method, GetMe):
            return TGUser(id=0, is_bot=True, first_name="Bot")
        if isinstance(method, (SendMessage, EditMessageText)):
            chat_id = getattr(method, "chat_id", None) or 123
            chat = Chat(id=chat_id, type="private")
            mid = getattr(method, "message_id", None) or 1
            result = Message(
                message_id=mid, date=datetime.now(), chat=chat,
                text=getattr(method, "text", None),
                reply_markup=getattr(method, "reply_markup", None),
            )
            if isinstance(method, SendMessage):
                self.sent.append(method)
            else:
                self.edited.append(method)
            return result
        if isinstance(method, AnswerCallbackQuery):
            self.answered.append(method)
            return True
        return None

    async def stream_content(self, url, timeout=None, chunk_size=65536, **kwargs):
        raise NotImplementedError

    async def close(self):
        pass


async def run():
    await db.init_db()
    async with db.SessionFactory() as s:
        await db.get_user(s, 123)  # user 123, no reminders

    bot = Bot("000:test", session=FakeSession())
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(main.router)

    user = TGUser(id=123, is_bot=False, first_name="Tester")
    chat = Chat(id=123, type="private")
    msg = Message(
        message_id=10, date=datetime.now(), chat=chat, text="start",
        reply_markup=main.keyboards.main_menu("en"),
    )
    cbq = CallbackQuery(
        id="cb-1", from_user=user, chat_instance="abc", message=msg,
        data="menu:reminders",
    )
    update = Update(update_id=1, callback_query=cbq)

    await dp.feed_update(bot, update)

    sess = bot.session
    print("editMessageText calls:", len(sess.edited))
    if sess.edited:
        m = sess.edited[0]
        print("  text:", repr(m.text))
        btns = [b.text for r in (m.reply_markup.inline_keyboard or []) for b in r]
        print("  buttons:", btns)
    print("answerCallbackQuery calls:", len(sess.answered))
    print("sendMessage calls:", len(sess.sent))

    assert len(sess.edited) >= 1, "Button did NOT trigger editMessageText -> routing broke!"


asyncio.run(run())
print("DISPATCH TEST PASSED")