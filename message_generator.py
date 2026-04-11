"""
All Claude-powered content generation for the motivational bot.

Each generator returns a fully formatted Telegram MarkdownV2 string
(or plain text where indicated). The JSON-structured prompting approach
lets us apply formatting programmatically, avoiding MarkdownV2 escaping bugs.
"""
import asyncio
import json
import logging
import re
from datetime import datetime

import anthropic

import config
from history_manager import get_recent_messages, get_week_messages

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Day-of-week themes (0 = Monday … 6 = Sunday)
# ---------------------------------------------------------------------------
DAY_THEMES = {
    0: ("lunes",     "energía, arranque fuerte, productividad, motivación para empezar la semana"),
    1: ("martes",    "constancia, construir hábitos, mantener el ritmo sin perder energía"),
    2: ("miércoles", "mentalidad, superar obstáculos, punto medio de la semana"),
    3: ("jueves",    "acción, ejecutar sin procrastinar, foco total"),
    4: ("viernes",   "reflexión, gratitud, celebrar los logros de la semana"),
    5: ("sábado",    "descanso activo, bienestar, recarga, familia y hobbies"),
    6: ("domingo",   "intención, preparación mental, tranquilidad antes de la semana"),
}

# ---------------------------------------------------------------------------
# MarkdownV2 helpers
# ---------------------------------------------------------------------------

def escape_mdv2(text: str) -> str:
    """Escape all MarkdownV2 special chars in plain content."""
    text = text.replace("\\", "\\\\")
    for ch in r"_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text


def build_message(greeting: str, emoji: str, quote: str, body: str) -> str:
    """Assemble a MarkdownV2-formatted motivational message."""
    return f"*{escape_mdv2(greeting)}* {emoji}\n\n_{escape_mdv2(quote)}_\n\n{escape_mdv2(body)}"


def mdv2_to_plain(text: str) -> str:
    """Strip MarkdownV2 formatting — used for voice generation prompts."""
    text = re.sub(r"\\(.)", r"\1", text)   # unescape \. \! etc.
    text = re.sub(r"[*_~`]", "", text)     # remove bold/italic markers
    return text.strip()


# ---------------------------------------------------------------------------
# Fallback messages (pre-built, used when all API retries fail)
# ---------------------------------------------------------------------------
_FALLBACKS = [
    build_message("¡Buenos días!", "☀️",
                  "El éxito es la suma de pequeños esfuerzos repetidos día tras día.",
                  "No hace falta un gran salto. Un paso firme cada mañana es suficiente para llegar lejos."),
    build_message("¡Feliz inicio de día!", "🌟",
                  "La disciplina es elegir entre lo que quieres ahora y lo que más quieres.",
                  "Hoy tienes 24 horas nuevas. Úsalas con intención. ¿Cuál es la única cosa que, si la haces hoy, marcará la diferencia?"),
    build_message("Buenos días", "🔥",
                  "No esperes la motivación perfecta — actúa, y la motivación te seguirá.",
                  "El cuerpo sigue a la mente, y la mente sigue a la acción. Da el primer paso aunque sea pequeño."),
]
_fallback_idx = 0

def _next_fallback() -> str:
    global _fallback_idx
    msg = _FALLBACKS[_fallback_idx % len(_FALLBACKS)]
    _fallback_idx += 1
    return msg

# ---------------------------------------------------------------------------
# Anthropic client (lazy singleton)
# ---------------------------------------------------------------------------
_client: anthropic.AsyncAnthropic | None = None

def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client

# ---------------------------------------------------------------------------
# Generic Claude caller
# ---------------------------------------------------------------------------

async def _call_claude(prompt: str, system: str, max_tokens: int = 600) -> str:
    """Call Claude and return raw text. Raises on failure."""
    response = await _get_client().messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


