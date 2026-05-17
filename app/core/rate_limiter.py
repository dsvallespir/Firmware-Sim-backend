"""
============================================================
rate_limiter.py - Rate limiting para FastAPI con slowapi
============================================================

Implementa rate limiting por IP para endpoints sensibles.
Usa slowapi (basado en limits) que se integra nativamente con FastAPI.

Endpoints protegidos:
- /auth/register: 5/hour por IP
- /auth/login: 10/minute por IP
- /auth/resend-verification: 3/minute por IP

Los límites son configurables desde settings.
El rate limiter se monta como middleware en main.py.

En caso de exceder el límite, devuelve HTTP 429 (Too Many Requests).
"""

import logging
from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi import Request

logger = logging.getLogger("rate_limiter")


def _get_real_ip(request: Request) -> str:
    """
    Extrae la IP real del cliente para rate limiting.
    Compatible con proxies (nginx, cloudflare).
    """
    # Cloudflare
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip.strip()

    # Nginx
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()

    # X-Forwarded-For
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()

    return get_remote_address(request)


# Instancia global del limiter
limiter = Limiter(
    key_func=_get_real_ip,
    default_limits=[],  # No aplicar límite global por defecto
    storage_uri="memory://",  # En producción usar Redis
)
