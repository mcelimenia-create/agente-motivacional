"""
Voice generation via ElevenLabs with emotional enhancement.

Model: eleven_multilingual_v2 (the most advanced multilingual model available)
Voice settings tuned for expressiveness and emotion:
  - stability=0.30   → voz más variable y expresiva (menos robótica)
  - similarity_boost=0.75 → fidelidad equilibrada a la voz original
  - style=0.65       → exageración de estilo para más emoción
  - use_speaker_boost=True → mejora de calidad de audio
"""
import asyncio
import logging

import config

logger = logging.getLogger(__name__)


async def generate_voice(text: str) -> bytes | None:
    """
    Convert plain text to MP3 audio using ElevenLabs v3.
    Returns None if ElevenLabs is not configured or the call fails.

    Parameters
    ----------
    text : str
        Plain text without MarkdownV2 markers.
        Use mdv2_to_plain() from message_generator before calling.
    """
    if not config.ELEVENLABS_API_KEY:
        logger.warning("ELEVENLABS_API_KEY not set — skipping voice generation.")
        return None

    logger.info(f"Generating voice audio with ElevenLabs v3 ({len(text)} chars)…")

    try:
        from elevenlabs import VoiceSettings
        from elevenlabs.client import ElevenLabs
    except ImportError:
        logger.error("elevenlabs package not installed. Add it to requirements.txt.")
        return None

    try:
        client = ElevenLabs(api_key=config.ELEVENLABS_API_KEY)

        def _sync_generate() -> bytes:
            chunks = client.text_to_speech.convert(
                voice_id=config.ELEVENLABS_VOICE_ID,
                text=text,
                model_id="eleven_multilingual_v2",
                voice_settings=VoiceSettings(
                    stability=0.30,        # más expresivo, menos monótono
                    similarity_boost=0.75, # fidelidad equilibrada
                    style=0.65,            # emoción y estilo amplificados
                    use_speaker_boost=True, # mejora calidad de audio
                ),
            )
            data = b"".join(chunks)
            logger.info(f"Voice generated — {len(data):,} bytes.")
            return data

        return await asyncio.to_thread(_sync_generate)

    except Exception as exc:
        logger.error(f"ElevenLabs v3 failed: {type(exc).__name__}: {exc}", exc_info=True)
        return None
