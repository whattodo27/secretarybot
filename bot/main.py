"""Personal-secretary Telegram bot — entrypoint and all handlers."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import delete

from . import config, db, i18n, keyboards, llm, timezones
from .db import Reminder, SessionFactory
from .scheduler import run_scheduler

router = Router()


# --- FSM states ------------------------------------------------

class EditFlow(StatesGroup):
    waiting_text = State()
    waiting_time = State()


class TZFlow(StatesGroup):
    waiting_city = State()


class CreateFlow(StatesGroup):
    waiting_time = State()  # user gave text but no time; collect time next


# --- formatting helpers ----------------------------------------


def fmt_reminder(r: Reminder, lang: str, tz: str) -> str:
    local = timezones.to_local(r.remind_at, tz)
    now_local = timezones.now_local(tz)
    when = i18n.format_dt(local, lang, now_local)
    rec = i18n.tr_recurrence(lang, r.recurrence)
    return f"• {r.text} — {when}{rec}"


def _match_reminder(reminders: list[Reminder], ref: str) -> int | None:
    """Match a free-text/LLM reference to an existing reminder id."""
    ref_l = (ref or "").strip().lower()
    if ref_l.isdigit():
        idx = int(ref_l)
        if 0 <= idx < len(reminders):
            return reminders[idx].id
    for r in reminders:
        if ref_l and ref_l in r.text.lower():
            return r.id
    return None


async def edit_or_send(cb: CallbackQuery, text: str, reply_markup=None) -> None:
    """Edit the message in place; if Telegram rejects the edit ('message is not
    modified', stale/deleted message, etc.), send a fresh message instead so the
    button press never looks dead."""
    try:
        await cb.message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=reply_markup)
    finally:
        await cb.answer()


# --- /start and /help ------------------------------------------


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    async with SessionFactory() as session:
        user = await db.get_user(session, message.from_user.id)
        lang = db.effective_language(user)
    await message.answer(
        i18n.t(lang, "start"), reply_markup=keyboards.main_menu(lang)
    )


@router.message(Command("help"))
async def cmd_help(message: Message, state: FSMContext) -> None:
    await state.clear()
    async with SessionFactory() as session:
        user = await db.get_user(session, message.from_user.id)
        lang = db.effective_language(user)
    await message.answer(i18n.t(lang, "start"), reply_markup=keyboards.main_menu(lang))


# --- main menu navigation --------------------------------------


@router.callback_query(F.data == "menu:root")
async def on_menu_root(cb: CallbackQuery) -> None:
    async with SessionFactory() as session:
        user = await db.get_user(session, cb.from_user.id)
        lang = db.effective_language(user)
    await edit_or_send(cb, i18n.t(lang, "menu"), keyboards.main_menu(lang))


@router.callback_query(F.data == "menu:reminders")
async def on_menu_reminders(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _render_reminders(cb, page=0)


async def _render_reminders(cb: CallbackQuery, page: int) -> None:
    async with SessionFactory() as session:
        user = await db.get_user(session, cb.from_user.id)
        lang = db.effective_language(user)
        tz = user.timezone
        reminders = await db.list_active_reminders(session, user.id)

    if not reminders:
        text = f"{i18n.t(lang, 'reminders_title')}\n\n{i18n.t(lang, 'no_reminders')}"
        await edit_or_send(cb, text, keyboards.empty_reminders_kb(lang))
        return

    now = datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC, matches DB storage
    window = now + timedelta(hours=config.UPCOMING_WINDOW_H)
    upcoming = [r for r in reminders if r.remind_at <= window]
    later = [r for r in reminders if r.remind_at > window]

    lines = [i18n.t(lang, "reminders_title"), "", i18n.t(lang, "upcoming")]
    if upcoming:
        lines += [fmt_reminder(r, lang, tz) for r in upcoming]
    else:
        lines.append(i18n.t(lang, "no_upcoming"))

    lines += ["", i18n.t(lang, "later")]
    if later:
        lines += [fmt_reminder(r, lang, tz) for r in later]
    else:
        lines.append(i18n.t(lang, "no_later"))

    kb, _ = keyboards.reminders_list(lang, reminders, page)
    await edit_or_send(cb, "\n".join(lines), kb)


@router.callback_query(F.data.startswith("list:page:"))
async def on_list_page(cb: CallbackQuery) -> None:
    page = int(cb.data.split(":")[2])
    await _render_reminders(cb, page)


# --- reminder detail / edit / delete ---------------------------


@router.callback_query(F.data == "rem:list")
async def on_rem_list(cb: CallbackQuery) -> None:
    await _render_reminders(cb, page=0)


@router.callback_query(F.data.startswith("rem:view:"))
async def on_rem_view(cb: CallbackQuery, state: FSMContext) -> None:
    rid = int(cb.data.split(":")[2])
    await state.clear()
    async with SessionFactory() as session:
        user = await db.get_user(session, cb.from_user.id)
        lang = db.effective_language(user)
        tz = user.timezone
        r = await session.get(Reminder, rid)
        if r is None or r.user_id != user.id:
            await cb.answer()
            return
        detail = fmt_reminder(r, lang, tz)
    await cb.message.edit_text(
        detail, reply_markup=keyboards.reminder_detail(lang, rid)
    )
    await cb.answer()


@router.callback_query(F.data.startswith("rem:edit_text:"))
async def on_edit_text(cb: CallbackQuery, state: FSMContext) -> None:
    rid = int(cb.data.split(":")[2])
    async with SessionFactory() as session:
        user = await db.get_user(session, cb.from_user.id)
        lang = db.effective_language(user)
    await state.set_state(EditFlow.waiting_text)
    await state.update_data(target_id=rid)
    await cb.message.edit_text(i18n.t(lang, "ask_new_text"))
    await cb.answer()


@router.callback_query(F.data.startswith("rem:edit_time:"))
async def on_edit_time(cb: CallbackQuery, state: FSMContext) -> None:
    rid = int(cb.data.split(":")[2])
    async with SessionFactory() as session:
        user = await db.get_user(session, cb.from_user.id)
        lang = db.effective_language(user)
    await state.set_state(EditFlow.waiting_time)
    await state.update_data(target_id=rid)
    await cb.message.edit_text(i18n.t(lang, "ask_new_time"))
    await cb.answer()


@router.callback_query(F.data.startswith("rem:delete:"))
async def on_rem_delete(cb: CallbackQuery) -> None:
    rid = int(cb.data.split(":")[2])
    async with SessionFactory() as session:
        user = await db.get_user(session, cb.from_user.id)
        lang = db.effective_language(user)
    await cb.message.edit_text(
        i18n.t(lang, "confirm_delete"), reply_markup=keyboards.confirm_delete(lang, rid)
    )
    await cb.answer()


@router.callback_query(F.data.startswith("rem:delete_yes:"))
async def on_rem_delete_yes(cb: CallbackQuery, state: FSMContext) -> None:
    rid = int(cb.data.split(":")[2])
    async with SessionFactory() as session:
        user = await db.get_user(session, cb.from_user.id)
        lang = db.effective_language(user)
        r = await session.get(Reminder, rid)
        if r is not None and r.user_id == user.id:
            await session.delete(r)
            await session.commit()
    await state.clear()
    await cb.message.edit_text(
        i18n.t(lang, "deleted"), reply_markup=keyboards.main_menu(lang)
    )
    await cb.answer()


# --- manage menu ---


@router.callback_query(F.data == "rem:manage")
async def on_manage(cb: CallbackQuery) -> None:
    async with SessionFactory() as session:
        user = await db.get_user(session, cb.from_user.id)
        lang = db.effective_language(user)
    await cb.message.edit_text(
        i18n.t(lang, "manage"), reply_markup=keyboards.manage_menu(lang)
    )
    await cb.answer()


@router.callback_query(F.data == "rem:stats")
async def on_stats(cb: CallbackQuery) -> None:
    async with SessionFactory() as session:
        user = await db.get_user(session, cb.from_user.id)
        lang = db.effective_language(user)
        stats = await db.count_stats(session, user.id)
    await cb.message.edit_text(
        i18n.t(lang, "stats", **stats), reply_markup=keyboards.manage_menu(lang)
    )
    await cb.answer()


@router.callback_query(F.data == "rem:clear_all")
async def on_clear_all(cb: CallbackQuery) -> None:
    async with SessionFactory() as session:
        user = await db.get_user(session, cb.from_user.id)
        lang = db.effective_language(user)
    await cb.message.edit_text(
        i18n.t(lang, "confirm_clear_all"), reply_markup=keyboards.confirm_clear_all(lang)
    )
    await cb.answer()


@router.callback_query(F.data == "rem:clear_all_yes")
async def on_clear_all_yes(cb: CallbackQuery) -> None:
    async with SessionFactory() as session:
        user = await db.get_user(session, cb.from_user.id)
        lang = db.effective_language(user)
        await session.execute(delete(Reminder).where(Reminder.user_id == user.id))
        await session.commit()
    await cb.message.edit_text(
        i18n.t(lang, "cleared"), reply_markup=keyboards.main_menu(lang)
    )
    await cb.answer()


# --- settings ---


@router.callback_query(F.data == "menu:settings")
@router.callback_query(F.data == "set:root")
async def on_settings(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    async with SessionFactory() as session:
        user = await db.get_user(session, cb.from_user.id)
        lang = db.effective_language(user)
        notif = user.notifications_enabled
    await cb.message.edit_text(
        i18n.t(lang, "settings_title"),
        reply_markup=keyboards.settings_menu(lang, notif),
    )
    await cb.answer()


@router.callback_query(F.data == "set:tz")
async def on_tz(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    async with SessionFactory() as session:
        user = await db.get_user(session, cb.from_user.id)
        lang = db.effective_language(user)
    await cb.message.edit_text(
        i18n.t(lang, "tz_title"), reply_markup=keyboards.timezone_menu(lang)
    )
    await cb.answer()


@router.callback_query(F.data == "set:tz_other")
async def on_tz_other(cb: CallbackQuery, state: FSMContext) -> None:
    async with SessionFactory() as session:
        user = await db.get_user(session, cb.from_user.id)
        lang = db.effective_language(user)
    await state.set_state(TZFlow.waiting_city)
    await cb.message.edit_text(i18n.t(lang, "tz_prompt"))
    await cb.answer()


@router.callback_query(F.data.startswith("set:tz_set:"))
async def on_tz_set(cb: CallbackQuery, state: FSMContext) -> None:
    tz = cb.data.split(":", 3)[2]
    await state.clear()
    async with SessionFactory() as session:
        user = await db.get_user(session, cb.from_user.id)
        user.timezone = tz
        await session.commit()
        lang = db.effective_language(user)
        notif = user.notifications_enabled
    await cb.message.edit_text(
        i18n.t(lang, "tz_set", tz=tz), reply_markup=keyboards.settings_menu(lang, notif)
    )
    await cb.answer()


@router.message(TZFlow.waiting_city)
async def on_tz_city(message: Message, state: FSMContext) -> None:
    async with SessionFactory() as session:
        user = await db.get_user(session, message.from_user.id)
        lang = db.effective_language(user)
    tz = timezones.resolve_timezone(message.text or "")
    if tz is None:
        await message.answer(i18n.t(lang, "tz_not_found"))
        return
    async with SessionFactory() as session:
        user = await db.get_user(session, message.from_user.id)
        user.timezone = tz
        await session.commit()
        notif = user.notifications_enabled
    await state.clear()
    await message.answer(
        i18n.t(lang, "tz_set", tz=tz),
        reply_markup=keyboards.settings_menu(lang, notif),
    )


@router.callback_query(F.data == "set:notif_toggle")
async def on_notif_toggle(cb: CallbackQuery) -> None:
    async with SessionFactory() as session:
        user = await db.get_user(session, cb.from_user.id)
        user.notifications_enabled = not user.notifications_enabled
        await session.commit()
        lang = db.effective_language(user)
        notif = user.notifications_enabled
    await cb.message.edit_text(
        i18n.t(lang, "settings_title"),
        reply_markup=keyboards.settings_menu(lang, notif),
    )
    await cb.answer()


@router.callback_query(F.data == "set:lang")
async def on_lang(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    async with SessionFactory() as session:
        user = await db.get_user(session, cb.from_user.id)
        lang = db.effective_language(user)
        current = user.language
    await cb.message.edit_text(
        i18n.t(lang, "lang_title"), reply_markup=keyboards.language_menu(lang, current)
    )
    await cb.answer()


@router.callback_query(F.data.startswith("set:lang_set:"))
async def on_lang_set(cb: CallbackQuery, state: FSMContext) -> None:
    code = cb.data.split(":", 3)[2]
    async with SessionFactory() as session:
        user = await db.get_user(session, cb.from_user.id)
        user.language = code
        await session.commit()
        notif = user.notifications_enabled
    await cb.message.edit_text(
        i18n.t(code, "lang_set", name=i18n.LANGUAGES.get(code, code)),
        reply_markup=keyboards.settings_menu(code, notif),
    )
    await cb.answer()


# --- edit follow-ups (FSM) ---


@router.message(EditFlow.waiting_text)
async def on_waiting_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    rid = data.get("target_id")
    async with SessionFactory() as session:
        user = await db.get_user(session, message.from_user.id)
        lang = db.effective_language(user)
        r = await session.get(Reminder, rid)
        exists = r is not None and r.user_id == user.id
        if exists:
            r.text = message.text or ""
            await session.commit()
    await state.clear()
    if exists:
        await message.answer(
            i18n.t(lang, "updated"),
            reply_markup=keyboards.reminder_detail(lang, rid),
        )
    else:
        await message.answer(
            i18n.t(lang, "deleted"), reply_markup=keyboards.main_menu(lang)
        )


@router.message(EditFlow.waiting_time)
async def on_waiting_time(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    rid = data.get("target_id")
    async with SessionFactory() as session:
        user = await db.get_user(session, message.from_user.id)
        lang = db.effective_language(user)
        tz = user.timezone

    local_now = timezones.now_local(tz)
    parsed = await llm.parse_time(message.text or "", lang, tz, local_now)
    if parsed is None:
        await message.answer(i18n.t(lang, "ask_new_time"))
        return

    utc_when = timezones.to_utc(parsed, tz)
    async with SessionFactory() as session:
        r = await session.get(Reminder, rid)
        exists = r is not None
        if exists:
            r.remind_at = utc_when
            await session.commit()
    await state.clear()
    if exists:
        await message.answer(
            i18n.t(lang, "updated"), reply_markup=keyboards.reminder_detail(lang, rid)
        )
    else:
        await message.answer(
            i18n.t(lang, "deleted"), reply_markup=keyboards.main_menu(lang)
        )


# --- create follow-up: text given, time missing ---


@router.message(CreateFlow.waiting_time)
async def on_create_waiting_time(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    text = data.get("pending_text")
    recurrence = data.get("pending_recurrence", "none")
    async with SessionFactory() as session:
        user = await db.get_user(session, message.from_user.id)
        lang = db.effective_language(user)
        tz = user.timezone

    local_now = timezones.now_local(tz)
    parsed = await llm.parse_time(message.text or "", lang, tz, local_now)
    if parsed is None:
        await message.answer(i18n.t(lang, "ask_new_time"))
        return

    save_utc = timezones.to_utc(parsed, tz)
    async with SessionFactory() as session:
        session.add(Reminder(
            user_id=user.id, text=text, remind_at=save_utc,
            recurrence=recurrence,
        ))
        await session.commit()
    await state.clear()
    local = timezones.to_local(save_utc, tz)
    await message.answer(
        i18n.t(lang, "created", text=text, time=i18n.format_dt(local, lang, local_now))
        + i18n.tr_recurrence(lang, recurrence),
        reply_markup=keyboards.main_menu(lang),
    )


# --- free-form text -> LLM routing -----------------------------


@router.message(F.text)
async def on_text(message: Message, state: FSMContext) -> None:
    async with SessionFactory() as session:
        user = await db.get_user(session, message.from_user.id)
        tz = user.timezone
        constrained_lang = db.effective_language(user)
        existing = await db.list_active_reminders(session, user.id)
        existing_texts = [r.text for r in existing]

    local_now = timezones.now_local(tz)
    parsed = await llm.parse_message(
        message.text or "", constrained_lang, tz, local_now, existing_texts
    )
    detected_lang = parsed.language or constrained_lang
    lang = detected_lang

    # Track detected language for auto mode.
    if user.language == "auto":
        async with SessionFactory() as session:
            u = await db.get_user(session, message.from_user.id)
            u.last_lang = detected_lang
            await session.commit()

    # Create reminder.
    if parsed.intent in ("create_reminder", "create") and parsed.text:
        if parsed.when is None:
            await state.set_state(CreateFlow.waiting_time)
            await state.update_data(
                pending_text=parsed.text, pending_recurrence=parsed.recurrence or "none"
            )
            await message.answer(i18n.t(lang, "ask_new_time"))
            return
        save_utc = timezones.to_utc(parsed.when, tz)
        async with SessionFactory() as session:
            session.add(Reminder(
                user_id=user.id, text=parsed.text, remind_at=save_utc,
                recurrence=parsed.recurrence or "none",
            ))
            await session.commit()
        local = timezones.to_local(save_utc, tz)
        await message.answer(
            i18n.t(lang, "created", text=parsed.text,
                   time=i18n.format_dt(local, lang, local_now))
            + i18n.tr_recurrence(lang, parsed.recurrence),
            reply_markup=keyboards.main_menu(lang),
        )
        return

    # Delete with a matched reference.
    if parsed.intent == "delete" and parsed.reminder_ref:
        rid = _match_reminder(existing, parsed.reminder_ref)
        if rid is not None:
            async with SessionFactory() as session:
                r = await session.get(Reminder, rid)
                if r is not None:
                    await session.delete(r)
                    await session.commit()
            await message.answer(
                i18n.t(lang, "deleted"), reply_markup=keyboards.main_menu(lang)
            )
            return

    # List intent.
    if parsed.intent == "list":
        if not existing:
            await message.answer(
                f"{i18n.t(lang, 'reminders_title')}\n\n{i18n.t(lang, 'no_reminders')}",
                reply_markup=keyboards.empty_reminders_kb(lang),
            )
        else:
            lines = [fmt_reminder(r, lang, tz) for r in existing]
            await message.answer(
                "\n".join(lines), reply_markup=keyboards.main_menu(lang)
            )
        return

    # Settings / timezone -> open the right menu.
    if parsed.intent == "settings":
        await message.answer(
            i18n.t(lang, "settings_title"),
            reply_markup=keyboards.settings_menu(lang, user.notifications_enabled),
        )
        return
    if parsed.intent == "timezone":
        await message.answer(
            i18n.t(lang, "tz_title"), reply_markup=keyboards.timezone_menu(lang)
        )
        return

    # Default: LLM's chat reply, plus a visible language-switch offer (spec §6).
    reply = parsed.reply or i18n.t(lang, "menu")
    offer = _language_offer(detected_lang, user.language)
    if offer:
        question, kb = offer
        await message.answer(f"{reply}\n\n{question}", reply_markup=kb)
    else:
        await message.answer(reply)


def _language_offer(detected: str, current: str) -> tuple[str, InlineKeyboardMarkup] | None:
    """If the user wrote in a language different from a manually-pinned UI
    language, return a visible question + one-tap switch keyboard. In 'auto'
    mode the bot already follows, so no offer is needed."""
    if current == "auto":
        return None
    if detected == current or detected not in i18n.SUPPORTED:
        return None

    flag = i18n.FLAGS.get(detected, "")
    name = i18n.LANGUAGES.get(detected, detected)
    question = i18n.t(detected, "lang_offer", name=f"{flag} {name}")

    yes = InlineKeyboardButton(
        text=f"{flag} {i18n.t(detected, 'lang_yes')}",
        callback_data=f"set:lang_set:{detected}",
    )
    cur_flag = i18n.FLAGS.get(current, "")
    no = InlineKeyboardButton(
        text=f"{cur_flag} {i18n.t(detected, 'lang_no')}", callback_data="menu:root"
    )
    return question, InlineKeyboardMarkup(inline_keyboard=[[yes, no]])


# --- app bootstrap ---------------------------------------------


@router.errors()
async def on_unhandled_error(event) -> None:
    exc = getattr(event, "exception", None)
    logging.error(
        "Unhandled error while processing update: %s: %s",
        type(exc).__name__, exc,
        exc_info=exc,
    )


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    await db.init_db()
    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    scheduler_task = asyncio.create_task(run_scheduler(bot))
    try:
        await dp.start_polling(bot)
    finally:
        scheduler_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())