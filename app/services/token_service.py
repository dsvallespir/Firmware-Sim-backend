"""
============================================================
token_service.py - Gestión de tokens de verificación
============================================================

Responsabilidades:
- Generar tokens criptográficamente seguros
- Almacenar solo el hash SHA-256 del token
- Revocar tokens anteriores al emitir uno nuevo
- Verificar tokens (sin timing leaks)
- Controlar cooldown y máximo de reenvíos

Flujo:
1. create_verification_token() → genera token raw + guarda hash
2. El token raw se envía por email
3. verify_token() → recibe token raw, calcula hash, busca en DB
4. Si coincide y es válido → marca used_at, retorna user_id

Seguridad:
- Token: 32 bytes random → 64 chars hexadecimal (256 bits de entropía)
- Solo se guarda SHA-256(token) en DB
- Comparación por hash (no timing-safe necesario: el atacante
  no ve el hash, solo envía el token raw)
"""

import hashlib
import secrets
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.verification_token import VerificationToken
from app.models.user import User

logger = logging.getLogger("token_service")


def _generate_token() -> Tuple[str, str]:
    """
    Genera un token seguro y su hash SHA-256.
    
    Returns:
        (token_raw, token_hash) — raw se envía por email, hash se guarda en DB
    """
    token_raw = secrets.token_hex(32)  # 64 chars, 256 bits de entropía
    token_hash = hashlib.sha256(token_raw.encode()).hexdigest()
    return token_raw, token_hash


def hash_token(token_raw: str) -> str:
    """Calcula el SHA-256 de un token raw."""
    return hashlib.sha256(token_raw.encode()).hexdigest()


async def create_verification_token(
    db: AsyncSession,
    user_id: int,
    token_type: str = "email_verification",
    ip_address: Optional[str] = None,
) -> str:
    """
    Crea un nuevo token de verificación, revocando los anteriores.
    
    Args:
        db: sesión de BD
        user_id: ID del usuario
        token_type: tipo de token
        ip_address: IP del request
    
    Returns:
        token_raw — para incluir en el email/link
    """
    # 1. Revocar tokens anteriores del mismo tipo para este usuario
    await _revoke_existing_tokens(db, user_id, token_type)

    # 2. Generar nuevo token
    token_raw, token_hash_value = _generate_token()

    expires_at = datetime.now(timezone.utc) + timedelta(
        hours=settings.VERIFICATION_TOKEN_EXPIRE_HOURS
    )

    new_token = VerificationToken(
        user_id=user_id,
        token_hash=token_hash_value,
        token_type=token_type,
        expires_at=expires_at,
        created_from_ip=ip_address,
    )
    db.add(new_token)
    await db.flush()

    logger.info(
        f"Token de {token_type} creado para user_id={user_id} "
        f"(expira: {expires_at.isoformat()})"
    )

    return token_raw


async def verify_email_token(
    db: AsyncSession,
    token_raw: str,
) -> Tuple[bool, Optional[User], str]:
    """
    Verifica un token de email y activa la cuenta si es válido.
    
    Args:
        db: sesión de BD
        token_raw: token recibido del link de verificación
    
    Returns:
        (success, user_or_none, message)
    """
    token_hash_value = hash_token(token_raw)

    # Buscar el token en DB
    result = await db.execute(
        select(VerificationToken).where(
            VerificationToken.token_hash == token_hash_value,
            VerificationToken.token_type == "email_verification",
        )
    )
    vtoken = result.scalar_one_or_none()

    if not vtoken:
        return False, None, "Token de verificación inválido"

    if vtoken.is_used:
        return False, None, "Este token ya fue utilizado"

    if vtoken.is_revoked:
        return False, None, "Este token fue reemplazado por uno más reciente"

    if vtoken.is_expired:
        return False, None, "El token de verificación expiró. Solicitá uno nuevo."

    # Token válido → marcar como usado
    now = datetime.now(timezone.utc)
    vtoken.used_at = now

    # Activar la cuenta del usuario
    user_result = await db.execute(
        select(User).where(User.id == vtoken.user_id)
    )
    user = user_result.scalar_one_or_none()

    if not user:
        return False, None, "Usuario no encontrado"

    # Solo activar si está en pending_verification
    from app.models.user import ACCOUNT_STATUS_PENDING, ACCOUNT_STATUS_ACTIVE
    if user.account_status == ACCOUNT_STATUS_PENDING:
        user.account_status = ACCOUNT_STATUS_ACTIVE
        user.email_verified_at = now

    return True, user, "Email verificado correctamente"


async def check_resend_allowed(
    db: AsyncSession,
    user_id: int,
    token_type: str = "email_verification",
) -> Tuple[bool, str]:
    """
    Verifica si se permite reenviar un token (cooldown + límite por hora).
    
    Returns:
        (allowed, reason_if_denied)
    """
    now = datetime.now(timezone.utc)

    # 1. Verificar cooldown: ¿cuándo fue el último token creado?
    result = await db.execute(
        select(VerificationToken)
        .where(
            VerificationToken.user_id == user_id,
            VerificationToken.token_type == token_type,
        )
        .order_by(VerificationToken.created_at.desc())
        .limit(1)
    )
    last_token = result.scalar_one_or_none()

    if last_token:
        cooldown = timedelta(seconds=settings.VERIFICATION_RESEND_COOLDOWN_SECONDS)
        if now - last_token.created_at < cooldown:
            remaining = int(
                (last_token.created_at + cooldown - now).total_seconds()
            )
            return False, f"Esperá {remaining} segundos antes de reenviar"

    # 2. Verificar límite por hora
    one_hour_ago = now - timedelta(hours=1)
    count_result = await db.execute(
        select(func.count(VerificationToken.id)).where(
            VerificationToken.user_id == user_id,
            VerificationToken.token_type == token_type,
            VerificationToken.created_at >= one_hour_ago,
        )
    )
    count = count_result.scalar() or 0

    if count >= settings.VERIFICATION_MAX_RESENDS_PER_HOUR:
        return False, "Superaste el límite de reenvíos. Intentá más tarde."

    return True, ""


async def _revoke_existing_tokens(
    db: AsyncSession,
    user_id: int,
    token_type: str,
) -> None:
    """Revoca todos los tokens activos del mismo tipo para un usuario."""
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(VerificationToken).where(
            VerificationToken.user_id == user_id,
            VerificationToken.token_type == token_type,
            VerificationToken.used_at.is_(None),
            VerificationToken.revoked_at.is_(None),
        )
    )
    active_tokens = result.scalars().all()

    for token in active_tokens:
        token.revoked_at = now
