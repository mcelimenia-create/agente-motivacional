# ── Build stage: install deps ────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Runtime stage ────────────────────────────────────────────────────────────
FROM python:3.11-slim

# Create a non-root user for security
RUN useradd --create-home --shell /bin/bash botuser

WORKDIR /app

# Copy installed packages from build stage
COPY --from=builder /install /usr/local

# Copy application source
COPY config.py history_manager.py message_generator.py bot.py \
     phrase_collector.py state_manager.py ./

# Data directory (mount a volume here for persistence)
RUN mkdir -p /app/data && chown botuser:botuser /app/data

USER botuser

# Persist all data files in /app/data so they survive container restarts
ENV HISTORY_FILE=/app/data/messages_history.json
ENV PHRASES_FILE=/app/data/community_phrases.json
ENV STATE_FILE=/app/data/bot_state.json

# Unbuffered output so logs appear immediately
ENV PYTHONUNBUFFERED=1

CMD ["python", "bot.py"]
