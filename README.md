# Bot Motivacional de Telegram

Envía automáticamente un mensaje motivacional en español a un canal o grupo de Telegram cada mañana, generado por Claude (Anthropic).

```
*¡Buenos días!* ☀️

_"La disciplina es elegir entre lo que quieres ahora y lo que más quieres."_

Hoy es un nuevo comienzo. Cada pequeña acción cuenta — no busques la perfección, busca el progreso. ¿Qué vas a hacer hoy que tu yo futuro te agradecerá?
```

---

## Requisitos previos

- Python 3.11+
- Una cuenta de Telegram y un bot creado con [@BotFather](https://t.me/BotFather)
- Una API key de [Anthropic](https://console.anthropic.com/)

---

## Instalación

```bash
# 1. Clona / descarga este directorio
cd telegram-motivational-bot

# 2. Crea un entorno virtual
python -m venv .venv
source .venv/bin/activate      # Linux/macOS
# .venv\Scripts\activate       # Windows

# 3. Instala dependencias
pip install -r requirements.txt

# 4. Configura las variables de entorno
cp .env.example .env
# Edita .env con tus credenciales
```

---

## Configuración

Copia `.env.example` a `.env` y rellena los valores:

| Variable | Descripción | Ejemplo |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Token del bot (de @BotFather) | `123456:ABCdef...` |
| `TELEGRAM_CHANNEL_ID` | ID del canal/grupo destino | `-1001234567890` |
| `TELEGRAM_ADMIN_ID` | Tu user ID de Telegram (para alertas de error) | `98765432` |
| `ANTHROPIC_API_KEY` | API key de Anthropic | `sk-ant-...` |
| `SEND_TIME` | Hora de envío en formato HH:MM | `07:30` |
| `TIMEZONE` | Zona horaria IANA | `Europe/Madrid` |

### Cómo obtener el token de Telegram

1. Abre Telegram y busca [@BotFather](https://t.me/BotFather)
2. Envía `/newbot` y sigue las instrucciones
3. Copia el token que te proporciona (formato `123456789:AABBccDDee...`)

### Cómo obtener el CHANNEL_ID

**Para un canal:**
1. Añade el bot como administrador del canal con permiso de publicar
2. Reenvía cualquier mensaje del canal a [@userinfobot](https://t.me/userinfobot)
3. Te dará el ID (número negativo que empieza por `-100`)

**Para un grupo:**
1. Añade el bot al grupo y hazlo administrador
2. Envía cualquier mensaje en el grupo
3. Accede a `https://api.telegram.org/bot<TOKEN>/getUpdates` y busca el `chat.id`

**Alternativa rápida:** añade [@RawDataBot](https://t.me/RawDataBot) temporalmente al canal/grupo.

### Cómo obtener tu TELEGRAM_ADMIN_ID

Envía cualquier mensaje a [@userinfobot](https://t.me/userinfobot) — te responde con tu user ID.

---

## Ejecución local

```bash
# Activa el entorno virtual si no está activo
source .venv/bin/activate

# Arranca el bot
python bot.py
```

El bot se conecta a Telegram, programa el envío diario y queda escuchando comandos. Pulsa `Ctrl+C` para detenerlo.

---

## Despliegue con Docker

```bash
# Construir la imagen
docker build -t motivational-bot .

# Ejecutar (con volumen para persistir el historial)
docker run -d \
  --name motivational-bot \
  --restart unless-stopped \
  -v $(pwd)/data:/app/data \
  --env-file .env \
  motivational-bot
```

Para ver los logs:
```bash
docker logs -f motivational-bot
```

Para detenerlo:
```bash
docker stop motivational-bot
```

### Docker Compose (recomendado para producción)

Crea un `docker-compose.yml`:

```yaml
services:
  bot:
    build: .
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./data:/app/data
```

```bash
docker compose up -d
docker compose logs -f
```

---

## Despliegue en Railway

Railway es la opción más sencilla para tener el bot corriendo en la nube de forma gratuita (plan Hobby tiene $5 de crédito mensual, suficiente para un bot ligero).

### Pasos

**1. Sube el código a GitHub**

Si aún no tienes un repo, crea uno con solo el contenido de esta carpeta:

```bash
cd telegram-motivational-bot
git init
git add .
git commit -m "initial commit"
gh repo create mi-bot-motivacional --private --source=. --push
# (o usa la web de GitHub)
```

**2. Crea el proyecto en Railway**

1. Ve a [railway.app](https://railway.app) e inicia sesión con GitHub
2. Haz clic en **New Project → Deploy from GitHub repo**
3. Selecciona el repositorio

> Si el repo tiene el bot en una subcarpeta, ve a **Service → Settings → Source → Root Directory** y escribe la ruta (ej. `telegram-motivational-bot`).

**3. Añade las variables de entorno**

En Railway: **Service → Variables → Add Variable** (o importa el archivo `.env`):

| Variable | Valor |
|---|---|
| `TELEGRAM_BOT_TOKEN` | tu token de @BotFather |
| `TELEGRAM_CHANNEL_ID` | ej. `-1001234567890` |
| `TELEGRAM_ADMIN_ID` | tu user ID de Telegram |
| `ANTHROPIC_API_KEY` | tu API key |
| `SEND_TIME` | `07:30` |
| `TIMEZONE` | `Europe/Madrid` |
| `HISTORY_FILE` | `/app/data/messages_history.json` |

**4. Añade un Volume para persistir el historial**

Sin esto el historial se pierde en cada deploy.

1. **Service → Volumes → Add Volume**
2. Mount Path: `/app/data`
3. Guarda — Railway monta el disco persistente automáticamente

**5. Despliega**

Railway detecta el `Dockerfile` y el `railway.toml` automáticamente. Haz clic en **Deploy** (o el primer deploy se lanza solo al conectar el repo).

Verifica en **Deployments → Logs** que aparezca:
```
Config OK — channel=...
Health-check server listening on :XXXX
Scheduler started — daily message at 07:30 (Europe/Madrid)
Bot is running.
```

### Re-despliegues

Cada `git push` al repo dispara un nuevo deploy automático. El historial JSON sobrevive porque está en el Volume persistente.

---

## Comandos del bot

| Comando | Descripción | Acceso |
|---|---|---|
| `/start` | Bienvenida y descripción | Todos |
| `/siguiente` | Previsualiza el próximo mensaje | Todos |
| `/ahora` | Fuerza el envío inmediato | Solo admin |
| `/stats` | Estadísticas de mensajes enviados | Todos |

---

## Estructura del proyecto

```
telegram-motivational-bot/
├── bot.py                  # Punto de entrada, handlers, lifecycle hooks
├── message_generator.py    # Generación con Claude + formateo MarkdownV2
├── scheduler.py            # Configuración de APScheduler
├── history_manager.py      # Lectura/escritura del historial JSON
├── config.py               # Variables de entorno y validación
├── .env.example            # Plantilla de configuración
├── requirements.txt        # Dependencias Python
├── Dockerfile              # Imagen Docker lista para producción
└── README.md
```

**Archivos generados en tiempo de ejecución:**
- `messages_history.json` — historial de mensajes (o en `/app/data/` en Docker)
- `bot.log` — logs con rotación automática (5 MB × 3 archivos)

---

## Comportamiento en reinicios

- Si el bot arranca **antes** de la hora programada, enviará el mensaje a la hora correcta.
- Si arranca **después** de la hora programada (margen de más de 60 segundos), **no** enviará mensaje ese día — esperará al día siguiente.
- El historial de mensajes persiste entre reinicios gracias al archivo JSON.

---

## Zonas horarias habituales

| País | Timezone |
|---|---|
| España | `Europe/Madrid` |
| México (Ciudad) | `America/Mexico_City` |
| Colombia | `America/Bogota` |
| Argentina | `America/Argentina/Buenos_Aires` |
| Chile | `America/Santiago` |
| Perú | `America/Lima` |

Lista completa: [Wikipedia — List of tz database time zones](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones)
