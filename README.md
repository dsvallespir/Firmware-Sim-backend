# Backend - Firmware Academy Platform

## ⚠️ Requisito crítico: Python 3.12

> **IMPORTANTE:** Este backend **NO es compatible con Python 3.14** (ni con versiones superiores a 3.13).
>
> Las dependencias `pydantic-core` y `asyncpg` requieren compilar extensiones nativas con `pyo3`,
> cuya versión incluida (`0.22.2`) soporta hasta **Python 3.13** como máximo.
>
> Usar `python3 -m venv .venv` en un sistema donde el Python por defecto sea 3.14
> causará errores como:
> ```
> error: the configured Python interpreter version (3.14) is newer than PyO3's maximum supported version (3.13)
> Failed to build installable wheels for: asyncpg, pydantic-core
> ```

---

## Requisitos del sistema

| Herramienta | Versión requerida |
|---|---|
| Python | **3.12** (recomendado) o 3.11 / 3.13 |
| PostgreSQL | 14+ (vía Docker) |
| Docker | 24+ |

---

## Instalación

### 1. Verificar la versión de Python disponible

```bash
python3.12 --version
```

Si no está instalado:
```bash
sudo apt install python3.12 python3.12-venv
```

### 2. Crear el entorno virtual con Python 3.12 explícitamente

```bash
# ✅ Correcto
python3.12 -m venv .venv

# ❌ Incorrecto si el Python por defecto del sistema es 3.14
python3 -m venv .venv
```

### 3. Activar el entorno e instalar dependencias

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### 4. Levantar el servidor

```bash
uvicorn app.main:app --reload
```

El servidor queda disponible en: `http://localhost:8000`  
Documentación interactiva: `http://localhost:8000/docs`

---

## Migraciones (Alembic)

```bash
source .venv/bin/activate
alembic upgrade head
```

---

## Base de datos (PostgreSQL via Docker)

Desde la raíz del proyecto `platform/`:

```bash
docker compose up -d db
```

---

## Variables de entorno

Copiar el archivo de ejemplo y ajustar los valores:

```bash
cp .env.example .env
```

---

## Tests

```bash
source .venv/bin/activate
pytest
```

---

## Solución de problemas frecuentes

### `Failed building wheel for pydantic-core / asyncpg`

**Causa:** El venv fue creado con Python 3.14+.  
**Solución:**
```bash
rm -rf .venv
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### `ModuleNotFoundError: No module named 'app'`

Asegurarse de ejecutar `uvicorn` desde el directorio `backend/` con el venv activo.

### Advertencias de paquetes ROS (`jinja2`, `setuptools`, `typeguard`)

Son dependencias del sistema operativo (ROS 2), no afectan al backend. Se pueden ignorar.
