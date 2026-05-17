"""
============================================================
auth.py - Router de Autenticación (Endurecido)
============================================================

Endpoints:
- POST /api/auth/register           - Crear cuenta (PendingVerification)
- POST /api/auth/login              - Obtener tokens JWT
- POST /api/auth/refresh            - Renovar access token
- POST /api/auth/verify-email       - Verificar email con token
- POST /api/auth/resend-verification - Reenviar email de verificación
- GET  /api/auth/me                 - Obtener perfil del usuario actual
- GET  /api/auth/security-config    - Config pública para el frontend

Seguridad implementada:
- Rate limiting por IP en register, login, resend-verification
- CAPTCHA (Cloudflare Turnstile) en register y resend-verification
- Verificación obligatoria de email con token hasheado
- Bloqueo temporal por intentos fallidos de login
- Anti-enumeración: respuestas genéricas que no revelan si el email existe
- Validación robusta de contraseñas (longitud, comunes, contextuales)
- Bloqueo de emails temporales/desechables
- Auditoría de todos los eventos de seguridad
- Normalización de email (lowercase, trim)
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limiter import limiter
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
)
from app.models.user import (
    User,
    ACCOUNT_STATUS_PENDING,
    ACCOUNT_STATUS_ACTIVE,
    ACCOUNT_STATUS_SUSPENDED,
    ACCOUNT_STATUS_BLOCKED,
)
from app.models.security_audit_log import (
    EVENT_REGISTER,
    EVENT_REGISTER_BLOCKED,
    EVENT_LOGIN_SUCCESS,
    EVENT_LOGIN_FAILED,
    EVENT_LOGIN_BLOCKED,
    EVENT_VERIFICATION_SENT,
    EVENT_VERIFICATION_RESENT,
    EVENT_VERIFICATION_SUCCESS,
    EVENT_VERIFICATION_FAILED,
    EVENT_RESEND_BLOCKED,
    EVENT_CAPTCHA_FAILED,
)
from app.schemas.user import (
    UserCreate,
    UserLogin,
    UserResponse,
    TokenResponse,
    RefreshTokenRequest,
    VerifyEmailRequest,
    ResendVerificationRequest,
    MessageResponse,
    SecurityConfigResponse,
)
from app.services.audit_service import audit_log, get_client_ip
from app.services.captcha_service import verify_turnstile_token
from app.services.disposable_email_checker import is_disposable_email, normalize_email
from app.services.email_service import send_verification_email
from app.services.password_validator import validate_password
from app.services.token_service import (
    create_verification_token,
    verify_email_token,
    check_resend_allowed,
)

router = APIRouter()

# ----------------------------------------------------------
# Mensaje genérico anti-enumeración
# ----------------------------------------------------------
_REGISTER_SUCCESS_MSG = (
    "Si el email es válido, recibirás un mensaje con instrucciones "
    "para verificar tu cuenta."
)
_RESEND_SUCCESS_MSG = (
    "Si existe una cuenta pendiente con ese email, "
    "se envió un nuevo link de verificación."
)


# ----------------------------------------------------------
# GET /security-config - Config pública para el frontend
# ----------------------------------------------------------
@router.get("/security-config", response_model=SecurityConfigResponse)
async def get_security_config():
    """
    Retorna configuración de seguridad pública necesaria para el frontend.
    No expone secretos — solo site key y flags de habilitación.
    """
    return SecurityConfigResponse(
        turnstile_enabled=settings.TURNSTILE_ENABLED,
        turnstile_site_key=settings.TURNSTILE_SITE_KEY,
        password_min_length=settings.PASSWORD_MIN_LENGTH,
    )


# ----------------------------------------------------------
# POST /register - Crear cuenta nueva
# ----------------------------------------------------------
@router.post("/register", response_model=MessageResponse, status_code=201)
@limiter.limit(settings.RATE_LIMIT_REGISTER)
async def register(
    request: Request,
    user_data: UserCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Registra un nuevo usuario en estado PendingVerification.
    
    Flujo:
    1. Validar aceptación legal obligatoria
    2. Validar CAPTCHA
    3. Normalizar y validar email
    4. Validar contraseña
    5. Verificar duplicados (sin revelar info)
    6. Crear usuario en PendingVerification
    7. Registrar aceptación legal
    8. Generar token de verificación
    9. Enviar email de verificación
    10. Retornar mensaje genérico (anti-enumeración)
    """
    ip = get_client_ip(request)
    ua = request.headers.get("user-agent", "")

    # 1. Validar aceptación legal (backend — no confiar en frontend)
    if not user_data.terms_accepted or not user_data.privacy_accepted:
        from app.models.security_audit_log import EVENT_LEGAL_ACCEPTANCE_MISSING
        await audit_log(
            db, EVENT_LEGAL_ACCEPTANCE_MISSING, email=user_data.email,
            ip_address=ip, user_agent=ua, success=False,
            metadata={
                "terms": user_data.terms_accepted,
                "privacy": user_data.privacy_accepted,
            },
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Debés aceptar los Términos y Condiciones y la Política de Privacidad para registrarte.",
        )

    # 2. CAPTCHA
    captcha_ok = await verify_turnstile_token(user_data.captcha_token, ip)
    if not captcha_ok:
        await audit_log(
            db, EVENT_CAPTCHA_FAILED, email=user_data.email,
            ip_address=ip, user_agent=ua, success=False,
            metadata={"endpoint": "register"},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verificación de seguridad fallida. Intentá de nuevo.",
        )

    # 2. Normalizar email
    email = normalize_email(user_data.email)

    # Bloquear dominios desechables
    if is_disposable_email(email):
        await audit_log(
            db, EVENT_REGISTER_BLOCKED, email=email,
            ip_address=ip, user_agent=ua, success=False,
            metadata={"reason": "disposable_email"},
        )
        await db.commit()
        # Respuesta genérica — no revelar que detectamos el dominio
        return MessageResponse(message=_REGISTER_SUCCESS_MSG)

    # 3. Validar contraseña
    password_errors = validate_password(
        user_data.password,
        email=email,
        username=user_data.username,
    )
    if password_errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=password_errors,
        )

    # 4. Verificar si el email ya está registrado
    existing = await db.execute(
        select(User).where(User.email == email)
    )
    existing_user = existing.scalar_one_or_none()

    if existing_user:
        # Anti-enumeración: respuesta idéntica a registro exitoso
        await audit_log(
            db, EVENT_REGISTER_BLOCKED, email=email,
            user_id=existing_user.id, ip_address=ip, user_agent=ua,
            success=False, metadata={"reason": "email_exists"},
        )
        await db.commit()
        return MessageResponse(message=_REGISTER_SUCCESS_MSG)

    # 5. Crear usuario en PendingVerification
    user = User(
        email=email,
        username=user_data.username.strip(),
        hashed_password=hash_password(user_data.password),
        role="student",
        account_status=ACCOUNT_STATUS_PENDING,
        is_active=True,
    )
    db.add(user)
    await db.flush()  # Obtener user.id sin commit

    # 6. Registrar aceptación legal (atómico con creación de usuario)
    from app.models.legal_acceptance import LegalAcceptance
    from app.models.legal_acceptance import DOC_TYPE_TERMS, DOC_TYPE_PRIVACY
    for doc_type in (DOC_TYPE_TERMS, DOC_TYPE_PRIVACY):
        version_map = {"terms": settings.TERMS_VERSION, "privacy": settings.PRIVACY_VERSION}
        db.add(LegalAcceptance(
            user_id=user.id,
            document_type=doc_type,
            document_version=version_map[doc_type],
            ip_address=ip,
            user_agent=ua,
        ))

    # 7. Generar token de verificación
    token_raw = await create_verification_token(
        db, user.id, ip_address=ip,
    )

    # 7. Enviar email
    await send_verification_email(
        to_email=email,
        username=user.username,
        token=token_raw,
    )

    # 8. Auditoría
    await audit_log(
        db, EVENT_REGISTER, user_id=user.id, email=email,
        ip_address=ip, user_agent=ua, success=True,
    )
    await audit_log(
        db, EVENT_VERIFICATION_SENT, user_id=user.id, email=email,
        ip_address=ip, user_agent=ua, success=True,
    )

    await db.commit()

    return MessageResponse(message=_REGISTER_SUCCESS_MSG)


