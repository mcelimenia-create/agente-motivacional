"""
Stores and retrieves community-submitted phrases.

File format (community_phrases.json):
[
  {
    "id": "abc123",
    "phrase": "La perseverancia es el camino al éxito.",
    "user_id": 12345678,
    "username": "marcos",
    "submitted_at": "2024-01-15T10:30:00",
    "used": false
  },
  ...
]
"""
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

import config

logger = logging.getLogger(__name__)


def _load() -> list[dict]:
    path = Path(config.PHRASES_FILE)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError) as exc:
        logger.error(f"Could not load phrases: {exc}")
        return []


def _save(phrases: list[dict]) -> None:
    try:
        Path(config.PHRASES_FILE).write_text(
            json.dumps(phrases, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except IOError as exc:
        logger.error(f"Could not save phrases: {exc}")


def save_phrase(user_id: int, username: str | None, phrase: str) -> None:
    """Store a community-submitted phrase."""
    phrases = _load()
    phrases.append({
        "id": str(uuid.uuid4())[:8],
        "phrase": phrase.strip(),
        "user_id": user_id,
        "username": username,
        "submitted_at": datetime.now().isoformat(),
        "used": False,
    })
    _save(phrases)
    logger.info(f"Phrase saved from user {user_id} (@{username})")


def get_random_unused() -> dict | None:
    """Return a random unused phrase, or None if none available."""
    import random
    phrases = _load()
    unused = [p for p in phrases if not p.get("used", False)]
    if not unused:
        return None
    return random.choice(unused)


def mark_used(phrase_id: str) -> None:
    """Mark a phrase as already published."""
    phrases = _load()
    for p in phrases:
        if p["id"] == phrase_id:
            p["used"] = True
            break
    _save(phrases)


def count_pending() -> int:
    """Return how many unused phrases are queued."""
    return sum(1 for p in _load() if not p.get("used", False))
