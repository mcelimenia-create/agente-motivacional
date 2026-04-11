"""
Optional voice message generation via ElevenLabs.

Only active when ELEVENLABS_API_KEY is set in the environment.
If the key is absent, all functions return None silently.

The output is MP3 bytes, sent via Telegram's send_audio (shows as audio player).
"""
import asyncio
import logging

import config

logger = logging.getLogger(__name__)


async def generate_voice(text: str) -> bytes | None:
    """
    Convert text to MP3 audio using ElevenLabs.

    Parameters
    ----------
    text : str
        Plain text (no MarkdownV2 markers). Use mdv2_to_plain() before calling.

    Returns
    -------
    bytes | None
        MP3 bytes, or None if ElevenLabs is not configured or the call fails.
    """
    if not config.ELEVENLABS_API_KEY:
        return None

    try:
        from elevenlabs.client import ElevenLabs

        client = ElevenLabs(api_key=config.ELEVENLABS_API_KEY)

        def _sync_generate() -> bytes:
            audio_chunks = client.text_to_speech.convert(
                voice_id=config.ELEVENLABS_VOICE_ID,
                text=text,
                model_id="eleven_multilingual_v2",
                output_format="mp3_44100_128",
            )
            return b"".join(audio_chunks)

        audio_bytes = await asyncio.to_thread(_sync_generate)
        logger.info(f"Voice generated — {len(audio_bytes)} bytes.")
        return audio_bytes

    except ImportError:
        logger.warning(
            "elevenlabs package not installed. "
            "Run: pip install elevenlabs  (or add to requirements.txt)"
        )
        return None
    except Exception as exc:
        logger.error(f"ElevenLabs error: {exc}", exc_info=True)
        return None
