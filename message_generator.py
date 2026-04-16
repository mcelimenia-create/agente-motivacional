"""
All Claude-powered content generation for the motivational bot.

Each generator returns a fully formatted Telegram MarkdownV2 string
(or plain text where indicated). The JSON-structured prompting approach
lets us apply formatting programmatically, avoiding MarkdownV2 escaping bugs.
"""
import asyncio
import json
import logging
import random
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
# Weekly series themes (rotating by ISO week number % 12)
# ---------------------------------------------------------------------------
WEEKLY_SERIES = [
    ("Arranque Fuerte",       "cómo empezar con energía y determinación"),
    ("Foco Total",            "eliminar distracciones y concentrarte en lo que importa"),
    ("Disciplina Diaria",     "constancia y hábitos que superan a la motivación"),
    ("Mentalidad de Campeón", "reprogramar creencias limitantes y pensar en grande"),
    ("Gestión de Energía",    "hábitos que te recargan frente a los que te drenan"),
    ("El Poder del Entorno",  "las personas y espacios que te impulsan o frenan"),
    ("De Sueño a Plan",       "convertir objetivos vagos en pasos concretos"),
    ("Resiliencia",           "caerse, levantarse y salir más fuerte"),
    ("Gratitud Activa",       "ver y aprovechar lo que ya tienes en tu vida"),
    ("Acción Masiva",         "ejecutar sin excusas, hacer más y pensar menos"),
    ("Descanso Inteligente",  "recuperar bien para rendir mejor"),
    ("Tu Propósito",              "el por qué detrás de todo lo que haces"),
    # — second rotation (weeks 13–24) —
    ("Comunicación Poderosa",     "expresarte con claridad e impacto en cada situación"),
    ("Gestión del Tiempo",        "hacer más en menos tiempo sin agotarte"),
    ("Confianza en Ti Mismo",     "construir autoestima desde adentro hacia afuera"),
    ("Manejo del Estrés",         "convertir la presión en rendimiento y calma interior"),
    ("Creatividad Práctica",      "innovar y resolver problemas de forma original"),
    ("Liderazgo Personal",        "dirigirte a ti mismo antes de poder dirigir a otros"),
    ("Mentalidad de Crecimiento", "aprender de los errores y mejorar siempre sin excusas"),
    ("Conexiones Auténticas",     "construir relaciones que te enriquezcan de verdad"),
    ("Inteligencia Emocional",    "entender y gestionar tus emociones con madurez"),
    ("Alto Rendimiento",          "las rutinas que separan resultados mediocres de los extraordinarios"),
    ("Visión a Largo Plazo",      "pensar en años, no en días, y actuar en consecuencia"),
    ("Equilibrio y Bienestar",    "rendir sin sacrificar tu salud ni tu felicidad"),
]

def get_week_theme() -> tuple[str, str]:
    """Return (name, description) for the current week's series theme."""
    week_num = datetime.now().isocalendar()[1]
    return WEEKLY_SERIES[week_num % len(WEEKLY_SERIES)]


