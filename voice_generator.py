"""
Optional voice message generation via ElevenLabs.
Active only when ELEVENLABS_API_KEY is set.
"""
import asyncio
import logging

import config

logger = logging.getLogger(__name__)


async def generate_voice(text: str) -> bytes | None:
    if not config.ELEVENLABS_API_KEY:
        logger.warning("ELEVENLABS_API_KEY not set — skipping voice generation.")
        return None

    logger.info(f"Generating voice audio ({len(text)} chars)…")

    try:
        from elevenlabs.client import ElevenLabs
    except ImportError:
        logger.error("elevenlabs package not installed. Add it to requirements.txt.")
        return None

    try:
        client = ElevenLabs(api_key=config.ELEVENLABS_API_KEY)

        def _sync_generate() -> bytes:
            # output_format omitted — uses ElevenLabs default (mp3_44100_128)
            # which works on all plans including free
            chunks = client.text_to_speech.convert(
                voice_id=config.ELEVENLABS_VOICE_ID,
                text=text,
                model_id="eleven_multilingual_v2",
            )
            data = b"".join(chunks)
            logger.info(f"Voice generated — {len(data):,} bytes.")
            return data

        return await asyncio.to_thread(_sync_generate)

    except Exception as exc:
        logger.error(f"ElevenLabs failed: {type(exc).__name__}: {exc}", exc_info=True)
        return None
