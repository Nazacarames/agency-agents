FROM mcr.microsoft.com/playwright/python:latest AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

ENV TZ=America/Buenos_Aires

# Dependencias base + Node 18 para web-scraper
RUN apt-get update && apt-get install -y --no-install-recommends \
        tzdata \
        curl \
        ca-certificates \
        tesseract-ocr \
        tesseract-ocr-spa \
        libtesseract-dev \
    && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# ── Hermes + deps del proyecto ────────────────────────────────────────
COPY requirements.txt .
RUN pip install -r requirements.txt && pip install hermes-agent

# ── Código ────────────────────────────────────────────────────────────
COPY app/ ./app/
COPY data/ ./data/
COPY scripts/ ./scripts/
COPY packs/ ./packs/

# Vendor web-scraper (lo usa el módulo adapter)
COPY vendor/ ./vendor/
RUN cd /app/vendor/web-scraper && npm install || true

# ── Hermes home (skills, agents, memory) ─────────────────────────────
ENV HERMES_HOME=/home/automiq/.hermes
RUN mkdir -p $HERMES_HOME/skills $HERMES_HOME/agents $HERMES_HOME/memory \
             logs /app/data && chmod -R 755 $HERMES_HOME

# Usuario no-root
RUN useradd --create-home --shell /bin/bash automiq 2>/dev/null || true \
    && chown -R automiq:automiq /app $HERMES_HOME || true
USER automiq
ENV HOME=/home/automiq

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://localhost:${PORT:-8000}/healthz || exit 1

# CMD: arranca Hermes en background (no bloquea) y uvicorn en foreground.
# Si el launcher falla, uvicorn sigue exponiendo el gateway + scheduler.
CMD ["sh", "-c", "python scripts/launcher_hermes.py >/app/logs/launcher.log 2>&1 || true; exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --log-level info"]
