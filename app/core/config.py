"""
============================================================
config.py - Configuración centralizada de la aplicación
============================================================

Usa pydantic-settings para cargar variables de entorno.
Esto nos da:
- Validación automática de tipos
- Valores por defecto sensatos para desarrollo
- Un único punto de verdad para toda la configuración

Variables de entorno esperadas (ver .env.example):
- DATABASE_URL: connection string de PostgreSQL
- SECRET_KEY: clave para firmar JWT tokens
- CORS_ORIGINS: lista de orígenes permitidos
- SMTP_*: configuración de email
- TURNSTILE_*: Cloudflare Turnstile para captcha
- RATE_LIMIT_*: configuración de rate limiting

IMPORTANTE: Nunca commitear el .env real. Solo .env.example.
"""

from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Configuración de la aplicación.
    Las variables se cargan desde .env o variables de entorno del sistema.
    """

    # ----------------------------------------------------------
    # Base de datos
    # ----------------------------------------------------------
    DATABASE_URL: str = "postgresql+asyncpg://platform:platform123@localhost:5432/course_platform"

    # ----------------------------------------------------------
    # Autenticación JWT
    # ----------------------------------------------------------
    SECRET_KEY: str = "dev-secret-key-cambiar-en-produccion-abc123"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ----------------------------------------------------------
    # CORS
    # ----------------------------------------------------------
    CORS_ORIGINS: List[str] = [
        "http://localhost:5174",
        "http://localhost:3000",
        "http://127.0.0.1:5174",
        # Capacitor Android (androidScheme: 'https' → usa https://localhost)
        "https://localhost",
        "capacitor://localhost",
    ]

    # ----------------------------------------------------------
    # Mercado Pago (Argentina)
    # ----------------------------------------------------------
    MP_ACCESS_TOKEN: str = ""
    MP_PUBLIC_KEY: str = ""
    MP_WEBHOOK_SECRET_KEY: str = ""

    # ----------------------------------------------------------
    # Stripe (usuarios internacionales) — oculto, reservado
    # ----------------------------------------------------------
    STRIPE_SECRET_KEY: str = ""
    STRIPE_PUBLISHABLE_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""

    # ----------------------------------------------------------
    # Lemon Squeezy (usuarios internacionales — activo)
    # ----------------------------------------------------------
    LEMON_SQUEEZY_API_KEY: str = ""
    LEMON_SQUEEZY_STORE_ID: str = ""
    LEMON_SQUEEZY_WEBHOOK_SECRET: str = ""

    # ----------------------------------------------------------
    # Geolocalización / pricing fallback
    # ----------------------------------------------------------
    # País por defecto cuando no hay header cf-ipcountry (dev local).
    # En producción Cloudflare lo inyecta automáticamente.
    # Valores: "AR", "" (vacío = USD/LemonSqueezy)
    DEFAULT_PAYMENT_COUNTRY: str = ""

    # URLs públicas
    FRONTEND_URL: str = "http://localhost:5174"
    BACKEND_URL: str = "http://localhost:8001"

    # ----------------------------------------------------------
    # Contenido de cursos
    # ----------------------------------------------------------
    CONTENT_BASE_PATH: str = "../../"

    # Idioma por defecto y soportados para contenido de cursos
    # Cada Project* tendrá subcarpetas es/ y en/ con el contenido
    DEFAULT_CONTENT_LANG: str = "es"
    SUPPORTED_CONTENT_LANGS: list = ["es", "en"]

    # ----------------------------------------------------------
    # Email
    # ----------------------------------------------------------
    # Prioridad de envío:
    #   1. EMAIL_LOG_ONLY=True  → consola (desarrollo)
    #   2. RESEND_API_KEY set   → Resend (resend.com)
    #   3. SMTP_HOST set        → SMTP genérico
    #   4. fallback             → consola

    # Resend.com — API key (https://resend.com/api-keys)
    RESEND_API_KEY: str = ""

    # SMTP (opcional, alternativa a Resend)
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_USE_TLS: bool = True

    SMTP_FROM_EMAIL: str = "noreply@firmware.academy"
    SMTP_FROM_NAME: str = "Firmware Academy"
    # Si True, los emails se imprimen en consola (desarrollo)
    EMAIL_LOG_ONLY: bool = True

    # ----------------------------------------------------------
    # Verificación de email
    # ----------------------------------------------------------
    # Duración del token de verificación en horas
    VERIFICATION_TOKEN_EXPIRE_HOURS: int = 24
    # Cooldown entre reenvíos de verificación en segundos
    VERIFICATION_RESEND_COOLDOWN_SECONDS: int = 60
    # Máximo de reenvíos por hora
    VERIFICATION_MAX_RESENDS_PER_HOUR: int = 5

    # ----------------------------------------------------------
    # Cloudflare Turnstile (CAPTCHA)
    # ----------------------------------------------------------
    # Obtener en: https://dash.cloudflare.com/?to=/:account/turnstile
    # En desarrollo: usar las claves de test de Cloudflare:
    #   Site key:   1x00000000000000000000AA (siempre pasa)
    #   Secret key: 1x0000000000000000000000000000000AA (siempre pasa)
    TURNSTILE_ENABLED: bool = False
    TURNSTILE_SITE_KEY: str = "1x00000000000000000000AA"
    TURNSTILE_SECRET_KEY: str = "1x0000000000000000000000000000000AA"
    TURNSTILE_VERIFY_URL: str = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

    # ----------------------------------------------------------
    # Rate Limiting
    # ----------------------------------------------------------
    # Formato: "{count}/{period}" — period: second, minute, hour, day
    RATE_LIMIT_REGISTER: str = "5/hour"
    RATE_LIMIT_LOGIN: str = "10/minute"
    RATE_LIMIT_RESEND_VERIFICATION: str = "3/minute"
    RATE_LIMIT_GLOBAL: str = "100/minute"

    # ----------------------------------------------------------
    # Seguridad de contraseñas
    # ----------------------------------------------------------
    PASSWORD_MIN_LENGTH: int = 10
    PASSWORD_MAX_LENGTH: int = 128
    # Bloquear contraseñas extremadamente comunes
    PASSWORD_CHECK_COMMON: bool = True

    # ----------------------------------------------------------
    # Bloqueo por intentos fallidos de login
    # ----------------------------------------------------------
    # Cantidad de intentos fallidos antes de bloqueo temporal
    LOGIN_MAX_FAILED_ATTEMPTS: int = 5
    # Duración del bloqueo temporal en minutos
    LOGIN_LOCKOUT_MINUTES: int = 15

    # ----------------------------------------------------------
    # Dominios de email temporales/desechables
    # ----------------------------------------------------------
    # Bloquear registros con dominios desechables conocidos
    BLOCK_DISPOSABLE_EMAILS: bool = True

    # ----------------------------------------------------------
    # Datos del proveedor (información fiscal y comercial)
    # ----------------------------------------------------------
    PROVIDER_NAME: str = "Firmware Academy"
    PROVIDER_LEGAL_NAME: str = "Firmware Academy S.A.S."
    PROVIDER_TAX_ID: str = "30-12345678-9"  # CUIT — REEMPLAZAR
    PROVIDER_ADDRESS: str = "Buenos Aires, Argentina"  # REEMPLAZAR
    PROVIDER_EMAIL: str = "contacto@firmware.academy"
    SUPPORT_EMAIL: str = "soporte@firmware.academy"
    PROVIDER_WEBSITE: str = "https://firmware.academy"

    # ----------------------------------------------------------
    # Precios y facturación
    # ----------------------------------------------------------
    PRICES_CURRENCY: str = "ARS"
    PRICES_INCLUDE_TAXES: bool = True  # Precios con IVA incluido

    # ----------------------------------------------------------
    # Versionado de documentos legales
    # ----------------------------------------------------------
    # Incrementar al modificar documentos → fuerza reaceptación
    TERMS_VERSION: str = "v1.0"
    PRIVACY_VERSION: str = "v1.0"
    COOKIES_VERSION: str = "v1.0"

    # ----------------------------------------------------------
    # Derecho de arrepentimiento
    # ----------------------------------------------------------
    # Plazo en días según Ley 24.240 de Defensa del Consumidor
    WITHDRAWAL_PERIOD_DAYS: int = 10

    # ----------------------------------------------------------
    # Configuración de pydantic-settings
    # ----------------------------------------------------------
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


# Instancia singleton - importar desde aquí en toda la app
settings = Settings()
