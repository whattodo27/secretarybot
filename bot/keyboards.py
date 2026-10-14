"""Inline/reply keyboards (localized by user language)."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from . import db, i18n
from .db import Reminder


def main_menu(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=i18n.t(lang, "main_reminders"), callback_data="menu:reminders")],
        [InlineKeyboardButton(text=i18n.t(lang, "main_settings"), callback_data="menu:settings")],
    ])


def reminders_list(lang: str, reminders: list[Reminder], page: int = 0,
                   per_page: int = 8) -> tuple[InlineKeyboardMarkup, int]:
    """List of reminders; pagination via a 'Show more' button."""
    start = page * per_page
    chunk = reminders[start : start + per_page]
    total_pages = (len(reminders) + per_page - 1) // per_page

    keys: list[list[InlineKeyboardButton]] = []
    for r in chunk:
        keys.append([
            InlineKeyboardButton(
                text=f"• {r.text[:40]}", callback_data=f"rem:view:{r.id}"
            )
        ])

    nav: list[InlineKeyboardButton] = []
    if (page + 1) < total_pages:
        nav.append(InlineKeyboardButton(
            text=i18n.t(lang, "show_more"), callback_data=f"list:page:{page + 1}"
        ))
    if nav:
        keys.append(nav)

    keys.append([
        InlineKeyboardButton(text=i18n.t(lang, "manage"), callback_data="rem:manage"),
    ])
    keys.append([
        InlineKeyboardButton(text=i18n.t(lang, "back_menu"), callback_data="menu:root"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=keys), len(chunk)


def reminder_detail(lang: str, reminder_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=i18n.t(lang, "edit_text"), callback_data=f"rem:edit_text:{reminder_id}"),
            InlineKeyboardButton(text=i18n.t(lang, "edit_time"), callback_data=f"rem:edit_time:{reminder_id}"),
        ],
        [InlineKeyboardButton(text=i18n.t(lang, "delete"), callback_data=f"rem:delete:{reminder_id}")],
        [InlineKeyboardButton(text=i18n.t(lang, "back_list"), callback_data="rem:list")],
    ])


def confirm_delete(lang: str, reminder_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=i18n.t(lang, "yes_delete"), callback_data=f"rem:delete_yes:{reminder_id}"),
            InlineKeyboardButton(text=i18n.t(lang, "cancel"), callback_data=f"rem:view:{reminder_id}"),
        ],
    ])


def manage_menu(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=i18n.t(lang, "clear_all"), callback_data="rem:clear_all")],
        [InlineKeyboardButton(text=i18n.t(lang, "stats_title"), callback_data="rem:stats")],
        [InlineKeyboardButton(text=i18n.t(lang, "back_menu"), callback_data="menu:root")],
    ])


def confirm_clear_all(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=i18n.t(lang, "yes_clear_all"), callback_data="rem:clear_all_yes"),
            InlineKeyboardButton(text=i18n.t(lang, "cancel"), callback_data="rem:manage"),
        ],
    ])


def settings_menu(lang: str, notifications_enabled: bool) -> InlineKeyboardMarkup:
    notif_label = (
        i18n.t(lang, "notif_on") if notifications_enabled else i18n.t(lang, "notif_off")
    )
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=i18n.t(lang, "tz"), callback_data="set:tz")],
        [InlineKeyboardButton(text=notif_label, callback_data="set:notif_toggle")],
        [InlineKeyboardButton(text=i18n.t(lang, "lang"), callback_data="set:lang")],
        [InlineKeyboardButton(text=i18n.t(lang, "back_menu"), callback_data="menu:root")],
    ])


def timezone_menu(lang: str) -> InlineKeyboardMarkup:
    from .timezones import POPULAR_CITIES
    keys = [
        [InlineKeyboardButton(text=city, callback_data=f"set:tz_set:{tz}")]
        for city, tz in POPULAR_CITIES
    ]
    keys.append([
        InlineKeyboardButton(text=i18n.t(lang, "tz_other"), callback_data="set:tz_other")
    ])
    keys.append([
        InlineKeyboardButton(text=i18n.t(lang, "back"), callback_data="set:root")
    ])
    return InlineKeyboardMarkup(inline_keyboard=keys)


def language_menu(lang: str, current: str) -> InlineKeyboardMarkup:
    keys: list[list[InlineKeyboardButton]] = []
    auto_label = i18n.t(lang, "lang_auto")
    if current == "auto":
        auto_label = "✅ " + auto_label
    keys.append([InlineKeyboardButton(text=auto_label, callback_data="set:lang_set:auto")])
    for code, name in i18n.LANGUAGES.items():
        flag = i18n.FLAGS.get(code, "")
        label = f"{name} {flag}" if code != current else f"✅ {name} {flag}"
        keys.append([
            InlineKeyboardButton(text=label, callback_data=f"set:lang_set:{code}")
        ])
    keys.append([
        InlineKeyboardButton(text=i18n.t(lang, "back"), callback_data="set:root")
    ])
    return InlineKeyboardMarkup(inline_keyboard=keys)


def empty_reminders_kb(lang: str) -> InlineKeyboardMarkup:
    """Shown when the reminders list is empty: a single 'back to main menu' button."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=i18n.t(lang, "back_menu"), callback_data="menu:root")],
    ])