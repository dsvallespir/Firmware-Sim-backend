# ============================================================
# Dockerfile - Backend FastAPI
# ============================================================
# Multi-stage build para imagen de producción pequeña
#
# Etapa 1: Instalar dependencias
# Etapa 2: Copiar solo lo necesario
#
# Imagen base: python:3.12-slim (Debian slim, ~150MB)
# ¿Por qué slim y no alpine?
# - alpine usa musl libc en vez de glibc
# - Muchas dependencias Python (numpy, etc.) tienen problemas con musl
# - slim es un buen balance entre tamaño y compatibilidad

FROM python:3.12-slim AS base

# Evitar prompts interactivos durante apt-get
ENV DEBIAN_FRONTEND=noninteractive
# No generar archivos .pyc (innecesarios en Docker)
ENV PYTHONDONTWRITEBYTECODE=1
# No buffear stdout/stderr (ver logs en tiempo real)
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# ----------------------------------------------------------
# Etapa de dependencias
# ----------------------------------------------------------
FROM base AS dependencies

# Instalar dependencias del sistema necesarias para compilar
# libpq-dev: cliente PostgreSQL (necesario para asyncpg)
# gcc: compilador C (necesario para algunas dependencias Python)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copiar solo requirements primero (cache de Docker layers)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ----------------------------------------------------------
# Etapa final
# ----------------------------------------------------------
FROM base AS final

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# CORRECCIÓN: Usar la URL oficial del script de instalación de arduino-cli
RUN curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | sh

# Ahora sí va a encontrar el binario instalado en /usr/local/bin
RUN arduino-cli config init

# Copiar dependencias instaladas desde la etapa anterior
COPY --from=dependencies /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=dependencies /usr/local/bin /usr/local/bin

COPY . .

# Puerto del servidor
EXPOSE 8000

# El resto queda exactamente igual...
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import httpx; import os; port = os.getenv('PORT', '8000'); httpx.get(f'http://localhost:{port}/api/health')" || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 4"]
