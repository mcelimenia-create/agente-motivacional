"""
Telegram Motivational Bot — main entry point.

Startup sequence:
  1. Validate config (exits on missing env vars).
  2. Build the Telegram Application.
  3. Register command handlers.
  4. post_init → start APScheduler.
  5. run_polling() → event loop lives here until SIGINT / SIGTERM.
  6. post_shutdown → stop scheduler gracefully.
"""
import asyncio
import logging
import logging.handlers
from pathlib import Path

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import NetworkError, RetryAfter, TelegramError, TimedOut
from telegram.ext import Application, CommandHandler, ContextTypes

import config
from history_manager import add_message, get_stats
from message_generator import generate_message
from scheduler import create_scheduler


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def _setup_logging() -> None:
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Console
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    # Rotating file (5 MB × 3 backups)
    log_file = logging.handlers.RotatingFileHandler(
        "bot.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    log_file.setFormatter(fmt)
    root.addHandler(log_file)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Telegram send helper with retry
# ---------------------------------------------------------------------------

async def _send_with_retry(
    bot,
    chat_id: str,
    text: str,
    parse_mode: str = ParseMode.MARKDOWN_V2,
) -> bool:
    """Send a message with exponential back-off on transient errors."""
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
            return True
        except RetryAfter as exc:
            logger.warning(f"Rate limited by Telegram — waiting {exc.retry_after}s…")
            await asyncio.sleep(exc.retry_after)
        except (NetworkError, TimedOut) as exc:
            delay = config.RETRY_BASE_DELAY ** attempt
            logger.error(
                f"Telegram network error (attempt {attempt}): {exc}. "
                f"Retrying in {delay}s…"
            )
            await asyncio.sleep(delay)
        except TelegramError as exc:
            logger.error(f"Telegram error (attempt {attempt}): {exc}")
            if attempt < config.MAX_RETRIES:
                await asyncio.sleep(config.RETRY_BASE_DELAY ** attempt)
    logger.error("All Telegram send retries exhausted.")
    return False


async def _notify_admin(application: Application, error_text: str) -> None:
    """DM the admin with an error notification (best-effort, no retry)."""
    if not config.TELEGRAM_ADMIN_ID:
        return
    try:
        await application.bot.send_message(
            chat_id=config.TELEGRAM_ADMIN_ID,
            text=f"⚠️ <b>Error en el bot motivacional</b>\n\n{error_text}",
            parse_mode=ParseMode.HTML,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Could not notify admin: {exc}")


# ---------------------------------------------------------------------------
# Core job — called by the scheduler every morning
# ---------------------------------------------------------------------------

async def send_daily_message(application: Application) -> None:
    """Generate a message, send it to the channel, and persist it."""
    logger.info("⏰ Sending daily motivational message…")
    try:
        message = await generate_message()
        success = await _send_with_retry(
            application.bot, config.TELEGRAM_CHANNEL_ID, message
        )
        if success:
            add_message(message)
            logger.info("✅ Daily message sent and saved.")
        else:
            await _notify_admin(
                application,
                "No se pudo enviar el mensaje motivacional diario al canal tras varios intentos.",
            )
    except Exception as exc:
        logger.error(f"Unhandled error in send_daily_message: {exc}", exc_info=True)
        await _notify_admin(application, f"Error inesperado al enviar el mensaje:\n{exc}")


# ---------------------------------------------------------------------------
# Bot command handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start — welcome message."""
    text = (
        "👋 <b>¡Hola! Soy tu bot motivacional diario.</b>\n\n"
        f"Cada mañana a las <b>{config.SEND_TIME}</b> ({config.TIMEZONE}) envío "
        "un mensaje inspirador al canal.\n\n"
        "<b>Comandos disponibles:</b>\n"
        "  /siguiente — previsualiza el próximo mensaje\n"
        "  /ahora — fuerza el envío ahora (solo admins)\n"
        "  /stats — estadísticas de envíos\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_siguiente(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/siguiente — preview the next message without sending it."""
    status = await update.message.reply_text("⏳ Generando vista previa…")
    try:
        message = await generate_message()
        await status.delete()
        await update.message.reply_text(
            f"👀 <b>Vista previa del próximo mensaje:</b>",
            parse_mode=ParseMode.HTML,
        )
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as exc:
        logger.error(f"/siguiente error: {exc}", exc_info=True)
        await status.edit_text("❌ No se pudo generar la vista previa. Inténtalo de nuevo.")


async def cmd_ahora(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/ahora — force-send a message immediately (admin only)."""
    user_id = str(update.effective_user.id)
    if not config.TELEGRAM_ADMIN_ID or user_id != config.TELEGRAM_ADMIN_ID:
        await update.message.reply_text("⛔ No tienes permisos para usar este comando.")
        return

    status = await update.message.reply_text("⏳ Generando y enviando mensaje…")
    try:
        message = await generate_message()
        success = await _send_with_retry(
            context.bot, config.TELEGRAM_CHANNEL_ID, message
        )
        if success:
            add_message(message)
            await status.edit_text("✅ Mensaje enviado al canal correctamente.")
        else:
            await status.edit_text("❌ No se pudo enviar el mensaje al canal.")
    except Exception as exc:
        logger.error(f"/ahora error: {exc}", exc_info=True)
        await status.edit_text(f"❌ Error inesperado: {exc}")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/stats — show sending statistics."""
    stats = get_stats()
    last = stats["last_sent"] or "Nunca"
    text = (
        "📊 <b>Estadísticas del bot</b>\n\n"
        f"📨 Total enviados: <b>{stats['total']}</b>\n"
        f"🔥 Racha actual: <b>{stats['streak']}</b> día(s)\n"
        f"🕐 Último envío: {last}\n"
        f"⏰ Próximo envío: <b>{config.SEND_TIME}</b> ({config.TIMEZONE})"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ---------------------------------------------------------------------------
# Application lifecycle hooks
# ---------------------------------------------------------------------------

async def post_init(application: Application) -> None:
    """Start APScheduler after the bot is initialised."""
    async def _job() -> None:
        await send_daily_message(application)

    scheduler = create_scheduler(_job)
    scheduler.start()
    application.bot_data["scheduler"] = scheduler
    logger.info(
        f"Scheduler started — daily message at {config.SEND_TIME} ({config.TIMEZONE})"
    )


async def post_shutdown(application: Application) -> None:
    """Stop the scheduler cleanly when the bot shuts down."""
    scheduler = application.bot_data.get("scheduler")
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped.")


# ---------------------------------------------------------------------------
# Health-check HTTP server (required by Railway and similar PaaS platforms)
# ---------------------------------------------------------------------------

def _start_health_server() -> None:
    """
    Bind a minimal HTTP server to $PORT so Railway's health check passes.
    Runs in a daemon thread — no new dependencies (uses stdlib http.server).
    """
    import os
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")

        def log_message(self, *args):  # suppress access logs
            pass

    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"Health-check server listening on :{port}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    _setup_logging()

    # Bind to $PORT immediately — Railway's health check starts as soon as the
    # container is up. If we validate config first and it fails (sys.exit),
    # the port never opens and Railway reports "service unavailable".
    _start_health_server()

    try:
        config.validate()
    except SystemExit:
        logger.critical(
            "Bot NOT started due to missing environment variables. "
            "Set them in Railway → Service → Variables and redeploy."
        )
        # Keep the process alive so Railway logs remain visible
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

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("siguiente", cmd_siguiente))
    application.add_handler(CommandHandler("ahora", cmd_ahora))
    application.add_handler(CommandHandler("stats", cmd_stats))

    logger.info("Bot is running. Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