# ---------------------------------------------------------------------------
# Wednesday mid-week polls (aligned with weekly series themes)
# ---------------------------------------------------------------------------
WEDNESDAY_POLLS = [
    ("¿Con qué energía arrancaste esta semana?",
     ["🚀 Con todo desde el primer día", "😐 Normal, tirando", "🐌 Poco a poco voy cogiendo ritmo", "🔄 Remontando"]),
    ("¿Cuánto tiempo has pasado en foco real esta semana?",
     ["💪 Más de 4 horas al día", "😐 Entre 2 y 3 horas", "😓 Menos de 1 hora", "🤯 El caos me ganó"]),
    ("¿Has mantenido tus hábitos esta semana?",
     ["✅ Todos sin excepción", "🤏 La gran mayoría", "⚡ Algunos sí, otros no", "❌ Ha sido difícil"]),
    ("¿Cómo está tu mentalidad a mitad de semana?",
     ["🔥 Imparable, sin frenos", "😐 Estable y constante", "😓 Necesito un empujón", "🧘 Reconectando"]),
    ("¿Cómo está tu nivel de energía hoy?",
     ["⚡ Al 100%, sin parar", "😐 Normal, bien", "😴 Bajo, necesito recarga", "🔄 Recuperándome"]),
    ("¿Tu entorno te está impulsando esta semana?",
     ["🚀 Totalmente", "😐 Más o menos", "😓 Me está frenando", "🔄 Lo estoy cambiando"]),
    ("¿Cuánto avanzaste en tus objetivos esta semana?",
     ["🎯 Mucho, voy bien", "😐 Algo de progreso", "🐌 Poco, pero sigo", "🔄 Replanificando"]),
    ("¿Superaste algún obstáculo esta semana?",
     ["💪 Sí, y salí más fuerte", "🤏 Sí, lo estoy trabajando", "😅 Sin grandes obstáculos", "🔄 Sigo intentándolo"]),
    ("¿Qué tan consciente eres de lo bueno en tu vida hoy?",
     ["🙏 Muy consciente", "😐 Algo, podría mejorar", "😓 Me cuesta verlo ahora", "🔄 Practicando la gratitud"]),
    ("¿Cuántas cosas importantes completaste esta semana?",
     ["🎯 Más de 3 cosas clave", "😐 Una o dos importantes", "🐌 Casi nada todavía", "🔄 Priorizando ahora"]),
    ("¿Cómo estás descansando esta semana?",
     ["😴 Genial, me cuido bien", "😐 Regular", "😓 Poco y mal", "🔄 Ajustando mi rutina"]),
    ("¿Sientes que tus acciones esta semana tienen sentido?",
     ["🌟 Totalmente alineado", "😐 Más o menos", "😕 Lo estoy buscando", "🔄 Reconectando con mi propósito"]),
    # — second rotation (weeks 13–24) —
    ("¿Cómo estás comunicándote esta semana?",
     ["💬 Con mucha claridad", "😐 Normal", "😓 Me cuesta expresarme", "🔄 Mejorando poco a poco"]),
    ("¿Estás usando bien tu tiempo esta semana?",
     ["⏱️ Muy bien, con foco", "😐 Más o menos", "😓 Lo pierdo fácil", "🔄 Reorganizando prioridades"]),
    ("¿Cómo está tu confianza esta semana?",
     ["💪 Alta, me siento capaz", "😐 Normal", "😓 Dudando de mí", "🔄 Construyéndola día a día"]),
    ("¿Cómo manejas el estrés esta semana?",
     ["🧘 Muy bien, con calma", "😐 Tirando", "😓 Me supera a ratos", "🔄 Buscando mi ritmo"]),
    ("¿Estás siendo creativo/a en la resolución de problemas?",
     ["💡 Sí, encontré soluciones nuevas", "😐 Lo de siempre", "😓 Estancado/a", "🔄 Abriendo la mente"]),
    ("¿Te estás liderando bien a ti mismo/a esta semana?",
     ["🎯 Sí, con disciplina", "😐 Regular", "😓 Me falta dirección", "🔄 Trabajando en ello"]),
    ("¿Estás aprendiendo de los errores esta semana?",
     ["📚 Sí, cada error me enseña", "😐 Intento", "😓 Me afectan demasiado", "🔄 Cambiando mi perspectiva"]),
    ("¿Cómo están tus relaciones esta semana?",
     ["❤️ Conectado/a y presente", "😐 Normal", "😓 Distante o aislado/a", "🔄 Cuidando más mis vínculos"]),
    ("¿Estás gestionando bien tus emociones esta semana?",
     ["🧠 Muy bien, con madurez", "😐 Más o menos", "😓 Me desborda a veces", "🔄 Practicando la gestión"]),
    ("¿Estás rindiendo al nivel que quieres esta semana?",
     ["🚀 Sí, al máximo", "😐 A buen ritmo", "😓 Por debajo de lo esperado", "🔄 Ajustando mis hábitos"]),
    ("¿Piensas en el largo plazo o solo en el día a día?",
     ["🔭 Tengo visión clara", "😐 Mezclo ambas", "😓 Solo veo el corto plazo", "🔄 Construyendo mi visión"]),
    ("¿Cómo está tu equilibrio entre trabajo y bienestar?",
     ["⚖️ Muy equilibrado", "😐 Tirando", "😓 Desequilibrado", "🔄 Poniendo límites"]),
]

