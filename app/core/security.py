"""
============================================================
security.py - Utilidades de seguridad (JWT + Password Hashing)
============================================================

Este módulo centraliza:
1. Hashing de contraseñas con bcrypt
2. Generación y verificación de JWT tokens
3. Dependency para obtener el usuario actual desde el token

¿Por qué bcrypt?
- Algoritmo diseñado específicamente para passwords
- Incluye salt automático (previene rainbow tables)
- Cost factor configurable (más lento = más seguro)
- Estándar de la industria

¿Por qué JWT?
- Stateless: el servidor no necesita almacenar sesiones
- Autocontenido: el token lleva la info del usuario
- Escalable: funciona con múltiples servidores sin sticky sessions
- Estándar: interoperable con cualquier frontend

IMPORTANTE sobre seguridad:
- ACCESS_TOKEN: corta duración (30 min), se envía en cada request
- REFRESH_TOKEN: larga duración (7 días), solo para renovar access
- SECRET_KEY: DEBE ser un valor random largo en producción
- Nunca almacenar tokens en localStorage (vulnerable a XSS)
- Preferir httpOnly cookies para el refresh token
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db


# ----------------------------------------------------------
# Password Hashing
# ----------------------------------------------------------
# Usamos bcrypt directamente (passlib no es compatible con bcrypt>=4).
# bcrypt incluye salt automático en el hash resultante.
_BCRYPT_ROUNDS = 12  # cost factor: 2^12 iteraciones


def hash_password(password: str) -> str:
    """
    Genera el hash bcrypt de una contraseña en texto plano.
    El salt se genera automáticamente y se incluye en el hash.
    """
    return bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(rounds=_BCRYPT_ROUNDS),
    ).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifica una contraseña contra su hash.
    checkpw usa comparación timing-safe para prevenir timing attacks.
    """
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


# ----------------------------------------------------------
# JWT Token Management
# ----------------------------------------------------------
def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    Crea un JWT access token.
    
    Args:
        data: payload del token (típicamente {"sub": user_id})
        expires_delta: duración custom, o usa el default de config
    
    Returns:
        Token JWT firmado como string
    
    El token contiene:
    - sub: subject (user_id)
    - exp: timestamp de expiración
    - type: "access" para distinguir de refresh tokens
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(data: dict) -> str:
    """
    Crea un JWT refresh token con mayor duración.
    Se usa exclusivamente para obtener nuevos access tokens.
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict:
    """
    Decodifica y verifica un JWT token.
    
    Raises:
        JWTError: si el token es inválido, expirado o manipulado
    
    Returns:
        Payload decodificado como diccionario
    """
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


# ----------------------------------------------------------
# OAuth2 scheme para extraer el token del header Authorization
# ----------------------------------------------------------
# Espera: Authorization: Bearer <token>
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    """
    Dependency que extrae y valida el usuario actual desde el JWT.
    
    Flujo:
    1. Extrae el token del header Authorization: Bearer <token>
    2. Decodifica el JWT y obtiene el user_id del campo "sub"
    3. Busca el usuario en la BD
    4. Retorna el usuario o lanza 401
    
    Uso en endpoints:
        @router.get("/me")
        async def get_me(user = Depends(get_current_user)):
            return user
    """
    # Import aquí para evitar circular imports
    from app.models.user import User

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido o expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_token(token)
        user_id: str = payload.get("sub")
        token_type: str = payload.get("type")

        # Solo aceptamos access tokens en endpoints normales
        if user_id is None or token_type != "access":
            raise credentials_exception

    except JWTError:
        raise credentials_exception

    # Buscar usuario en la BD
    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cuenta desactivada",
        )

    return user


async def get_optional_user(
    token: Optional[str] = Depends(OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)),
    db: AsyncSession = Depends(get_db),
):
    """
    Dependency opcional: retorna el usuario si hay token válido, o None si no.
    Usar en endpoints públicos que muestran info extra a usuarios autenticados.
    """
    if not token:
        return None
    try:
        from app.models.user import User
        payload = decode_token(token)
        user_id = payload.get("sub")
        if not user_id or payload.get("type") != "access":
            return None
        result = await db.execute(select(User).where(User.id == int(user_id)))
        user = result.scalar_one_or_none()
        return user if (user and user.is_active) else None
    except Exception:
        return None


async def get_current_admin(user=Depends(get_current_user)):
    """
    Dependency que verifica que el usuario actual es administrador.
    Admins deben tener email verificado y cuenta activa.
    """
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requieren permisos de administrador",
        )
    return user


async def get_current_verified_user(user=Depends(get_current_user)):
    """
    Dependency que verifica que el usuario tiene email verificado
    y cuenta en estado 'active'. Usar en endpoints que requieren
    acceso completo (cursos, contenido, pagos, etc.).
    
    Cuentas en PendingVerification pueden autenticarse (get_current_user)
    pero NO pueden acceder a recursos protegidos por esta dependency.
    """
    from app.models.user import ACCOUNT_STATUS_ACTIVE

    if user.account_status != ACCOUNT_STATUS_ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Necesitás verificar tu email para acceder a esta función",
        )
    return user
