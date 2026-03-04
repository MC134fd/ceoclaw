FROM python:3.12-slim

LABEL org.opencontainers.image.title="CEOClaw" \
      org.opencontainers.image.description="Autonomous founder agent REST API" \
      org.opencontainers.image.version="1.0.0"

# ---------------------------------------------------------------------------
# System dependencies (curl for healthcheck only)
# ---------------------------------------------------------------------------
RUN apt-get update -qq && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

# Runtime directories (SQLite lives in /data, mounted as a volume)
RUN mkdir -p /data data/exports data/websites

# ---------------------------------------------------------------------------
# Runtime configuration
# ---------------------------------------------------------------------------
ENV CEOCLAW_DATABASE_PATH=/data/ceoclaw.db \
    FLOCK_MOCK_MODE=true \
    CEOCLAW_ENV=production

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -sf http://localhost:8000/health || exit 1

# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8000", \
     "--log-level", "info"]
