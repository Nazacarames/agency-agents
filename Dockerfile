FROM mcr.microsoft.com/playwright/python:latest AS base

# Evita bytecode .pyc y fuerza stdout sin buffer (logs de Render)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Zona horaria de Argentina (seteada antes de instalar tzdata para evitar prompts)
ENV TZ=America/Buenos_Aires

# Dependencias ligeras: tzdata y curl (Playwright base incluye navegadores y libs)
# Usamos DEBIAN_FRONTEND=noninteractive para evitar prompts interactivos en CI
RUN apt-get update && apt-get install -y --no-install-recommends \
        tzdata \
        curl \
        ca-certificates \
        tesseract-ocr \
        tesseract-ocr-spa \
        libtesseract-dev \
    && rm -rf /var/lib/apt/lists/*

# Asegurar timezone configurado
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Instalar deps de Python primero (mejor cacheo de layers)
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copiar el código
COPY app/ ./app/
COPY data/ ./data/
COPY scripts/ ./scripts/

# Crear directorios de runtime con permisos
RUN mkdir -p logs && chmod -R 755 /app

# Usuario no-root (Playwright base suele incluir 'pwuser'; mantenemos compatibilidad creando automiq si falta)
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
