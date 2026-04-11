import os
import sys
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# --- Telegram ---
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID: str = os.getenv("TELEGRAM_CHANNEL_ID", "")
TELEGRAM_ADMIN_ID: str = os.getenv("TELEGRAM_ADMIN_ID", "")

# --- Anthropic ---
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL: str = "claude-haiku-4-5-20251001"

# --- Scheduler ---
SEND_TIME: str = os.getenv("SEND_TIME", "07:30")
SEND_TIME_EVENING: str = os.getenv("SEND_TIME_EVENING", "21:00")
TIMEZONE: str = os.getenv("TIMEZONE", "Europe/Madrid")

# --- History ---
HISTORY_FILE: str = os.getenv("HISTORY_FILE", "messages_history.json")
MAX_HISTORY_DAYS: int = 90
CONTEXT_MESSAGES: int = 30

# --- Persistence ---
PHRASES_FILE: str = os.getenv("PHRASES_FILE", "community_phrases.json")
STATE_FILE: str = os.getenv("STATE_FILE", "bot_state.json")

# --- ElevenLabs (optional, for voice messages) ---
ELEVENLABS_API_KEY: str = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID: str = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # Rachel

# --- Retry ---
MAX_RETRIES: int = 3
RETRY_BASE_DELAY: int = 2  # seconds; actual delay = RETRY_BASE_DELAY ** attempt


def _parse_time(value: str, name: str) -> tuple[int, int]:
    try:
        parts = value.split(":")
        hour, minute = int(parts[0]), int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("Out of range")
        return hour, minute
    except (ValueError, IndexError):
        logger.error(f"{name}='{value}' is invalid. Expected HH:MM (e.g. 07:30).")
        sys.exit(1)


def get_send_time() -> tuple[int, int]:
    """Parse SEND_TIME into (hour, minute)."""
    return _parse_time(SEND_TIME, "SEND_TIME")


def get_evening_send_time() -> tuple[int, int]:
    """Parse SEND_TIME_EVENING into (hour, minute)."""
    return _parse_time(SEND_TIME_EVENING, "SEND_TIME_EVENING")


def validate() -> None:
    """Check that all required env vars are set. Exits on missing vars."""
    required = {
        "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
        "TELEGRAM_CHANNEL_ID": TELEGRAM_CHANNEL_ID,
        "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        logger.error(
            f"Missing required environment variables: {', '.join(missing)}. "
            "Copy .env.example to .env and fill in the values."
        )
        sys.exit(1)

    get_send_time()  # also validates time format
    logger.info(
        f"Config OK — channel={TELEGRAM_CHANNEL_ID}, "
        f"send_time={SEND_TIME}, timezone={TIMEZONE}"
    )