async def _call_with_retry(prompt: str, system: str, max_tokens: int = 600) -> str | None:
    """Call Claude with exponential back-off. Returns None if all retries fail."""
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            return await _call_claude(prompt, system, max_tokens)
        except anthropic.APIStatusError as exc:
            logger.error(f"Anthropic API {exc.status_code} (attempt {attempt}): {exc.message}")
        except anthropic.APIConnectionError as exc:
            logger.error(f"Anthropic connection error (attempt {attempt}): {exc}")
        except Exception as exc:
            logger.error(f"Unexpected Anthropic error (attempt {attempt}): {exc}", exc_info=True)
        if attempt < config.MAX_RETRIES:
            await asyncio.sleep(config.RETRY_BASE_DELAY ** attempt)
    return None

# ---------------------------------------------------------------------------
# 1. Daily morning message (themed by day)
# ---------------------------------------------------------------------------

_MORNING_SYSTEM = (
    "Eres un coach motivacional experto en comunicación positiva en español. "
    "Generas mensajes únicos, variados y auténticos. "
    "Respondes ÚNICAMENTE con el JSON solicitado, sin texto adicional."
)

async def generate_message(day_of_week: int | None = None) -> str:
    """Generate the daily themed morning message."""
    if day_of_week is None:
        day_of_week = datetime.now().weekday()

    day_name, day_theme = DAY_THEMES[day_of_week]
    recent = get_recent_messages()
    history_ctx = (
        "MENSAJES RECIENTES (no repitas temas):\n" + "\n---\n".join(recent[-10:])
        if recent else "(Sin mensajes previos)"
    )

    prompt = f"""\
Genera un mensaje motivacional de buenos días en español para un {day_name}.
Tema del día: {day_theme}.

Devuelve EXACTAMENTE este JSON:
{{
  "greeting": "saludo breve acorde al día",
  "emoji": "UN emoji relevante",
  "quote": "cita o reflexión inspiradora de 1-2 líneas",
  "body": "2-3 frases prácticas. Puede terminar con una pregunta reflexiva."
}}

REGLAS:
- Varía el tono: reflexivo / energético / filosófico / práctico / con humor positivo
- Sin clichés vacíos
- Idioma: español
- NO repitas los temas recientes

{history_ctx}

Devuelve ÚNICAMENTE el JSON."""

    raw = await _call_with_retry(prompt, _MORNING_SYSTEM)
    if raw:
        try:
            data = json.loads(raw)
            msg = build_message(data["greeting"], data["emoji"], data["quote"], data["body"])
            logger.info(f"Morning message generated ({day_name}).")
            return msg
        except (json.JSONDecodeError, KeyError) as exc:
            logger.error(f"Bad JSON from Claude: {exc}")

    logger.error("Using fallback morning message.")
    return _next_fallback()

# ---------------------------------------------------------------------------
# 2. Evening check-in
# ---------------------------------------------------------------------------

_EVENING_SYSTEM = (
    "Eres un coach de bienestar que acompaña a personas al final del día. "
    "Tus mensajes son breves, cálidos y reflexivos. "
    "Respondes ÚNICAMENTE con el JSON solicitado."
)

async def generate_evening_checkin() -> str:
    """Generate the evening reflection message."""
    day_name, _ = DAY_THEMES[datetime.now().weekday()]
    prompt = f"""\
Genera un mensaje de cierre del día para un {day_name} por la noche.
Debe invitar a reflexionar sobre el día, agradecer algo pequeño, y preparar la mente para descansar.

Devuelve EXACTAMENTE este JSON:
{{
  "greeting": "saludo nocturno breve (ej: Buenas noches, Hora de cerrar el día...)",
  "emoji": "UN emoji nocturno o reflexivo (🌙✨🌟💫🕯️🌜)",
  "quote": "reflexión breve y serena de 1 línea",
  "body": "2 frases cálidas. Termina con UNA pregunta de reflexión sobre el día."
}}

Devuelve ÚNICAMENTE el JSON."""

    raw = await _call_with_retry(prompt, _EVENING_SYSTEM, max_tokens=400)
    if raw:
        try:
            data = json.loads(raw)
            return build_message(data["greeting"], data["emoji"], data["quote"], data["body"])
        except (json.JSONDecodeError, KeyError) as exc:
            logger.error(f"Bad JSON for evening: {exc}")

    return build_message(
        "Buenas noches", "🌙",
        "El descanso no es rendirse — es prepararse para mañana.",
        "Antes de dormir, piensa en una cosa que salió bien hoy. ¿Qué fue?"
    )

