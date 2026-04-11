"""
APScheduler configuration for the daily motivational message.

We use AsyncIOScheduler so it shares the event loop with
python-telegram-bot without threading conflicts.

Key behaviour:
  - misfire_grace_time=60 → if the scheduler restarts within 60 seconds
    of the scheduled time it will still fire. Any later restart waits for
    the next day (no duplicate messages on normal restarts).
  - coalesce=True → collapses multiple misfired triggers into a single run.
"""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

import config

logger = logging.getLogger(__name__)


def create_scheduler(job_func) -> AsyncIOScheduler:
    """
    Build and configure the scheduler.

    Parameters
    ----------
    job_func : async callable
        Zero-argument coroutine function that sends the daily message.

    Returns
    -------
    AsyncIOScheduler
        Configured but NOT yet started (call .start() separately).
    """
    hour, minute = config.get_send_time()

    scheduler = AsyncIOScheduler(timezone=config.TIMEZONE)
    scheduler.add_job(
        job_func,
        trigger=CronTrigger(
            hour=hour,
            minute=minute,
            timezone=config.TIMEZONE,
        ),
        id="daily_motivational_message",
        name=f"Daily message at {config.SEND_TIME} ({config.TIMEZONE})",
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=60,  # seconds
    )

    logger.info(
        f"Scheduler configured — next fire at {config.SEND_TIME} {config.TIMEZONE}"
    )
    return scheduler
