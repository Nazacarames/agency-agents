# ────────────────────────────────────────────────────────────
# Automiq Agency Agents — Dockerfile
# Multi-stage para imagen final pequeña
# ────────────────────────────────────────────────────────────
FROM python:3.12-slim AS base

# Evita bytecode .pyc y fuerza stdout sin buffer (logs de Render)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencias del sistema (tzdata para America/Buenos_Aires, curl para healthcheck)
# Añadimos libs necesarias para que Playwright funcione en Debian slim
RUN apt-get update && apt-get install -y --no-install-recommends \
        tzdata \
        curl \
        ca-certificates \
        wget \
        gnupg \
        libnss3 \
        libatk1.0-0 \
        libatk-bridge2.0-0 \
        libcups2 \
        libxss1 \
        libasound2 \
        libx11-xcb1 \
        libxcomposite1 \
        libxdamage1 \
        libxrandr2 \
        libpangocairo-1.0-0 \
        libgtk-3-0 \
        libgbm1 \
        libdrm2 \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Zona horaria de Argentina
ENV TZ=America/Buenos_Aires
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Instalar deps primero (mejor cacheo de layers)
COPY requirements.txt .
RUN pip install -r requirements.txt

# Instalar navegadores Playwright (con deps) — debe ejecutarse como root
RUN python -m playwright install --with-deps

# Copiar el código
COPY app/ ./app/
COPY data/ ./data/
COPY scripts/ ./scripts/

# Crear directorios de runtime con permisos
RUN mkdir -p logs && chmod -R 755 /app

# Usuario no-root (Render-compatible)
RUN useradd --create-home --shell /bin/bash automiq
RUN chown -R automiq:automiq /app
USER automiq

# Exponer puerto (Render lo lee de $PORT, pero declaramos el default)
EXPOSE 8000

# Healthcheck nativo de Docker
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:${PORT:-8000}/healthz || exit 1

# Comando de inicio
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