def get_wednesday_poll() -> tuple[str, list[str]]:
    """Return (question, options) for this week's Wednesday mid-week poll."""
    week_num = datetime.now().isocalendar()[1]
    return WEDNESDAY_POLLS[week_num % len(WEDNESDAY_POLLS)]


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
    """Strip MarkdownV2 formatting to get plain comparable text."""
    text = re.sub(r"\\(.)", r"\1", text)   # unescape \. \! etc.
    text = re.sub(r"[*_~`]", "", text)     # remove bold/italic markers
    return text.strip()


_STOPWORDS = {
    "de", "la", "el", "en", "un", "una", "que", "es", "y", "a", "con", "por",
    "para", "tu", "te", "se", "lo", "no", "si", "del", "al", "le", "su", "sus",
    "pero", "más", "este", "esta", "hay", "ser", "cada", "hoy", "día", "días",
    "vida", "vez", "como", "qué", "cómo", "solo", "bien", "muy", "ya", "todo",
    "todos", "las", "los", "sus", "has", "hace", "algo", "nada", "puedes",
}


def _is_duplicate(candidate: str, recent_plain: list[str], threshold: float = 0.45) -> bool:
    """Return True if candidate shares too many content words with any recent message."""
    cand_words = set(mdv2_to_plain(candidate).lower().split()) - _STOPWORDS
    if len(cand_words) < 8:
        return False
    for ref in recent_plain:
        ref_words = set(ref.lower().split()) - _STOPWORDS
        if not ref_words:
            continue
        overlap = len(cand_words & ref_words) / min(len(cand_words), len(ref_words))
        if overlap >= threshold:
            logger.debug(f"Duplicate detected (overlap={overlap:.2f}): {candidate[:60]}…")
            return True
    return False


def _pick_fallback(pool: list, recent_plain: list[str]) -> str:
    """Pick a random fallback that is not too similar to recent messages."""
    candidates = [m for m in pool if not _is_duplicate(m, recent_plain)]
    return random.choice(candidates) if candidates else random.choice(pool)


# ---------------------------------------------------------------------------
# Fallback messages — typed pools, randomly selected (never repeat in order)
# ---------------------------------------------------------------------------
_MORNING_FALLBACKS = [
    build_message("¡Buenos días!", "☀️",
                  "El éxito es la suma de pequeños esfuerzos repetidos día tras día.",
                  "No hace falta un gran salto. Un paso firme cada mañana es suficiente para llegar lejos."),
    build_message("¡Feliz inicio de día!", "🌟",
                  "La disciplina es elegir entre lo que quieres ahora y lo que más quieres.",
                  "Hoy tienes 24 horas nuevas. Úsalas con intención. ¿Cuál es la única cosa que, si la haces hoy, marcará la diferencia?"),
    build_message("Buenos días", "🔥",
                  "No esperes la motivación perfecta — actúa, y la motivación te seguirá.",
                  "El cuerpo sigue a la mente, y la mente sigue a la acción. Da el primer paso aunque sea pequeño."),
    build_message("¡Despierta con propósito!", "💪",
                  "El que actúa decide su destino. El que espera lo hereda.",
                  "Antes de abrir cualquier pantalla, decide cuál es tu prioridad número uno de hoy. Eso es lo que importa."),
    build_message("Empieza bien el día", "🌅",
                  "No son las circunstancias las que definen tu día — es tu respuesta a ellas.",
                  "Tienes más control del que crees. Elige cómo vas a responder hoy, antes de que empiece el caos."),
    build_message("Un nuevo día comienza", "🌄",
                  "La constancia hace lo que el talento no puede hacer solo.",
                  "No necesitas ser el mejor, solo necesitas ser consistente. Hoy es otro día de construir."),
    build_message("Buenos días", "⚡",
                  "El foco no es hacer más cosas — es hacer las cosas correctas.",
                  "Identifica las dos cosas más importantes de hoy y hazlas primero. El resto puede esperar."),
    build_message("¡A por el día!", "🚀",
                  "El único fracaso real es no intentarlo.",
                  "Haz algo hoy que tu yo de ayer pensaba que era demasiado difícil. Solo una cosa."),
    build_message("Comienza con energía", "✨",
                  "La diferencia entre quien eres y quien quieres ser está en lo que haces cada día.",
                  "No esperes el momento perfecto. El momento perfecto siempre es ahora."),
    build_message("¡Buenos días!", "🎯",
                  "Las personas de éxito no tienen más tiempo — tienen mejores prioridades.",
                  "Pregúntate: ¿qué acción de hoy tendrá más impacto en un mes? Empieza por ahí."),
]

