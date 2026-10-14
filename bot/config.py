"""Central configuration loaded from environment (.env)."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env if present (no-op if missing).
load_dotenv()


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


# --- Telegram ---
BOT_TOKEN: str = _get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")

# --- SQLite ---
DATA_DIR = Path(_get("DATA_DIR", "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / _get("DB_FILE", "bot.db")

# --- LLM (OpenAI-compatible). Works with OpenRouter / DeepSeek / OpenAI / etc. ---
LLM_BASE_URL: str = _get("LLM_BASE_URL", "https://openrouter.ai/api/v1")
LLM_API_KEY: str = _get("LLM_API_KEY", "")
LLM_MODEL: str = _get("LLM_MODEL", "deepseek/deepseek-chat")
LLM_TIMEOUT: float = float(_get("LLM_TIMEOUT", "30"))

# --- Scheduler ---
POLL_INTERVAL_SEC: float = float(_get("POLL_INTERVAL_SEC", "15"))
# A reminder is "upcoming" (vs "later") if it fires within this window.
UPCOMING_WINDOW_H: float = float(_get("UPCOMING_WINDOW_H", "24"))

# --- Defaults for new users ---
DEFAULT_LANGUAGE: str = "en"
DEFAULT_TIMEZONE: str = "UTC"