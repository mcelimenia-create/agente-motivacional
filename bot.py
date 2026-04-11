"""
Telegram Motivational Bot — main entry point.

Scheduled jobs:
  - Daily morning message (themed by day)           → SEND_TIME every day
  - Monday weekly challenge                          → SEND_TIME + 5 min, Mondays
  - Daily evening check-in + poll                   → SEND_TIME_EVENING every day
  - Saturday community phrase spotlight              → 12:00 Saturdays
  - Sunday weekly summary                            → 19:00 Sundays
  - Daily milestone check                            → 12:05 every day

Commands (via DM or group):
  /start      — welcome
  /siguiente  — preview tomorrow's message
  /ahora      — force-send now (admin only)
  /stats      — sending statistics
  /reflexion  — on-demand reflection on any topic
  /frase      — submit a phrase for the community spotlight
"""
import asyncio
import io
import logging
import logging.handlers
import os
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import Update
from telegram.constants import ParseMode
from telegram.error import NetworkError, RetryAfter, TelegramError, TimedOut
from telegram.ext import Application, CommandHandler, ContextTypes

import config
import state_manager
from history_manager import add_message, get_stats, get_week_messages
from message_generator import (
    generate_evening_checkin,
    generate_message,
    generate_milestone_message,
    generate_phrase_intro,
    generate_reflection,
    generate_weekly_challenge,
    generate_weekly_summary,
    mdv2_to_plain,
)
from phrase_collector import count_pending, get_random_unused, mark_used, save_phrase
from voice_generator import generate_voice

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _setup_logging() -> None:
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    log_path = os.environ.get("LOG_FILE", "")
    if log_path:
        fh = logging.handlers.RotatingFileHandler(
            log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        root.addHandler(fh)


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Evening polls (one per day of week, 0=Monday)
# ---------------------------------------------------------------------------
EVENING_POLLS = [
    ("¿Cómo arrancó tu lunes?",
     ["🔥 Con todo", "😐 Normal", "😴 Necesito más energía"]),
    ("¿Cumpliste tus prioridades del martes?",
     ["✅ Todas", "🤏 La mayoría", "🔄 Mañana las recupero"]),
    ("Mitad de semana — ¿cómo vas?",
     ["💪 Mejor de lo esperado", "😐 Más o menos", "😓 Ha sido duro"]),
    ("¿Qué tal el jueves?",
     ["🎯 Muy productivo", "⚡ Bien, podría ser mejor", "😴 Ya quiero el fin de semana"]),
    ("¿Cómo fue tu semana?",
     ["🏆 Semana épica", "👍 Bien en general", "💪 La próxima mejor"]),
    ("¿Desconectaste bien hoy?",
     ["🌴 Totalmente", "🤏 Un poco", "💻 No del todo..."]),
    ("¿Te sientes listo para la semana?",
     ["🚀 ¡Completamente!", "😐 Más o menos", "😅 Necesito más domingo"]),
]

MILESTONES = [100, 250, 500, 1_000, 2_500, 5_000, 10_000, 25_000, 50_000, 100_000]

# ---------------------------------------------------------------------------
# Telegram send helpers
# ---------------------------------------------------------------------------

async def _send_with_retry(
    bot, chat_id: str, text: str, parse_mode: str = ParseMode.MARKDOWN_V2
) -> bool:
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
            return True
        except RetryAfter as exc:
            logger.warning(f"Rate limited — waiting {exc.retry_after}s…")
            await asyncio.sleep(exc.retry_after)
        except (NetworkError, TimedOut) as exc:
            delay = config.RETRY_BASE_DELAY ** attempt
            logger.error(f"Network error (attempt {attempt}): {exc}. Retry in {delay}s…")
            await asyncio.sleep(delay)
        except TelegramError as exc:
            logger.error(f"Telegram error (attempt {attempt}): {exc}")
            if attempt < config.MAX_RETRIES:
                await asyncio.sleep(config.RETRY_BASE_DELAY ** attempt)
    return False


async def _notify_admin(application: Application, text: str) -> None:
    if not config.TELEGRAM_ADMIN_ID:
        return
    try:
        await application.bot.send_message(
            chat_id=config.TELEGRAM_ADMIN_ID,
            text=f"⚠️ <b>Error en el bot</b>\n\n{text}",
            parse_mode=ParseMode.HTML,
        )
    except Exception as exc:
        logger.error(f"Could not notify admin: {exc}")


# ---------------------------------------------------------------------------
# Voice helper
# ---------------------------------------------------------------------------

async def _send_voice_if_enabled(bot, message_mdv2: str) -> None:
    """Generate and send audio to the channel if ElevenLabs is configured."""
    if not config.ELEVENLABS_API_KEY:
        return
    logger.info("ElevenLabs key found — requesting audio…")
    audio = await generate_voice(mdv2_to_plain(message_mdv2))
    if audio:
        logger.info(f"Sending audio to channel ({len(audio):,} bytes)…")
        try:
            await bot.send_audio(
                chat_id=config.TELEGRAM_CHANNEL_ID,
                audio=io.BytesIO(audio),
                filename="motivacion.mp3",
                title="Mensaje del día 🎧",
            )
            logger.info("✅ Audio sent.")
        except TelegramError as exc:
            logger.error(f"Failed to send audio: {exc}")
    else:
        logger.warning("Audio generation returned None — no audio sent.")


# ---------------------------------------------------------------------------
# Scheduled job functions
# ---------------------------------------------------------------------------

async def send_daily_message(application: Application) -> None:
    """Morning message — themed by day of week."""
    logger.info("⏰ Sending morning message…")
    try:
        day = datetime.now().weekday()
        message = await generate_message(day)
        success = await _send_with_retry(application.bot, config.TELEGRAM_CHANNEL_ID, message)
        if success:
            add_message(message)
            logger.info("✅ Morning message sent.")
            await _send_voice_if_enabled(application.bot, message)
        else:
            await _notify_admin(application, "No se pudo enviar el mensaje matutino.")
    except Exception as exc:
        logger.error(f"send_daily_message error: {exc}", exc_info=True)
        await _notify_admin(application, f"Error en mensaje matutino: {exc}")


async def send_weekly_challenge(application: Application) -> None:
    """Monday: send the weekly challenge after the morning message."""
    logger.info("🎯 Sending weekly challenge…")
    try:
        message = await generate_weekly_challenge()
        await _send_with_retry(application.bot, config.TELEGRAM_CHANNEL_ID, message)
        logger.info("✅ Weekly challenge sent.")
    except Exception as exc:
        logger.error(f"send_weekly_challenge error: {exc}", exc_info=True)


async def send_evening_checkin(application: Application) -> None:
    """Evening: send reflection message + daily poll."""
    logger.info("🌙 Sending evening check-in…")
    try:
        message = await generate_evening_checkin()
        await _send_with_retry(application.bot, config.TELEGRAM_CHANNEL_ID, message)

        # Send daily poll
        day = datetime.now().weekday()
        question, options = EVENING_POLLS[day]
        await application.bot.send_poll(
            chat_id=config.TELEGRAM_CHANNEL_ID,
            question=question,
            options=options,
            is_anonymous=True,
        )
        logger.info("✅ Evening check-in + poll sent.")
    except Exception as exc:
        logger.error(f"send_evening_checkin error: {exc}", exc_info=True)


async def send_community_phrase(application: Application) -> None:
    """Saturday: publish a community-submitted phrase."""
    logger.info("💬 Sending community phrase…")
    try:
        phrase_data = get_random_unused()
        if not phrase_data:
            logger.info("No pending community phrases — skipping Saturday spotlight.")
            return
        message = await generate_phrase_intro(phrase_data["phrase"], phrase_data.get("username"))
        success = await _send_with_retry(application.bot, config.TELEGRAM_CHANNEL_ID, message)
        if success:
            mark_used(phrase_data["id"])
            logger.info(f"✅ Community phrase published (id={phrase_data['id']}).")
    except Exception as exc:
        logger.error(f"send_community_phrase error: {exc}", exc_info=True)


async def send_weekly_summary(application: Application) -> None:
    """Sunday: send a reflection summary of the week."""
    logger.info("📅 Sending weekly summary…")
    try:
        week_msgs = get_week_messages()
        message = await generate_weekly_summary(week_msgs)
        await _send_with_retry(application.bot, config.TELEGRAM_CHANNEL_ID, message)
        logger.info("✅ Weekly summary sent.")
    except Exception as exc:
        logger.error(f"send_weekly_summary error: {exc}", exc_info=True)


async def check_milestone(application: Application) -> None:
    """Daily: check if the channel crossed a follower milestone."""
    try:
        count = await application.bot.get_chat_member_count(config.TELEGRAM_CHANNEL_ID)
        last = state_manager.get("last_milestone", 0)
        next_ms = next((m for m in MILESTONES if m > last), None)
        if next_ms and count >= next_ms:
            logger.info(f"🎉 Milestone reached: {next_ms} members!")
            message = await generate_milestone_message(next_ms)
            success = await _send_with_retry(
                application.bot, config.TELEGRAM_CHANNEL_ID, message
            )
            if success:
                state_manager.set("last_milestone", next_ms)
    except Exception as exc:
        logger.error(f"check_milestone error: {exc}", exc_info=True)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "👋 <b>¡Hola! Soy tu bot motivacional diario.</b>\n\n"
        f"Cada mañana a las <b>{config.SEND_TIME}</b> envío un mensaje inspirador al canal.\n"
        f"Por la noche a las <b>{config.SEND_TIME_EVENING}</b> te invito a reflexionar sobre el día.\n\n"
        "<b>Comandos:</b>\n"
        "  /siguiente — previsualiza el próximo mensaje\n"
        "  /reflexion [tema] — reflexión sobre cualquier tema\n"
        "  /frase [tu frase] — envía tu frase a la comunidad\n"
        "  /ahora — fuerza el envío ahora (solo admins)\n"
        "  /stats — estadísticas\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_siguiente(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    status = await update.message.reply_text("⏳ Generando vista previa…")
    try:
        message = await generate_message()
        await status.delete()
        await update.message.reply_text("👀 <b>Vista previa:</b>", parse_mode=ParseMode.HTML)
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as exc:
        logger.error(f"/siguiente error: {exc}", exc_info=True)
        await status.edit_text("❌ Error al generar la vista previa. Inténtalo de nuevo.")


async def cmd_ahora(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not config.TELEGRAM_ADMIN_ID or str(update.effective_user.id) != config.TELEGRAM_ADMIN_ID:
        await update.message.reply_text("⛔ No tienes permisos para usar este comando.")
        return
    status = await update.message.reply_text("⏳ Generando y enviando mensaje…")
    try:
        message = await generate_message()
        success = await _send_with_retry(context.bot, config.TELEGRAM_CHANNEL_ID, message)
        if success:
            add_message(message)
            await status.edit_text("✅ Mensaje enviado al canal. Generando audio…")
            await _send_voice_if_enabled(context.bot, message)
            await status.edit_text("✅ Mensaje (y audio si ElevenLabs está activo) enviados.")
        else:
            await status.edit_text("❌ No se pudo enviar el mensaje.")
    except Exception as exc:
        logger.error(f"/ahora error: {exc}", exc_info=True)
        await status.edit_text(f"❌ Error inesperado: {exc}")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    stats = get_stats()
    pending = count_pending()
    text = (
        "📊 <b>Estadísticas del bot</b>\n\n"
        f"📨 Total enviados: <b>{stats['total']}</b>\n"
        f"🔥 Racha actual: <b>{stats['streak']}</b> día(s)\n"
        f"🕐 Último envío: {stats['last_sent'] or 'Nunca'}\n"
        f"💬 Frases en cola: <b>{pending}</b>\n"
        f"⏰ Mañana: <b>{config.SEND_TIME}</b> | Noche: <b>{config.SEND_TIME_EVENING}</b> ({config.TIMEZONE})"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_reflexion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    topic = " ".join(context.args).strip() if context.args else ""
    if not topic:
        await update.message.reply_text(
            "Dime sobre qué quieres reflexionar.\n"
            "Ejemplo: <code>/reflexion ansiedad</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    status = await update.message.reply_text(f"⏳ Reflexionando sobre <i>{topic}</i>…", parse_mode=ParseMode.HTML)
    try:
        message = await generate_reflection(topic)
        await status.delete()
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as exc:
        logger.error(f"/reflexion error: {exc}", exc_info=True)
        await status.edit_text("❌ No pude generar la reflexión. Inténtalo de nuevo.")


async def cmd_frase(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    phrase = " ".join(context.args).strip() if context.args else ""
    if not phrase:
        await update.message.reply_text(
            "Envía tu frase así:\n<code>/frase La perseverancia es el camino al éxito.</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    if len(phrase) > 280:
        await update.message.reply_text("⚠️ La frase es demasiado larga (máx. 280 caracteres).")
        return
    user = update.effective_user
    save_phrase(user.id, user.username, phrase)
    await update.message.reply_text(
        "✅ <b>¡Gracias!</b> Tu frase ha sido recibida y podría aparecer en el canal el próximo sábado 💬",
        parse_mode=ParseMode.HTML,
    )


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

async def post_init(application: Application) -> None:
    morning_h, morning_m = config.get_send_time()
    evening_h, evening_m = config.get_evening_send_time()

    # Monday challenge fires 5 minutes after the morning message
    ch_m = morning_m + 5
    ch_h = morning_h + ch_m // 60
    ch_m = ch_m % 60

    scheduler = AsyncIOScheduler(timezone=config.TIMEZONE)

    async def _morning():
        await send_daily_message(application)

    async def _challenge():
        await send_weekly_challenge(application)

    async def _evening():
        await send_evening_checkin(application)

    async def _phrase():
        await send_community_phrase(application)

    async def _summary():
        await send_weekly_summary(application)

    async def _milestone():
        await check_milestone(application)

    scheduler.add_job(_morning,   CronTrigger(hour=morning_h, minute=morning_m, timezone=config.TIMEZONE),
                      id="morning",    replace_existing=True, coalesce=True, misfire_grace_time=60)
    scheduler.add_job(_challenge, CronTrigger(day_of_week="mon", hour=ch_h, minute=ch_m, timezone=config.TIMEZONE),
                      id="challenge",  replace_existing=True, coalesce=True, misfire_grace_time=60)
    scheduler.add_job(_evening,   CronTrigger(hour=evening_h, minute=evening_m, timezone=config.TIMEZONE),
                      id="evening",    replace_existing=True, coalesce=True, misfire_grace_time=60)
    scheduler.add_job(_phrase,    CronTrigger(day_of_week="sat", hour=12, minute=0, timezone=config.TIMEZONE),
                      id="phrase",     replace_existing=True, coalesce=True, misfire_grace_time=60)
    scheduler.add_job(_summary,   CronTrigger(day_of_week="sun", hour=19, minute=0, timezone=config.TIMEZONE),
                      id="summary",    replace_existing=True, coalesce=True, misfire_grace_time=60)
    scheduler.add_job(_milestone, CronTrigger(hour=12, minute=5, timezone=config.TIMEZONE),
                      id="milestone",  replace_existing=True, coalesce=True, misfire_grace_time=60)

    scheduler.start()
    application.bot_data["scheduler"] = scheduler
    logger.info(
        f"Scheduler started — morning={morning_h:02d}:{morning_m:02d}, "
        f"evening={evening_h:02d}:{evening_m:02d} ({config.TIMEZONE})"
    )


async def post_shutdown(application: Application) -> None:
    scheduler = application.bot_data.get("scheduler")
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped.")


# ---------------------------------------------------------------------------
# Health-check server (required by Railway)
# ---------------------------------------------------------------------------

def _start_health_server() -> None:
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import threading

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")

        def log_message(self, *args):
            pass

    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    logger.info(f"Health-check server listening on :{port}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    _setup_logging()
    _start_health_server()

    try:
        config.validate()
    except SystemExit:
        logger.critical(
            "Bot NOT started — missing environment variables. "
            "Set them in Railway → Variables and redeploy."
        )
        import time
        while True:
            time.sleep(3600)

    logger.info("Starting Telegram Motivational Bot…")

    application = (
        Application.builder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    application.add_handler(CommandHandler("start",     cmd_start))
    application.add_handler(CommandHandler("siguiente", cmd_siguiente))
    application.add_handler(CommandHandler("ahora",     cmd_ahora))
    application.add_handler(CommandHandler("stats",     cmd_stats))
    application.add_handler(CommandHandler("reflexion", cmd_reflexion))
    application.add_handler(CommandHandler("frase",     cmd_frase))

    logger.info("Bot is running. Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
