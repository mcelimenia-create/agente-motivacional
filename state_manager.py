"""
Simple key-value persistent state (JSON file).
Used to track milestones reached, last phrase date, etc.
"""
import json
import logging
from pathlib import Path

import config

logger = logging.getLogger(__name__)


def _load() -> dict:
    path = Path(config.STATE_FILE)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return {}


def _save(state: dict) -> None:
    try:
        Path(config.STATE_FILE).write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except IOError as exc:
        logger.error(f"Could not save state: {exc}")


def get(key: str, default=None):
    return _load().get(key, default)


def set(key: str, value) -> None:  # noqa: A001
    state = _load()
    state[key] = value
    _save(state)