_EVENING_FALLBACKS = [
    build_message("Buenas noches", "🌙",
                  "El descanso no es rendirse — es prepararse para mañana.",
                  "Antes de dormir, piensa en una cosa que salió bien hoy. ¿Qué fue?"),
    build_message("Cierra bien el día", "✨",
                  "Cada día que terminas con gratitud, el siguiente empieza mejor.",
                  "¿Qué pequeña victoria tuviste hoy que merece reconocimiento?"),
    build_message("Hora de descansar", "🌟",
                  "La noche no es el final — es el punto de recarga para un nuevo comienzo.",
                  "¿Qué aprendiste hoy que te hará mejor mañana?"),
    build_message("Buenas noches", "🕯️",
                  "Un día vivido con intención vale más que una semana de inercia.",
                  "Cierra el día sabiendo que diste algo de ti. ¿Qué fue ese algo?"),
    build_message("Que descanses bien", "💫",
                  "El sueño no interrumpe el progreso — lo consolida.",
                  "Antes de cerrar el día, ¿de qué momento de hoy estás más agradecido/a?"),
]

_CHALLENGE_FALLBACKS = [
    ("Escribe 3 gratitudes cada noche",
     "Antes de dormir, anota 3 cosas buenas que pasaron hoy. Solo 3 minutos.",
     "Entrena tu mente para ver lo positivo en cualquier situación."),
    ("Camina 20 minutos sin el móvil",
     "Cada día, sal a caminar 20 minutos sin auriculares ni pantallas. Solo tú y tu mente.",
     "El movimiento y la soledad activan ideas que el ruido apaga."),
    ("Una tarea difícil antes del mediodía",
     "Identifica la tarea más difícil del día y hazla antes de las 12. Sin negociación.",
     "Quien domina la mañana, domina el día."),
]


