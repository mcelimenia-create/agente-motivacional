"""
Generates motivational messages in Spanish using the Anthropic API (Claude).

Output is formatted in Telegram MarkdownV2. The generator asks Claude to
return a structured JSON response so we can apply the correct formatting
(bold greeting, italic quote, plain body) programmatically — avoiding the
notorious MarkdownV2 escaping pitfalls when AI-generated text is involved.
"""
import asyncio
import json
import logging

import anthropic

import config
from history_manager import get_recent_messages

logger = logging.getLogger(__name__)

# Single reusable async client
_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


# ---------------------------------------------------------------------------
# MarkdownV2 helpers
# ---------------------------------------------------------------------------

def escape_mdv2(text: str) -> str:
    """
    Escape all MarkdownV2 special characters in *plain* text.

    Must be applied to the *content* of each field before embedding it
    inside formatting entities (e.g. *bold* or _italic_).
    Backslash is escaped first to prevent double-escaping.
    """
    text = text.replace("\\", "\\\\")
    for ch in r"_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text


def build_message(greeting: str, emoji: str, quote: str, body: str) -> str:
    """
    Assemble the final Telegram MarkdownV2 message from its components.

    Structure:
        *Greeting* EMOJI

        _"Quote"_

        Body text.
    """
    g = escape_mdv2(greeting)
    q = escape_mdv2(quote)
    b = escape_mdv2(body)
    # emoji: unicode, no escaping needed
    return f"*{g}* {emoji}\n\n_{q}_\n\n{b}"


# ---------------------------------------------------------------------------
# Fallback messages (pre-formatted MarkdownV2, used if all API retries fail)
# ---------------------------------------------------------------------------

_FALLBACKS: list[str] = [
    build_message(
        "¡Buenos días!",
        "☀️",
        "El éxito es la suma de pequeños esfuerzos repetidos día tras día.",
        "No hace falta dar un gran salto. Un paso firme cada mañana es suficiente para llegar lejos.",
    ),
    build_message(
        "¡Feliz inicio de día!",
        "🌟",
        "La disciplina es elegir entre lo que quieres ahora y lo que más quieres.",
        "Hoy tienes 24 horas nuevas. Úsalas con intención. ¿Cuál es la única cosa que, si la haces hoy, marcará la diferencia?",
    ),
    build_message(
        "Buenos días",
        "🔥",
        "No esperes la motivación perfecta — actúa, y la motivación te seguirá.",
        "El cuerpo sigue a la mente, y la mente sigue a la acción. Da el primer paso aunque sea pequeño.",
    ),
]
_fallback_index = 0


def _next_fallback() -> str:
    global _fallback_index
    msg = _FALLBACKS[_fallback_index % len(_FALLBACKS)]
    _fallback_index += 1
    return msg


# ---------------------------------------------------------------------------
# Core generation logic
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "Eres un coach motivacional experto en comunicación positiva en español. "
    "Generas mensajes inspiradores únicos, variados y auténticos para enviar "
    "por la mañana. Siempre respondes ÚNICAMENTE con el JSON solicitado, "
    "sin texto adicional, sin bloques de código."
)

_USER_PROMPT_TEMPLATE = """\
Genera UN mensaje motivacional de buenos días en español para un canal de Telegram.

Devuelve EXACTAMENTE este JSON y nada más:
{{
  "greeting": "saludo breve (ej: Buenos días, ¡Feliz lunes!, Despierta, etc.)",
  "emoji": "UN emoji relevante (☀️🌟💪🧠🌱🔥✨🎯💡🌊🦋🎶)",
  "quote": "cita inspiradora o reflexión original de 1-2 líneas",
  "body": "cuerpo del mensaje, 2-3 frases. Puede terminar con una pregunta reflexiva."
}}

REGLAS DE ESTILO:
- Varía el tono: reflexivo / energético / filosófico / práctico / con humor positivo
- Sin clichés trillados ("carpe diem", "sigue tus sueños" sin más profundidad)
- Longitud total del mensaje: 3-6 líneas
- Idioma: español (acepta lenguaje informal o formal según el tono)
- NO repitas temas de los mensajes recientes (listados abajo)

{history_section}

Devuelve ÚNICAMENTE el JSON. Sin markdown, sin explicaciones."""


async def generate_message() -> str:
    """
    Call the Anthropic API and return a fully formatted MarkdownV2 message.
    Retries up to MAX_RETRIES times with exponential back-off.
    Falls back to a pre-written message if all attempts fail.
    """
    recent = get_recent_messages()
    if recent:
        last_10 = recent[-10:]
        history_section = (
            "MENSAJES RECIENTES (no repitas temas similares):\n"
            + "\n---\n".join(last_10)
        )
    else:
        history_section = "(No hay mensajes previos — ¡empieza con algo especial!)"

    prompt = _USER_PROMPT_TEMPLATE.format(history_section=history_section)
    client = _get_client()

    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            logger.info(f"Calling Anthropic API (attempt {attempt}/{config.MAX_RETRIES})…")
            response = await client.messages.create(
                model=config.ANTHROPIC_MODEL,
                max_tokens=512,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            data = json.loads(raw)

            # Validate required fields
            for field in ("greeting", "emoji", "quote", "body"):
                if field not in data or not data[field]:
                    raise ValueError(f"Missing field '{field}' in API response")

            message = build_message(
                data["greeting"], data["emoji"], data["quote"], data["body"]
            )
            logger.info("Message generated successfully.")
            return message

        except json.JSONDecodeError as exc:
            logger.error(f"Claude returned non-JSON (attempt {attempt}): {exc}")
        except anthropic.APIStatusError as exc:
            logger.error(f"Anthropic API error {exc.status_code} (attempt {attempt}): {exc.message}")
        except anthropic.APIConnectionError as exc:
            logger.error(f"Anthropic connection error (attempt {attempt}): {exc}")
        except ValueError as exc:
            logger.error(f"Unexpected response structure (attempt {attempt}): {exc}")
        except Exception as exc:
            logger.error(f"Unexpected error (attempt {attempt}): {exc}", exc_info=True)

        if attempt < config.MAX_RETRIES:
            delay = config.RETRY_BASE_DELAY ** attempt
            logger.info(f"Retrying in {delay}s…")
            await asyncio.sleep(delay)

    logger.error("All Anthropic retries exhausted. Using fallback message.")
    return _next_fallback()