# ----------------------------------------------------------
# POST /verify-email - Verificar email con token
# ----------------------------------------------------------
@router.post("/verify-email", response_model=MessageResponse)
async def verify_email(
    request: Request,
    body: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Verifica el email de un usuario con el token enviado por email.
    
    - Token de un solo uso
    - Token con expiración
    - Cambia estado de PendingVerification → Active
    """
    ip = get_client_ip(request)
    ua = request.headers.get("user-agent", "")

    success, user, message = await verify_email_token(db, body.token)

    if not success:
        await audit_log(
            db, EVENT_VERIFICATION_FAILED, ip_address=ip,
            user_agent=ua, success=False,
            metadata={"reason": message},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )

    # Verificación exitosa
    await audit_log(
        db, EVENT_VERIFICATION_SUCCESS, user_id=user.id,
        email=user.email, ip_address=ip, user_agent=ua,
        success=True,
    )
    await db.commit()

    return MessageResponse(message="¡Email verificado! Ya podés iniciar sesión.")


# ----------------------------------------------------------
# POST /resend-verification - Reenviar email de verificación
# ----------------------------------------------------------
@router.post("/resend-verification", response_model=MessageResponse)
@limiter.limit(settings.RATE_LIMIT_RESEND_VERIFICATION)
async def resend_verification(
    request: Request,
    body: ResendVerificationRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Reenvía el email de verificación.
    
    Controles:
    - CAPTCHA obligatorio
    - Cooldown entre reenvíos
    - Límite por hora
    - Respuesta genérica (anti-enumeración)
    """
    ip = get_client_ip(request)
    ua = request.headers.get("user-agent", "")
    email = normalize_email(body.email)

    # 1. CAPTCHA
    captcha_ok = await verify_turnstile_token(body.captcha_token, ip)
    if not captcha_ok:
        await audit_log(
            db, EVENT_CAPTCHA_FAILED, email=email,
            ip_address=ip, user_agent=ua, success=False,
            metadata={"endpoint": "resend_verification"},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verificación de seguridad fallida. Intentá de nuevo.",
        )

    # 2. Buscar usuario
    result = await db.execute(
        select(User).where(User.email == email)
    )
    user = result.scalar_one_or_none()

    # Si no existe o ya verificado → respuesta genérica
    if not user or user.account_status != ACCOUNT_STATUS_PENDING:
        await audit_log(
            db, EVENT_RESEND_BLOCKED, email=email,
            ip_address=ip, user_agent=ua, success=False,
            metadata={"reason": "user_not_pending"},
        )
        await db.commit()
        return MessageResponse(message=_RESEND_SUCCESS_MSG)

    # 3. Verificar cooldown y límites
    allowed, reason = await check_resend_allowed(db, user.id)
    if not allowed:
        await audit_log(
            db, EVENT_RESEND_BLOCKED, user_id=user.id,
            email=email, ip_address=ip, user_agent=ua,
            success=False, metadata={"reason": reason},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=reason,
        )

    # 4. Generar nuevo token (revoca los anteriores)
    token_raw = await create_verification_token(
        db, user.id, ip_address=ip,
    )

    # 5. Enviar email
    await send_verification_email(
        to_email=email,
        username=user.username,
        token=token_raw,
    )

    # 6. Auditoría
    await audit_log(
        db, EVENT_VERIFICATION_RESENT, user_id=user.id,
        email=email, ip_address=ip, user_agent=ua, success=True,
    )
    await db.commit()

    return MessageResponse(message=_RESEND_SUCCESS_MSG)


# ----------------------------------------------------------
# POST /login - Autenticarse y obtener tokens
# ----------------------------------------------------------
@router.post("/login", response_model=TokenResponse)
@limiter.limit(settings.RATE_LIMIT_LOGIN)
async def login(
    request: Request,
    credentials: UserLogin,
    db: AsyncSession = Depends(get_db),
):
    """
    Autentica un usuario y retorna tokens JWT.
    
    Seguridad:
    - Mensaje genérico anti-enumeración
    - Bloqueo temporal por intentos fallidos
    - Auditoría de éxito y fallo
    - Verificación de estado de cuenta
    """
    ip = get_client_ip(request)
    ua = request.headers.get("user-agent", "")
    email = normalize_email(credentials.email)

    # Mensaje genérico para TODOS los errores de auth
    invalid_credentials = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Email o contraseña incorrectos",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Buscar usuario por email
    result = await db.execute(
        select(User).where(User.email == email)
    )
    user = result.scalar_one_or_none()

    # --- Usuario no existe ---
    if not user:
        await audit_log(
            db, EVENT_LOGIN_FAILED, email=email,
            ip_address=ip, user_agent=ua, success=False,
            metadata={"reason": "user_not_found"},
        )
        await db.commit()
        raise invalid_credentials

    # --- Bloqueo temporal por intentos fallidos ---
    if user.locked_until and datetime.now(timezone.utc) < user.locked_until:
        remaining = int((user.locked_until - datetime.now(timezone.utc)).total_seconds())
        await audit_log(
            db, EVENT_LOGIN_BLOCKED, user_id=user.id, email=email,
            ip_address=ip, user_agent=ua, success=False,
            metadata={"locked_seconds_remaining": remaining},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Cuenta bloqueada temporalmente. Intentá en {remaining // 60 + 1} minutos.",
        )

    # --- Verificar contraseña ---
    if not verify_password(credentials.password, user.hashed_password):
        # Incrementar contador de intentos fallidos
        user.failed_login_attempts += 1

        # Bloqueo temporal si se superó el máximo
        if user.failed_login_attempts >= settings.LOGIN_MAX_FAILED_ATTEMPTS:
            from datetime import timedelta
            user.locked_until = datetime.now(timezone.utc) + timedelta(
                minutes=settings.LOGIN_LOCKOUT_MINUTES
            )
            await audit_log(
                db, EVENT_LOGIN_BLOCKED, user_id=user.id, email=email,
                ip_address=ip, user_agent=ua, success=False,
                metadata={
                    "reason": "max_failed_attempts",
                    "attempts": user.failed_login_attempts,
                },
            )
        else:
            await audit_log(
                db, EVENT_LOGIN_FAILED, user_id=user.id, email=email,
                ip_address=ip, user_agent=ua, success=False,
                metadata={"attempts": user.failed_login_attempts},
            )

        await db.commit()
        raise invalid_credentials

    # --- Contraseña correcta: resetear contador ---
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = datetime.now(timezone.utc)

    # --- Verificar estado de cuenta ---
    if not user.is_active:
        await audit_log(
            db, EVENT_LOGIN_FAILED, user_id=user.id, email=email,
            ip_address=ip, user_agent=ua, success=False,
            metadata={"reason": "account_inactive"},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cuenta desactivada. Contacta soporte.",
        )

    if user.account_status == ACCOUNT_STATUS_BLOCKED:
        await audit_log(
            db, EVENT_LOGIN_FAILED, user_id=user.id, email=email,
            ip_address=ip, user_agent=ua, success=False,
            metadata={"reason": "account_blocked"},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cuenta bloqueada. Contacta soporte.",
        )

    if user.account_status == ACCOUNT_STATUS_SUSPENDED:
        await audit_log(
            db, EVENT_LOGIN_FAILED, user_id=user.id, email=email,
            ip_address=ip, user_agent=ua, success=False,
            metadata={"reason": "account_suspended"},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cuenta suspendida temporalmente. Contacta soporte.",
        )

    # --- Cuenta pendiente de verificación: permitir login limitado ---
    # El frontend redirigirá a la pantalla de verificación pendiente.
    # No bloqueamos el login porque el usuario necesita acceder al
    # flujo de reenvío. El acceso a recursos está controlado por
    # get_current_verified_user en los endpoints protegidos.

    # Generar tokens
    token_data = {"sub": str(user.id)}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    await audit_log(
        db, EVENT_LOGIN_SUCCESS, user_id=user.id, email=email,
        ip_address=ip, user_agent=ua, success=True,
        metadata={"account_status": user.account_status},
    )
    await db.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


# ----------------------------------------------------------
# POST /refresh - Renovar access token
# ----------------------------------------------------------
@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    body: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Renueva el access token usando un refresh token válido.
    Verifica que el usuario existe, está activo, y no está bloqueado.
    """
    try:
        payload = decode_token(body.refresh_token)
        user_id = payload.get("sub")
        token_type = payload.get("type")

        if not user_id or token_type != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token inválido",
            )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token inválido o expirado",
        )

    # Verificar usuario
    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesión inválida",
        )

    if user.account_status in (ACCOUNT_STATUS_BLOCKED, ACCOUNT_STATUS_SUSPENDED):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cuenta no disponible",
        )

    # Generar nuevos tokens
    token_data = {"sub": str(user.id)}
    return TokenResponse(
        access_token=create_access_token(token_data),
        refresh_token=create_refresh_token(token_data),
    )


# ----------------------------------------------------------
# GET /me - Obtener perfil del usuario actual
# ----------------------------------------------------------
@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """
    Retorna el perfil del usuario autenticado.
    Incluye account_status para que el frontend pueda redirigir
    a la pantalla de verificación si es necesario.
    """
    return current_user
