"""LLM client (OpenAI-compatible) + natural-language parsing.

The model is asked to return a single JSON object describing the user's intent,
the language they wrote in, and the structured reminder to save. This is what
makes the bot "understand plain speech" — no commands to learn.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime

from openai import AsyncOpenAI

from . import config

client: AsyncOpenAI | None = None
if config.LLM_API_KEY:
    client = AsyncOpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY)


@dataclass
class ParsedMessage:
    intent: str = "chat"  # create_reminder | list | delete | edit | settings | timezone | language | chat
    language: str = "en"
    reply: str = ""
    text: str | None = None          # reminder text
    when: datetime | None = None     # naive datetime in the USER's local zone
    recurrence: str = "none"         # none | daily | weekly | monthly
    reminder_ref: str | None = None  # for edit/delete: which existing reminder


def _extract_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Fall back to the first balanced {...} block.
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            pass
    return {}


def _safe_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip().replace("Z", "")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


_SYSTEM = (
    "You are the brain of a personal-secretary Telegram reminder bot. "
    "You parse the user's message and decide what to do. "
    "Always answer with a single JSON object and nothing else.\n\n"
    "Fields:\n"
    "- \"intent\": one of \"create_reminder\", \"list\", \"delete\", \"edit\", "
    "\"settings\", \"timezone\", \"language\", \"chat\".\n"
    "- \"language\": ISO 639-1 code the user wrote in (\"en\",\"ru\",\"es\",\"de\",\"fr\",\"pt\",\"tr\").\n"
    "- \"reply\": a short friendly reply (1-2 sentences) in the user's language.\n"
    "- \"text\": for create/edit, the reminder content in the user's language (omit otherwise).\n"
    "- \"when\": for create/edit, the date+time as ISO 8601 WITHOUT timezone, "
    "interpreted in the user's local timezone, e.g. \"2026-10-15T10:00:00\". "
    "Omit if no time is specified.\n"
    "- \"recurrence\": \"none\", \"daily\", \"weekly\" or \"monthly\" (detect phrases like "
    "\"every day\", \"every Monday\", \"every month\").\n"
    "- \"reminder_ref\": for edit/delete, a short string identifying WHICH existing "
    "reminder the user means (match against the list below), or null.\n\n"
    "Intent rules: a request to set/remind/schedule something -> create_reminder; "
    "asking to see reminders -> list; delete/remove -> delete; change/edit -> edit; "
    "plain chat -> chat with a secretary-style reply.\n"
    "Be precise with time: \"tomorrow at 10\" = tomorrow in local time; "
    "\"in 2 hours\" = now + 2h; map \"at 10 pm\" to 22:00."
)


def _build_messages(user_text: str, lang: str, tz: str, now: datetime,
                    existing: list[str], extra_prompt: str = "") -> list[dict]:
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%S")
    meta = (
        f"The user's current interface language is {lang!r}, their timezone is {tz!r}, "
        f"and their current local time is {now_iso}.\n"
    )
    if existing:
        meta += "Existing active reminders:\n" + "\n".join(
            f"- id={i}: {s}" for i, s in enumerate(existing)
        ) + "\n"
    else:
        meta += "The user has no existing reminders.\n"
    if extra_prompt:
        meta += extra_prompt + "\n"
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": meta + "\nUser message: " + user_text},
    ]


async def parse_message(user_text: str, lang: str, tz: str, now: datetime,
                        existing: list[str]) -> ParsedMessage:
    """Route a free-text message into an intent + structured reminder."""
    result = ParsedMessage()
    if client is None:
        result.reply = "LLM is not configured (set LLM_API_KEY)."
        return result

    messages = _build_messages(user_text, lang, tz, now, existing)
    resp = await client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=messages,
        temperature=0.2,
        timeout=config.LLM_TIMEOUT,
    )
    raw = resp.choices[0].message.content or "{}"
    data = _extract_json(raw)

    result.intent = str(data.get("intent", "chat"))
    result.language = str(data.get("language", lang or "en"))
    if result.language not in {"en", "ru", "es", "de", "fr", "pt", "tr"}:
        result.language = lang or "en"
    result.reply = str(data.get("reply", "") or "")
    result.text = data.get("text") or None
    result.when = _safe_dt(data.get("when"))
    result.recurrence = str(data.get("recurrence", "none") or "none")
    result.reminder_ref = data.get("reminder_ref") or None
    return result


async def parse_time(user_text: str, lang: str, tz: str, now: datetime) -> datetime | None:
    """Extract only a date/time, used for editing time / follow-up 'when?'."""
    if client is None:
        return None
    extra = (
        "The user is only giving a time for a reminder. "
        "Return JSON with the single field \"when\" (ISO 8601, no timezone, local time)."
    )
    messages = _build_messages(user_text, lang, tz, now, [], extra_prompt=extra)
    resp = await client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=messages,
        temperature=0.1,
        timeout=config.LLM_TIMEOUT,
    )
    data = _extract_json(resp.choices[0].message.content or "{}")
    return _safe_dt(data.get("when"))