# ---------------------------------------------------------------------------
# 3. Afternoon audio monologue (sent at 16:00, designed to be HEARD not read)
# ---------------------------------------------------------------------------

_AUDIO_SYSTEM = (
    "Eres un locutor motivacional con voz cálida y energética. "
    "Escribes monólogos pensados para ser escuchados como un podcast corto. "
    "Tu estilo es cercano, directo y emotivo — como un buen amigo que inspira. "
    "Usas pausas naturales, segunda persona (tú/tu) y ritmo conversacional."
)

async def generate_afternoon_audio() -> str:
    """
    Generate a spoken-word motivational monologue for the 4pm audio.
    Returns plain text (no MarkdownV2) — optimized for text-to-speech.
    Deliberately different content from the morning text message.
    """
    day_name, _ = DAY_THEMES[datetime.now().weekday()]

    prompt = f"""\
Escribe un monólogo motivacional en español para ser escuchado a las 4 de la tarde de un {day_name}.
El oyente lleva ya más de la mitad del día — puede estar cansado, distraído o con el bajón de media tarde.

REQUISITOS ESTRICTOS:
- Texto fluido para VOZ: sin emojis, sin viñetas, sin asteriscos, sin formato
- Segunda persona (tú/tu)
- Incluye UNA analogía o microhistoria de 2-3 frases
- Energía moderada-alta, emotivo, auténtico
- Longitud: 150-180 palabras (aprox. 45-60 segundos de audio)
- Termina con una frase de afirmación poderosa en positivo
- DISTINTO al típico mensaje de buenos días: habla del momento actual, la tarde, el esfuerzo ya hecho

Devuelve ÚNICAMENTE el texto del monólogo, sin títulos ni encabezados."""

    raw = await _call_with_retry(prompt, _AUDIO_SYSTEM, max_tokens=350)
    if raw:
        logger.info("Afternoon audio script generated.")
        return raw

    # Fallback plain text
    return (
        "Ya llevas más de la mitad del día. Eso, aunque no lo parezca, es mucho. "
        "Piensa en un escalador: no celebra la cima antes de llegar, pero tampoco ignora "
        "cada metro que ya escaló. Tú estás ahí ahora mismo — a mitad de la pared, "
        "con el esfuerzo acumulado y la cima todavía posible.\n\n"
        "La tarde es donde se decide quién eres de verdad. No cuando todo va bien, "
        "sino cuando el cansancio llega y tú decides seguir de todos modos. "
        "Eso es lo que te diferencia.\n\n"
        "Tienes más de lo que crees. Termina fuerte este día. "
        "Porque cuando llegue la noche, quieres poder decir que diste todo."
    )


# ---------------------------------------------------------------------------
# 3. Weekly challenge (sent Monday morning)
# ---------------------------------------------------------------------------

_CHALLENGE_SYSTEM = (
    "Eres un coach de hábitos que lanza retos semanales prácticos y alcanzables. "
    "Respondes ÚNICAMENTE con el JSON solicitado."
)

