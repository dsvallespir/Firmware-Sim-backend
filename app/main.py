"""
============================================================
main.py - Punto de entrada de la aplicación FastAPI
============================================================
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import compile
from app.services.arduino_compiler import compiler_service

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("workbench")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Arduino Workbench API started")
    await compiler_service.populate_cache()
    yield
    logger.info("Arduino Workbench API stopped")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Arduino Workbench API",
    description="Compile & simulate Arduino / AVR sketches. No auth required.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(compile.router, prefix="/api/compile", tags=["Compile"])


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/api/health", tags=["System"])
async def health_check():
    return {"status": "ok", "service": "arduino-workbench"}
