"""
Manages the JSON file that stores every motivational message sent by the bot.

File format:
[
  {
    "message": "<full MarkdownV2 text>",
    "timestamp": "2024-01-15T07:30:00.123456"
  },
  ...
]
"""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import config

logger = logging.getLogger(__name__)


def _load() -> list[dict]:
    path = Path(config.HISTORY_FILE)
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as exc:
        logger.error(f"Could not load history from {path}: {exc}")
        return []


def _save(history: list[dict]) -> None:
    try:
        with open(config.HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except IOError as exc:
        logger.error(f"Could not save history to {config.HISTORY_FILE}: {exc}")


def add_message(message: str) -> None:
    """Append a sent message and prune entries older than MAX_HISTORY_DAYS."""
    history = _load()
    history.append({"message": message, "timestamp": datetime.now().isoformat()})

    cutoff = datetime.now() - timedelta(days=config.MAX_HISTORY_DAYS)
    history = [
        e for e in history
        if datetime.fromisoformat(e["timestamp"]) > cutoff
    ]
    _save(history)
    logger.debug(f"History saved — {len(history)} entries total.")


def get_recent_messages(n: int = config.CONTEXT_MESSAGES) -> list[str]:
    """Return the last *n* message texts (oldest first) for LLM context."""
    history = _load()
    return [e["message"] for e in history[-n:]]


def get_week_messages() -> list[str]:
    """Return messages sent in the last 7 days (oldest first)."""
    history = _load()
    cutoff = datetime.now() - timedelta(days=7)
    return [
        e["message"] for e in history
        if datetime.fromisoformat(e["timestamp"]) > cutoff
    ]


def get_stats() -> dict:
    """Return total messages sent, current streak (days), and last send time."""
    history = _load()
    if not history:
        return {"total": 0, "streak": 0, "last_sent": None}

    total = len(history)

    # Deduplicate dates (a message per day)
    sent_dates = sorted(
        {datetime.fromisoformat(e["timestamp"]).date() for e in history},
        reverse=True,
    )

    today = datetime.now().date()
    streak = 0
    if sent_dates and sent_dates[0] >= today - timedelta(days=1):
        streak = 1
        for i in range(1, len(sent_dates)):
            if sent_dates[i] == sent_dates[i - 1] - timedelta(days=1):
                streak += 1
            else:
                break

    last_sent = datetime.fromisoformat(history[-1]["timestamp"]).strftime(
        "%d/%m/%Y a las %H:%M"
    )
    return {"total": total, "streak": streak, "last_sent": last_sent}