def _random_fallback(pool: list) -> str:
    """Return a random element from a fallback pool."""
    return random.choice(pool)

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
    recent = get_recent_messages(n=20, msg_type="morning")
    recent_plain = [mdv2_to_plain(m) for m in recent]
    history_block = (
        "\n---\n".join(recent_plain)
        if recent_plain else "(Sin mensajes previos)"
    )

    theme_name, _ = get_week_theme()

    prompt = f"""\
⛔ MENSAJES MATUTINOS YA ENVIADOS — NO reutilices sus citas, ideas ni estructuras:
{history_block}

---
TAREA: Crea un mensaje de buenos días COMPLETAMENTE DIFERENTE a los anteriores.
- Día: {day_name} — temas del día: {day_theme}
- Tema semanal: "{theme_name}" — incorpóralo sutilmente si encaja
- Varía el tono: reflexivo / energético / filosófico / práctico / con humor positivo
- La "quote" debe ser una reflexión NUEVA, no usada antes
- Sin clichés vacíos

Devuelve EXACTAMENTE este JSON:
{{
  "greeting": "saludo breve acorde al día",
  "emoji": "UN emoji relevante",
  "quote": "reflexión inspiradora NUEVA de 1-2 líneas, no repetida",
  "body": "2-3 frases prácticas. Puede terminar con una pregunta reflexiva."
}}

Devuelve ÚNICAMENTE el JSON."""

    raw = await _call_with_retry(prompt, _MORNING_SYSTEM)
    if raw:
        try:
            data = json.loads(raw)
            msg = build_message(data["greeting"], data["emoji"], data["quote"], data["body"])
            if _is_duplicate(msg, recent_plain):
                logger.warning("Morning message too similar to recent history — using fallback.")
            else:
                logger.info(f"Morning message generated ({day_name}).")
                return msg
        except (json.JSONDecodeError, KeyError) as exc:
            logger.error(f"Bad JSON from Claude: {exc}")

    logger.error("Using fallback morning message.")
    return _pick_fallback(_MORNING_FALLBACKS, recent_plain)

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
    recent = get_recent_messages(n=10, msg_type="evening")
    recent_plain = [mdv2_to_plain(m) for m in recent]
    history_block = (
        "\n---\n".join(recent_plain)
        if recent_plain else "(Sin mensajes nocturnos previos)"
    )

    prompt = f"""\
⛔ MENSAJES NOCTURNOS YA ENVIADOS — NO repitas sus preguntas, reflexiones ni frases:
{history_block}

---
TAREA: Crea un mensaje de cierre del día DIFERENTE a los anteriores para un {day_name} por la noche.
Invita a reflexionar, agradecer algo pequeño y preparar la mente para descansar.

Devuelve EXACTAMENTE este JSON:
{{
  "greeting": "saludo nocturno breve (ej: Buenas noches, Hora de cerrar el día...)",
  "emoji": "UN emoji nocturno o reflexivo (🌙✨🌟💫🕯️🌜)",
  "quote": "reflexión serena de 1 línea, NUEVA y diferente a las anteriores",
  "body": "2 frases cálidas. Termina con UNA pregunta de reflexión DISTINTA a todas las anteriores."
}}

Devuelve ÚNICAMENTE el JSON."""

    raw = await _call_with_retry(prompt, _EVENING_SYSTEM, max_tokens=400)
    if raw:
        try:
            data = json.loads(raw)
            msg = build_message(data["greeting"], data["emoji"], data["quote"], data["body"])
            if _is_duplicate(msg, recent_plain):
                logger.warning("Evening message too similar to recent history — using fallback.")
            else:
                return msg
        except (json.JSONDecodeError, KeyError) as exc:
            logger.error(f"Bad JSON for evening: {exc}")

    return _pick_fallback(_EVENING_FALLBACKS, recent_plain)

# ---------------------------------------------------------------------------
# 3. Weekly challenge (sent Monday morning)
# ---------------------------------------------------------------------------

_CHALLENGE_SYSTEM = (
    "Eres un coach de hábitos que lanza retos semanales prácticos y alcanzables. "
    "Respondes ÚNICAMENTE con el JSON solicitado."
)

