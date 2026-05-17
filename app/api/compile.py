"""
compile.py — Compilation router (no auth, no rate limiting)
-----------------------------------------------------------
POST /api/compile/          Compile a sketch → returns .hex
GET  /api/compile/boards    List supported boards
GET  /api/compile/libraries List supported external libraries (grouped)
GET  /api/compile/status    arduino-cli health check
"""

import logging

from fastapi import APIRouter, HTTPException

from app.schemas.compile import (
    CompileRequest,
    CompileResponse,
    BoardInfo,
    BoardsResponse,
)
from app.services.arduino_compiler import (
    compiler_service,
    ALLOWED_BOARDS,
    ALLOWED_LIBRARIES,
)

logger = logging.getLogger("compile_router")
router = APIRouter()


# ---------------------------------------------------------------------------
# POST /compile/
# ---------------------------------------------------------------------------

@router.post("/", response_model=CompileResponse)
async def compile_sketch(body: CompileRequest):
    """
    Compile an Arduino sketch and return the Intel HEX binary.

    The frontend sends source files; the backend compiles with arduino-cli
    and returns the HEX for in-browser simulation with avr8js.
    """
    if not compiler_service.is_board_allowed(body.board_fqbn):
        allowed = ", ".join(ALLOWED_BOARDS.keys())
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported board: {body.board_fqbn}. Allowed: {allowed}",
        )

    if not any(f.name.endswith(".ino") for f in body.files):
        raise HTTPException(
            status_code=400,
            detail="At least one .ino file is required.",
        )

    # Validate libraries against allowlist
    if body.libraries:
        invalid = [lib for lib in body.libraries if lib not in ALLOWED_LIBRARIES]
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=f"Bibliotecas no permitidas: {invalid}. "
                       f"Consultar GET /api/compile/libraries para la lista válida.",
            )

    logger.info("Compiling %s (%d files, %d libraries)",
                body.board_fqbn, len(body.files), len(body.libraries))

    result = await compiler_service.compile(
        files=[{"name": f.name, "content": f.content} for f in body.files],
        board_fqbn=body.board_fqbn,
        libraries=body.libraries,
    )

    return CompileResponse(**result)


# ---------------------------------------------------------------------------
# GET /compile/boards
# ---------------------------------------------------------------------------

@router.get("/boards", response_model=BoardsResponse)
async def list_boards():
    """Return the list of boards supported for compilation."""
    boards = [
        BoardInfo(fqbn=fqbn, name=info["name"], variant=info["variant"])
        for fqbn, info in ALLOWED_BOARDS.items()
    ]
    return BoardsResponse(boards=boards)


# ---------------------------------------------------------------------------
# GET /compile/libraries
# ---------------------------------------------------------------------------

@router.get("/libraries")
async def list_libraries():
    """
    Return the allowed external libraries grouped by category.
    Each entry includes whether the library is currently installed.
    """
    return compiler_service.get_allowed_libraries()


# ---------------------------------------------------------------------------
# GET /compile/status
# ---------------------------------------------------------------------------

@router.get("/status")
async def compile_status():
    """Check arduino-cli availability."""
    return await compiler_service.verify_cli()
