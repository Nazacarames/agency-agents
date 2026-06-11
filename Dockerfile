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

# Sin USER no-root: Render corre como root, los permisos no-root pueden romper
# el install de playwright. El container es efímero.
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://localhost:${PORT:-8000}/healthz || exit 1

# CMD: arranca uvicorn en foreground. El launcher Hermes se removió
# (lo corremos como job de Render en lugar de background process).
# --timeout-keep-alive 30 acepta health checks lentos.
# stdout/stderr van a tty, que Render captura en /logs.
CMD ["sh", "-c", "echo \"[startup] $(date) - launching uvicorn\"; exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --log-level info --timeout-keep-alive 30"]