async def generate_weekly_challenge() -> str:
    """Generate the Monday weekly challenge aligned with the week's series theme."""
    theme_name, theme_desc = get_week_theme()
    theme_esc = escape_mdv2(theme_name)
    recent = get_recent_messages(n=8, msg_type="challenge")
    recent_plain = [mdv2_to_plain(m) for m in recent]
    history_block = (
        "\n---\n".join(recent_plain)
        if recent_plain else "(Sin retos previos)"
    )

    prompt = f"""\
⛔ RETOS YA ENVIADOS — NO repitas actividades, conceptos ni ideas similares:
{history_block}

---
TAREA: Crea un reto semanal NUEVO para la semana de "{theme_name}": {theme_desc}.
- Debe poder hacerse en 5-15 minutos al día
- Debe generar un cambio real si se mantiene 7 días
- Diferente a todos los retos anteriores en concepto y actividad

Devuelve EXACTAMENTE este JSON:
{{
  "title": "nombre corto del reto (máx 6 palabras)",
  "emoji": "UN emoji que represente el reto",
  "challenge": "descripción del reto en 1-2 frases claras: QUÉ hacer, CUÁNDO y CUÁNTO tiempo",
  "why": "por qué este reto impacta directamente en el tema de la semana (1 frase)",
  "cta": "frase de cierre motivadora y directa (1 frase corta)"
}}

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
                f"📅 *Semana de {theme_esc}*\n\n"
                f"🎯 *Reto de la semana* {emoji}\n\n"
                f"*{title_esc}*\n\n"
                f"{challenge_esc}\n\n"
                f"_{why_esc}_\n\n"
                f"{cta_esc}"
            )
        except (json.JSONDecodeError, KeyError) as exc:
            logger.error(f"Bad JSON for weekly challenge: {exc}")

    title, challenge, why = _pick_fallback(_CHALLENGE_FALLBACKS, recent_plain)
    return (
        f"📅 *Semana de {theme_esc}*\n\n"
        f"🎯 *Reto de la semana* 💪\n\n"
        f"*{escape_mdv2(title)}*\n\n"
        f"{escape_mdv2(challenge)}\n\n"
        f"_{escape_mdv2(why)}_\n\n"
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

# ---------------------------------------------------------------------------
# 8. Onboarding — exclusive welcome message for new members
# ---------------------------------------------------------------------------

_ONBOARDING_SYSTEM = (
    "Eres un coach motivacional cercano y cálido. "
    "Escribes mensajes de bienvenida que hacen que la gente se sienta especial e importante. "
    "Respondes ÚNICAMENTE con el JSON solicitado."
)

async def generate_onboarding_message() -> str:
    """Generate an exclusive welcome message for new members who DM the bot."""
    theme_name, _ = get_week_theme()
    prompt = f"""\
Escribe un mensaje de bienvenida exclusivo para alguien que acaba de unirse a un canal motivacional de Telegram.
Este mensaje lo reciben solo los nuevos miembros, directamente del bot — es especial.
Esta semana el canal trabaja el tema: "{theme_name}".

Devuelve EXACTAMENTE este JSON:
{{
  "greeting": "saludo de bienvenida cálido y personal (ej: Bienvenido/a, Nos alegra que estés aquí...)",
  "emoji": "UN emoji acogedor",
  "quote": "reflexión breve y poderosa sobre los nuevos comienzos o el potencial de las personas (1-2 líneas)",
  "body": "2-3 frases: qué recibirán en el canal (mensajes diarios, audio, retos semanales), menciona que esta semana el tema es '{theme_name}', y termina con una frase de ánimo directa"
}}

Devuelve ÚNICAMENTE el JSON."""

    raw = await _call_with_retry(prompt, _ONBOARDING_SYSTEM, max_tokens=450)
    if raw:
        try:
            data = json.loads(raw)
            return build_message(data["greeting"], data["emoji"], data["quote"], data["body"])
        except (json.JSONDecodeError, KeyError) as exc:
            logger.error(f"Bad JSON for onboarding: {exc}")

    theme_esc = escape_mdv2(theme_name)
    return build_message(
        "¡Bienvenido/a!", "🌟",
        "Cada gran camino empieza con el primer paso. Acabas de darlo.",
        f"Cada mañana recibirás un mensaje para empezar el día con energía\\. "
        f"Cada semana un reto práctico alineado con el tema de la semana\\. "
        f"Esta semana trabajamos *{theme_esc}*\\. "
        f"Estamos aquí para recordarte que puedes más de lo que crees\\."
    )
