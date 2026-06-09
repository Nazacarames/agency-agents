# ────────────────────────────────────────────────────────────
# Automiq Agency Agents — Dockerfile
# Multi-stage para imagen final pequeña
# ────────────────────────────────────────────────────────────
FROM mcr.microsoft.com/playwright/python:latest AS base

# Evita bytecode .pyc y fuerza stdout sin buffer (logs de Render)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencias ligeras: tzdata y curl (Playwright base incluye navegadores y libs)
RUN apt-get update && apt-get install -y --no-install-recommends \
        tzdata \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Zona horaria de Argentina
ENV TZ=America/Buenos_Aires
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Instalar deps primero (mejor cacheo de layers)
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copiar el código
COPY app/ ./app/
COPY data/ ./data/
COPY scripts/ ./scripts/

# Crear directorios de runtime con permisos
RUN mkdir -p logs && chmod -R 755 /app

# Usuario no-root (Render-compatible) — Playwright image typically has 'pwuser', switch if needed
# Create automiq user and chown to be consistent with previous image
RUN useradd --create-home --shell /bin/bash automiq || true
RUN chown -R automiq:automiq /app || true
USER automiq

# Exponer puerto (Render lo lee de $PORT, pero declaramos el default)
EXPOSE 8000

# Healthcheck nativo de Docker
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:${PORT:-8000}/healthz || exit 1

# Comando de inicio
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
