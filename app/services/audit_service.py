"""
============================================================
audit_service.py - Servicio de auditoría de seguridad
============================================================

Funciones para registrar eventos de seguridad en la tabla
security_audit_log. Diseñado para ser llamado desde los
endpoints de auth sin bloquear el flujo principal.

Uso:
    await audit_log(
        db=db,
        event_type=EVENT_LOGIN_SUCCESS,
        user_id=user.id,
        email=user.email,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
"""

import json
import logging
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Request

from app.models.security_audit_log import SecurityAuditLog

logger = logging.getLogger("audit")


async def audit_log(
    db: AsyncSession,
    event_type: str,
    *,
    user_id: Optional[int] = None,
    email: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    success: bool = True,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Registra un evento de seguridad.
    
    Diseñado para no lanzar excepciones: si falla el log,
    se loguea el error pero no se interrumpe el flujo.
    """
    try:
        entry = SecurityAuditLog(
            event_type=event_type,
            user_id=user_id,
            email=email,
            ip_address=ip_address,
            user_agent=user_agent[:512] if user_agent else None,
            success=success,
            metadata_json=json.dumps(metadata, default=str) if metadata else None,
        )
        db.add(entry)
        # Flush para persistir sin hacer commit (el endpoint hace commit)
        await db.flush()

        # También loguear a consola para visibilidad inmediata en desarrollo
        status_str = "✓" if success else "✗"
        logger.info(
            f"[AUDIT] {status_str} {event_type} | "
            f"email={email} user_id={user_id} ip={ip_address}"
        )
    except Exception as e:
        # Nunca interrumpir el flujo por un fallo de auditoría
        logger.error(f"Error registrando evento de auditoría: {e}")


def get_client_ip(request: Request) -> str:
    """
    Obtiene la IP real del cliente, considerando proxies (nginx, cloudflare).
    
    Orden de prioridad:
    1. CF-Connecting-IP (Cloudflare)
    2. X-Real-IP (Nginx)
    3. X-Forwarded-For (primer IP de la cadena)
    4. request.client.host (conexión directa)
    """
    # Cloudflare
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip.strip()

    # Nginx
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()

    # Proxy chain — tomar la primera IP (la del cliente original)
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()

    # Conexión directa
    return request.client.host if request.client else "unknown"