async def generate_weekly_challenge() -> str:
    """Generate the Monday weekly challenge."""
    prompt = """\
Crea un reto semanal práctico y alcanzable para esta semana.
El reto debe poder hacerse en 5-15 minutos al día y generar un cambio real si se mantiene 7 días.

Devuelve EXACTAMENTE este JSON:
{
  "title": "nombre corto del reto (máx 6 palabras)",
  "emoji": "UN emoji que represente el reto",
  "challenge": "descripción del reto en 1-2 frases claras: QUÉ hacer, CUÁNDO y CUÁNTO tiempo",
  "why": "por qué este reto tiene impacto (1 frase)",
  "cta": "frase de cierre motivadora y directa (1 frase corta)"
}

Varía el tipo de reto: hábitos físicos, mentales, sociales, creativos, de gratitud, productividad.
Devuelve ÚNICAMENTE el JSON."""

    raw = await _call_with_retry(prompt, _CHALLENGE_SYSTEM, max_tokens=400)
    if raw:
        try:
            d = json.loads(raw)
            title_esc = escape_mdv2(d["title"])
            challenge_esc = escape_mdv2(d["challenge"])
            why_esc = escape_mdv2(d["why"])
            cta_esc = escape_mdv2(d["cta"])
            emoji = d["emoji"]
            return (
                f"🎯 *Reto de la semana* {emoji}\n\n"
                f"*{title_esc}*\n\n"
                f"{challenge_esc}\n\n"
                f"_{why_esc}_\n\n"
                f"{cta_esc}"
            )
        except (json.JSONDecodeError, KeyError) as exc:
            logger.error(f"Bad JSON for weekly challenge: {exc}")

    return (
        f"🎯 *Reto de la semana* 💪\n\n"
        f"*Escribe 3 gratitudes cada noche*\n\n"
        f"Antes de dormir, anota 3 cosas buenas que pasaron hoy\\. Solo 3 minutos\\.\n\n"
        f"_Entrena tu mente para ver lo positivo en cualquier situación\\._\n\n"
        f"¿Aceptas el reto esta semana?"
    )

# ---------------------------------------------------------------------------
# 4. Weekly summary (sent Sunday evening)
# ---------------------------------------------------------------------------

_SUMMARY_SYSTEM = (
    "Eres un coach reflexivo que ayuda a las personas a integrar sus aprendizajes semanales. "
    "Respondes ÚNICAMENTE con el JSON solicitado."
)

async def generate_weekly_summary(week_messages: list[str]) -> str:
    """Generate Sunday's weekly recap based on messages sent during the week."""
    if week_messages:
        plain = [mdv2_to_plain(m) for m in week_messages[-5:]]
        ctx = "Mensajes de esta semana:\n" + "\n---\n".join(plain)
    else:
        ctx = "(Sin mensajes esta semana)"

    prompt = f"""\
Crea un mensaje de cierre semanal reflexivo en español para el domingo por la tarde.
Debe hacer una reflexión integradora de la semana, invitar a celebrar los logros y preparar la intención para la próxima.

{ctx}

Devuelve EXACTAMENTE este JSON:
{{
  "greeting": "saludo de cierre semanal",
  "emoji": "UN emoji de cierre/reflexión",
  "reflection": "reflexión integradora de 1-2 frases sobre la semana",
  "body": "2-3 frases: celebrar lo conseguido + intención para la próxima semana. Termina con una pregunta."
}}

Devuelve ÚNICAMENTE el JSON."""

    raw = await _call_with_retry(prompt, _SUMMARY_SYSTEM, max_tokens=500)
    if raw:
        try:
            d = json.loads(raw)
            return build_message(d["greeting"], d["emoji"], d["reflection"], d["body"])
        except (json.JSONDecodeError, KeyError) as exc:
            logger.error(f"Bad JSON for weekly summary: {exc}")

    return build_message(
        "Cierre de semana", "🌅",
        "Cada semana es un capítulo completo — con sus retos y sus victorias.",
        "Tómate un momento para celebrar lo que conseguiste, por pequeño que sea. ¿Cuál fue tu mayor logro esta semana?"
    )

# ---------------------------------------------------------------------------
# 5. /reflexion command — on-demand topic reflection
# ---------------------------------------------------------------------------

_REFLECTION_SYSTEM = (
    "Eres un coach de mentalidad que ofrece reflexiones profundas y prácticas en español. "
    "Eres directo, cercano y sin tecnicismos. "
    "Respondes ÚNICAMENTE con el JSON solicitado."
)

