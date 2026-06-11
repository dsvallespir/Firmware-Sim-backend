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
# ----------------------------------------------------------
# Etapa final
# ----------------------------------------------------------
FROM base AS final

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    ca-certificates \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*
# Configurar rutas de datos explícitas para Arduino dentro de /app
ENV ARDUINO_DATA_DIR=/app/.arduino15
ENV ARDUINO_DOWNLOADS_DIR=/app/.arduino15/staging
ENV ARDUINO_USER_DIR=/app/Arduino

WORKDIR /app
# Copiar dependencias de Python primero (antes de tocar /usr/local/bin)
COPY --from=dependencies /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=dependencies /usr/local/bin /usr/local/bin

# CORRECCIÓN: Forzar la instalación de arduino-cli directamente en /usr/local/bin
RUN curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | BINDIR=/usr/local/bin sh

# Ahora el sistema lo va a encontrar de forma global sin importar el PATH
RUN arduino-cli config init

# =========================================================================
# NUEVA CORRECCIÓN: Descargar los índices e instalar las herramientas AVR
# =========================================================================
   
# Actualizar el índice de tarjetas de Arduino e instalar el core de AVR    
RUN arduino-cli core update-index
RUN arduino-cli core install arduino:avr

COPY . .

# Asegúrate de exponer el puerto correcto que leerá Railway
EXPOSE 8080

# Healthcheck corregido: Si falla la variable PORT, usa 8080.
# Además, cambiamos 'localhost' por '127.0.0.1' que es más rápido y directo en Docker.
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import httpx; import os; port = os.getenv('PORT', '8080'); httpx.get(f'http://127.0.0.1:{port}/api/health')" || exit 1

# Comando de inicio optimizado a 1 worker para estabilizar el proxy de Railway
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
