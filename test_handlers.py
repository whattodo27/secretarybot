"""Exercise the real handler functions directly (fake Telegram objects + real DB)
to prove the 'My reminders' empty-list flow and the language offer both work
without raising — the two things the user reported broken."""
import asyncio
import os
import sys
from types import SimpleNamespace

os.environ["BOT_TOKEN"] = "000:test"
os.environ["DATA_DIR"] = "/tmp/bot_test_data2"
os.environ["LLM_API_KEY"] = ""  # LLM disabled -> graceful fallback

sys.path.insert(0, os.path.dirname(__file__))
from bot import config, db, i18n, keyboards, main  # noqa: E402


class FakeMessage:
    def __init__(self):
        self.edited = None
        self.answered = []
        self.chat = SimpleNamespace(id=1)

    async def edit_text(self, text, **kw):
        self.edited = (text, kw)
        return self

    async def answer(self, text, **kw):
        self.answered.append((text, kw))
        return self


class FakeCB:
    def __init__(self, user_id):
        self.from_user = SimpleNamespace(id=user_id)
        self.message = FakeMessage()
        self.data = "menu:reminders"
        self._n = 0

    async def answer(self, *a, **kw):
        self._n += 1


class FakeState:
    async def clear(self): ...
    async def set_state(self, s): ...
    async def update_data(self, **kw): ...
    async def get_data(self): return {}


async def test_empty_reminders():
    await db.init_db()
    async with db.SessionFactory() as s:
        await db.get_user(s, 777)  # create user 777 with no reminders

    cb = FakeCB(777)
    await main.on_menu_reminders(cb, FakeState())

    assert cb.message.edited is not None, "edit_text was NOT called -> button 'does nothing'!"
    text, kw = cb.message.edited
    assert "no_reminders" in text or "reminders" in text.lower(), text
    kb = kw.get("reply_markup")
    buttons = [b.text for row in kb.inline_keyboard for b in row]
    assert any("Главное меню" in b or "Main menu" in b for b in buttons), buttons
    print("empty reminders OK ->", repr(text[:60]), "| buttons:", buttons)


def test_language_offer():
    # current=en, detected=ru -> must return a visible question with 🇷🇺 and flags.
    offer = main._language_offer("ru", "en")
    assert offer is not None
    question, kb = offer
    assert "🇷🇺" in question and "Русский" in question, question
    labels = [b.text for row in kb.inline_keyboard for b in row]
    assert any("🇷🇺" in l and "переключить" in l for l in labels), labels
    assert any("🇬🇧" in l for l in labels), labels
    print("language offer OK ->", repr(question), "| buttons:", labels)

    # same language -> no offer; auto -> no offer
    assert main._language_offer("en", "en") is None
    assert main._language_offer("ru", "auto") is None
    print("offer suppressed correctly (same lang / auto)")


def test_flags_and_back_keys():
    assert i18n.FLAGS["ru"] == "🇷🇺" and i18n.FLAGS["en"] == "🇬🇧"
    for lang in i18n.STRINGS:
        assert "back" in i18n.STRINGS[lang], f"{lang} missing 'back' key"
    # language picker shows flags
    kb = keyboards.language_menu("ru", "auto")
    labels = [b.text for row in kb.inline_keyboard for b in row]
    assert any("Русский 🇷🇺" in l for l in labels), labels
    assert any("English 🇬🇧" in l for l in labels), labels
    print("flags + back keys OK ->", labels[:4], "...")


async def run():
    test_language_offer()
    test_flags_and_back_keys()
    await test_empty_reminders()
    print("\nALL HANDLER TESTS PASSED")


asyncio.run(run())