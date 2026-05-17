"""
============================================================
database.py - Configuración de SQLAlchemy Async
============================================================

Usamos SQLAlchemy 2.0 con el driver asyncpg para PostgreSQL.

¿Por qué async?
- FastAPI es async por naturaleza
- asyncpg es el driver PostgreSQL más rápido para Python
- Evitamos bloquear el event loop en operaciones de BD

Componentes:
- engine: conexión al motor de BD (pool de conexiones)
- async_session_maker: fábrica de sesiones async
- Base: clase base para todos los modelos ORM
- get_db: dependency injection para obtener sesión en endpoints

IMPORTANTE sobre el connection pool:
- pool_size=20: máximo 20 conexiones simultáneas
- max_overflow=10: hasta 10 conexiones extra bajo carga
- Ajustar según el tráfico esperado
"""

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


# ----------------------------------------------------------
# Engine: pool de conexiones a PostgreSQL
# ----------------------------------------------------------
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,          # True para ver SQL en desarrollo (muy verboso)
    pool_size=20,        # Conexiones persistentes en el pool
    max_overflow=10,     # Conexiones extra cuando el pool está lleno
    pool_pre_ping=True,  # Verificar conexión antes de usarla (evita stale)
)


# ----------------------------------------------------------
# Session Factory
# ----------------------------------------------------------
# expire_on_commit=False evita que los objetos expiren al hacer commit,
# lo cual es necesario para retornarlos en responses después del commit.
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ----------------------------------------------------------
# Base declarativa para modelos ORM
# ----------------------------------------------------------
class Base(DeclarativeBase):
    """
    Clase base para todos los modelos SQLAlchemy.
    Todos los modelos en app/models/ heredan de esta clase.
    """
    pass


# ----------------------------------------------------------
# Dependency Injection: sesión de BD para endpoints
# ----------------------------------------------------------
async def get_db():
    """
    Generador que provee una sesión de BD a cada endpoint.
    
    Uso en un endpoint:
        @router.get("/items")
        async def get_items(db: AsyncSession = Depends(get_db)):
            ...
    
    El generador se encarga de:
    1. Crear la sesión
    2. Yield-earla al endpoint
    3. Cerrarla automáticamente al terminar (incluso si hay error)
    
    NOTA: No hacemos commit aquí. Cada endpoint es responsable
    de hacer commit explícito. Esto da control fino sobre
    transacciones.
    """
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()
