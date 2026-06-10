FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

ENV TZ=America/Buenos_Aires

# Dependencias base + Playwright (sin la imagen oficial porque usa Python viejo)
RUN apt-get update && apt-get install -y --no-install-recommends \
        tzdata \
        curl \
        ca-certificates \
        tesseract-ocr \
        tesseract-ocr-spa \
        libtesseract-dev \
        libnss3 \
        libnspr4 \
        libatk1.0-0 \
        libatk-bridge2.0-0 \
        libcups2 \
        libdrm2 \
        libdbus-1-3 \
        libxkbcommon0 \
        libxcomposite1 \
        libxdamage1 \
        libxfixes3 \
        libxrandr2 \
        libgbm1 \
        libpango-1.0-0 \
        libcairo2 \
        libasound2t64 \
        fonts-liberation \
    && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# ── Hermes + deps del proyecto ────────────────────────────────────────
COPY requirements.txt .
RUN pip install -r requirements.txt
# Playwright browser deps (los binarios se bajan con playwright install)
RUN playwright install --with-deps chromium || true

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
