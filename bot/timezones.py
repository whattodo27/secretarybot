"""Time-zone helpers on top of the stdlib ``zoneinfo`` (IANA database)."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, available_timezones

# Popular cities -> IANA timezone. Shown as a quick-pick list in Settings.
POPULAR_CITIES: list[tuple[str, str]] = [
    ("Moscow", "Europe/Moscow"),
    ("Kyiv", "Europe/Kyiv"),
    ("Minsk", "Europe/Minsk"),
    ("Almaty", "Asia/Almaty"),
    ("Tashkent", "Asia/Tashkent"),
    ("Istanbul", "Europe/Istanbul"),
    ("London", "Europe/London"),
    ("Berlin", "Europe/Berlin"),
    ("Paris", "Europe/Paris"),
    ("Madrid", "Europe/Madrid"),
    ("Rome", "Europe/Rome"),
    ("Dubai", "Asia/Dubai"),
    ("Tokyo", "Asia/Tokyo"),
    ("Beijing", "Asia/Shanghai"),
    ("New York", "America/New_York"),
    ("Los Angeles", "America/Los_Angeles"),
    ("Sao Paulo", "America/Sao_Paulo"),
    ("Mexico City", "America/Mexico_City"),
]

_all_tz = None


def _all_timezones() -> set[str]:
    global _all_tz
    if _all_tz is None:
        _all_tz = available_timezones()
    return _all_tz


def is_valid_tz(name: str) -> bool:
    return name in _all_timezones()


def localize(naive: datetime, tz_name: str) -> datetime:
    """Attach a concrete timezone to a naive datetime (interpreted in tz_name)."""
    return naive.replace(tzinfo=ZoneInfo(tz_name))


def to_utc(naive: datetime, tz_name: str) -> datetime:
    """A naive datetime given in the user's local zone -> UTC."""
    return localize(naive, tz_name).astimezone(timezone.utc)


def to_local(utc_dt: datetime, tz_name: str) -> datetime:
    return utc_dt.astimezone(ZoneInfo(tz_name))


def now_local(tz_name: str) -> datetime:
    return datetime.now(ZoneInfo(tz_name))


def resolve_timezone(text: str) -> str | None:
    """Try to turn free text (city or IANA name) into a valid IANA timezone."""
    text = text.strip()
    if not text:
        return None
    if is_valid_tz(text):
        return text

    # Case-insensitive match of the trailing city part of an IANA name.
    needle = text.lower().replace(" ", "_")
    for tz in _all_timezones():
        if tz.lower().endswith("/" + needle):
            return tz

    # Substring match on the whole name (e.g. "london" -> Europe/London).
    matches = [tz for tz in _all_timezones() if needle in tz.lower()]
    if matches:
        return matches[0]
    return None