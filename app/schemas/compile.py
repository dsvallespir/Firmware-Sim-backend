"""
============================================================
compile.py - Schemas para el endpoint de compilación Arduino
============================================================

Define los modelos Pydantic para:
- CompileRequest: código fuente + board seleccionado
- CompileResponse: resultado de compilación (.hex, stdout, uso de memoria)

Seguridad:
- Nombres de archivo validados con regex estricta
- Contenido limitado a 100 KB por archivo
- Máximo 20 archivos por request
- Board FQBN validado contra allowlist en el router
"""

from pydantic import BaseModel, Field
from typing import Optional


class SketchFile(BaseModel):
    """Un archivo del sketch Arduino (.ino, .h, .cpp)."""
    name: str = Field(
        ...,
        pattern=r'^[a-zA-Z0-9_][a-zA-Z0-9_.\-]*$',
        max_length=100,
        description="Nombre del archivo (solo alfanuméricos, _, ., -)",
        examples=["sketch.ino", "config.h", "utils.cpp"],
    )
    content: str = Field(
        ...,
        max_length=102400,  # 100 KB máximo por archivo
        description="Contenido del archivo fuente",
    )


class CompileRequest(BaseModel):
    """Request de compilación: archivos fuente + board target."""
    files: list[SketchFile] = Field(
        ...,
        min_length=1,
        max_length=20,
        description="Lista de archivos del sketch",
    )
    board_fqbn: str = Field(
        default="arduino:avr:uno",
        max_length=100,
        description="FQBN del board target (ej: arduino:avr:uno)",
    )
    libraries: list[str] = Field(
        default=[],
        max_length=10,
        description="Nombres de bibliotecas Arduino a instalar antes de compilar (máx. 10)",
        examples=[["DHT sensor library", "Adafruit GFX Library"]],
    )

class CompileResponse(BaseModel):
    """Resultado de compilación."""
    success: bool
    hex_content: Optional[str] = None
    binary_content: Optional[str] = None  # base64 para RP2040/ESP32
    binary_type: Optional[str] = None     # 'hex', 'bin', 'uf2'
    stdout: str = ""
    stderr: str = ""
    error: Optional[str] = None
    flash_used: Optional[int] = None      # bytes de Flash usados
    flash_total: Optional[int] = None     # bytes de Flash totales
    ram_used: Optional[int] = None        # bytes de RAM usados
    ram_total: Optional[int] = None       # bytes de RAM totales


class BoardInfo(BaseModel):
    """Info de un board soportado."""
    fqbn: str
    name: str
    variant: str  # 'uno', 'mega', 'tiny85'


class BoardsResponse(BaseModel):
    """Lista de boards soportados."""
    boards: list[BoardInfo]
