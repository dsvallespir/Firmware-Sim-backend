"""
============================================================
Alembic env.py - Configuración de migraciones
============================================================

Este archivo configura Alembic para trabajar con SQLAlchemy async.
Alembic maneja las migraciones de esquema de la BD:
- Crear tablas nuevas
- Modificar columnas existentes
- Agregar índices
- etc.

Uso:
    # Crear una migración nueva
    alembic revision --autogenerate -m "descripción del cambio"
    
    # Aplicar migraciones
    alembic upgrade head
    
    # Revertir última migración
    alembic downgrade -1
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from app.core.config import settings
from app.core.database import Base

# Importar todos los modelos para que Alembic los detecte
from app.models.user import User
from app.models.course import Course, Module, Lesson
from app.models.enrollment import Enrollment
from app.models.progress import LessonProgress

# Config de Alembic
config = context.config

# Interpretar el archivo de logging de alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata de los modelos (para autogenerate)
target_metadata = Base.metadata

# Sobreescribir la URL de la BD desde nuestro config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)


def run_migrations_offline() -> None:
    """
    Ejecutar migraciones en modo 'offline'.
    Genera SQL sin conectarse a la BD.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Helper para ejecutar migraciones con una conexión."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """
    Ejecutar migraciones en modo async.
    Crea un engine async y ejecuta las migraciones.
    """
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Ejecutar migraciones online (async)."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
