"""
============================================================
captcha_service.py - Integración con Cloudflare Turnstile
============================================================

Cloudflare Turnstile es una alternativa moderna a reCAPTCHA:
- No requiere resolver puzzles visuales
- Privacidad del usuario (no tracking invasivo)
- Free tier generoso
- Verificación server-side obligatoria

Flujo:
1. Frontend renderiza el widget Turnstile
2. El usuario interactúa (generalmente invisible)
3. Turnstile genera un token (cf-turnstile-response)
4. Frontend envía el token al backend con el form
5. Backend valida el token contra la API de Cloudflare
6. Si es válido → continuar. Si no → rechazar.

Configuración:
- TURNSTILE_ENABLED: habilitar/deshabilitar por ambiente
- TURNSTILE_SITE_KEY: clave pública (para el frontend)
- TURNSTILE_SECRET_KEY: clave secreta (para validación server-side)

En desarrollo se puede usar con TURNSTILE_ENABLED=False para
saltear la validación, o usar las claves de test de Cloudflare.
"""

import logging
from typing import Optional

import httpx

from app.core.config import settings

logger = logging.getLogger("captcha")


async def verify_turnstile_token(
    token: Optional[str],
    remote_ip: Optional[str] = None,
) -> bool:
    """
    Valida un token de Cloudflare Turnstile contra la API.
    
    Args:
        token: el cf-turnstile-response del frontend
        remote_ip: IP del cliente (opcional, mejora la validación)
    
    Returns:
        True si el token es válido o si Turnstile está deshabilitado
    """
    # Si Turnstile está deshabilitado, siempre pasar
    if not settings.TURNSTILE_ENABLED:
        return True

    # Sin token → rechazar
    if not token or not token.strip():
        logger.warning("Turnstile: token vacío o ausente")
        return False

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                settings.TURNSTILE_VERIFY_URL,
                data={
                    "secret": settings.TURNSTILE_SECRET_KEY,
                    "response": token,
                    **({"remoteip": remote_ip} if remote_ip else {}),
                },
            )

        result = response.json()
        success = result.get("success", False)

        if not success:
            error_codes = result.get("error-codes", [])
            logger.warning(
                f"Turnstile: verificación fallida. "
                f"Errors: {error_codes}"
            )

        return success

    except httpx.TimeoutException:
        logger.error("Turnstile: timeout al verificar token")
        # En caso de timeout, ser permisivo para no bloquear usuarios legítimos
        # En producción high-security, cambiar a False
        return True

    except Exception as e:
        logger.error(f"Turnstile: error inesperado: {e}")
        return True  # Fail-open en caso de error de infraestructura
