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
COPY config.py history_manager.py message_generator.py scheduler.py bot.py ./

# Data directory (mount a volume here for persistence)
RUN mkdir -p /app/data && chown botuser:botuser /app/data

USER botuser

# Store history outside the image so it survives container restarts
ENV HISTORY_FILE=/app/data/messages_history.json

# Unbuffered output so logs appear immediately
ENV PYTHONUNBUFFERED=1

VOLUME ["/app/data"]

CMD ["python", "bot.py"]