async def generate_reflection(topic: str) -> str:
    """Generate a reflection on a user-requested topic."""
    topic_safe = topic[:100]  # limit length
    prompt = f"""\
El usuario quiere reflexionar sobre: "{topic_safe}"

Genera una reflexión breve, profunda y práctica sobre este tema.

Devuelve EXACTAMENTE este JSON:
{{
  "title": "título breve de la reflexión",
  "emoji": "UN emoji relevante al tema",
  "insight": "la idea central en 1-2 frases — algo no obvio y valioso",
  "body": "2-3 frases de aplicación práctica. Termina con una pregunta personal."
}}

Devuelve ÚNICAMENTE el JSON."""

    raw = await _call_with_retry(prompt, _REFLECTION_SYSTEM, max_tokens=400)
    if raw:
        try:
            d = json.loads(raw)
            return build_message(d["title"], d["emoji"], d["insight"], d["body"])
        except (json.JSONDecodeError, KeyError) as exc:
            logger.error(f"Bad JSON for reflection: {exc}")

    topic_esc = escape_mdv2(topic_safe)
    return build_message(
        f"Reflexión sobre {topic_safe}", "💡",
        "Cada tema difícil es una puerta a un mayor autoconocimiento.",
        f"Pregúntate: ¿qué es lo que realmente sientes sobre {topic_safe}? A veces la respuesta ya la tienes."
    )

# ---------------------------------------------------------------------------
# 6. Milestone celebration
# ---------------------------------------------------------------------------

_MILESTONE_SYSTEM = (
    "Eres el community manager de un canal motivacional en Telegram. "
    "Celebras los hitos de la comunidad con entusiasmo auténtico. "
    "Respondes ÚNICAMENTE con el JSON solicitado."
)

async def generate_milestone_message(count: int) -> str:
    """Generate a celebration message for reaching a follower milestone."""
    prompt = f"""\
El canal de motivación acaba de alcanzar {count} miembros. ¡Es un hito importante!

Genera un mensaje de celebración para publicar en el canal.

Devuelve EXACTAMENTE este JSON:
{{
  "greeting": "saludo de celebración",
  "emoji": "UN emoji festivo",
  "celebration": "1-2 frases celebrando el hito y agradeciendo a la comunidad",
  "body": "1-2 frases sobre lo que significa esta comunidad + invita a compartir el canal con alguien que lo necesite"
}}

Devuelve ÚNICAMENTE el JSON."""

    raw = await _call_with_retry(prompt, _MILESTONE_SYSTEM, max_tokens=350)
    if raw:
        try:
            d = json.loads(raw)
            return build_message(d["greeting"], d["emoji"], d["celebration"], d["body"])
        except (json.JSONDecodeError, KeyError) as exc:
            logger.error(f"Bad JSON for milestone: {exc}")

    count_esc = escape_mdv2(str(count))
    return build_message(
        f"¡{count} personas en la comunidad!", "🎉",
        f"Acabamos de alcanzar {count} miembros. Gracias por estar aquí.",
        "Esta comunidad crece porque cada uno de vosotros aporta energía. Comparte este canal con alguien que necesite un empujón diario."
    )

# ---------------------------------------------------------------------------
# 7. Community phrase spotlight
# ---------------------------------------------------------------------------

async def generate_phrase_intro(phrase: str, username: str | None) -> str:
    """Format a community-submitted phrase for the channel."""
    author = f"@{username}" if username else "un miembro de la comunidad"
    phrase_esc = escape_mdv2(phrase)
    author_esc = escape_mdv2(author)
    return (
        f"💬 *La frase de la comunidad*\n\n"
        f"_{phrase_esc}_\n\n"
        f"Gracias a {author_esc} por compartirla\\. "
        f"¿Quieres que tu frase aparezca aquí? Envíame /frase seguido de tu reflexión\\."
    )
