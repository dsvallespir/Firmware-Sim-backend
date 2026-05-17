"""
============================================================
email_service.py - Servicio de envío de emails
============================================================

Prioridad de envío:
  1. EMAIL_LOG_ONLY=True  → imprime a consola (desarrollo)
  2. RESEND_API_KEY set   → envía vía Resend REST API (httpx)
  3. SMTP_HOST set        → envía vía SMTP (aiosmtplib)
  4. fallback             → imprime a consola

Templates embebidos aquí por simplicidad. Si el proyecto crece,
migrar a archivos Jinja2 en templates/.

Funciones principales:
- send_verification_email(): envía link de verificación
- send_email(): función base para envío
"""

import logging
from typing import Optional

from app.core.config import settings

logger = logging.getLogger("email_service")


# ----------------------------------------------------------
# Templates de email (HTML mínimo, inline CSS)
# ----------------------------------------------------------
VERIFICATION_EMAIL_TEMPLATE = """
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
             background-color: #0f172a; color: #e2e8f0; padding: 40px 20px;">
  <div style="max-width: 480px; margin: 0 auto; background-color: #1e293b;
              border-radius: 12px; padding: 32px; border: 1px solid #334155;">
    <h1 style="color: #818cf8; font-size: 24px; margin: 0 0 8px 0;">
      🎓 Firmware Academy
    </h1>
    <h2 style="color: #f1f5f9; font-size: 18px; margin: 0 0 24px 0;">
      Verificá tu email
    </h2>
    <p style="color: #94a3b8; line-height: 1.6; margin: 0 0 24px 0;">
      Hola <strong style="color: #e2e8f0;">{username}</strong>,<br><br>
      Gracias por registrarte. Hacé clic en el botón para activar tu cuenta:
    </p>
    <a href="{verification_url}"
       style="display: inline-block; background-color: #6366f1; color: #ffffff;
              text-decoration: none; padding: 12px 28px; border-radius: 8px;
              font-weight: 600; font-size: 16px;">
      Verificar Email
    </a>
    <p style="color: #64748b; font-size: 13px; margin: 24px 0 0 0; line-height: 1.5;">
      Este link expira en {expire_hours} horas.<br>
      Si no creaste esta cuenta, podés ignorar este mensaje.<br><br>
      Si el botón no funciona, copiá este link en tu navegador:<br>
      <a href="{verification_url}" style="color: #818cf8; word-break: break-all;">
        {verification_url}
      </a>
    </p>
  </div>
</body>
</html>
"""


async def send_verification_email(
    to_email: str,
    username: str,
    token: str,
) -> bool:
    """
    Envía el email de verificación con el link de activación.
    
    Args:
        to_email: email destino
        username: nombre del usuario para personalizar
        token: token RAW (no el hash) para incluir en el link
    
    Returns:
        True si se envió/logueó correctamente
    """
    verification_url = (
        f"{settings.FRONTEND_URL}/verify-email?token={token}"
    )

    html_body = VERIFICATION_EMAIL_TEMPLATE.format(
        username=username,
        verification_url=verification_url,
        expire_hours=settings.VERIFICATION_TOKEN_EXPIRE_HOURS,
    )

    return await send_email(
        to_email=to_email,
        subject="Verificá tu email — Firmware Academy",
        html_body=html_body,
    )


async def send_email(
    to_email: str,
    subject: str,
    html_body: str,
    text_body: Optional[str] = None,
) -> bool:
    """
    Envía un email. Prioridad: log → Resend → SMTP → log fallback.

    Returns:
        True si se envió correctamente
    """
    if settings.EMAIL_LOG_ONLY or (not settings.RESEND_API_KEY and not settings.SMTP_HOST):
        _log_email(to_email, subject, html_body)
        return True

    if settings.RESEND_API_KEY:
        return await _send_via_resend(to_email, subject, html_body, text_body)

    return await _send_via_smtp(to_email, subject, html_body, text_body)


def _log_email(to_email: str, subject: str, html_body: str) -> None:
    logger.info(
        "\n"
        "═══════════════════════════════════════════════\n"
        "📧 EMAIL (modo desarrollo — no se envía)\n"
        "═══════════════════════════════════════════════\n"
        f"  Para:    {to_email}\n"
        f"  Asunto:  {subject}\n"
        "───────────────────────────────────────────────\n"
        f"{_extract_text_from_html(html_body)}\n"
        "═══════════════════════════════════════════════"
    )


async def _send_via_resend(
    to_email: str,
    subject: str,
    html_body: str,
    text_body: Optional[str],
) -> bool:
    """Envía usando la REST API de Resend (https://resend.com)."""
    import httpx

    payload: dict = {
        "from": f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>",
        "to": [to_email],
        "subject": subject,
        "html": html_body,
    }
    if text_body:
        payload["text"] = text_body

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        if response.status_code in (200, 201):
            data = response.json()
            logger.info(f"Email enviado via Resend a {to_email} — id={data.get('id')}")
            return True
        else:
            logger.error(
                f"Resend error {response.status_code} al enviar a {to_email}: {response.text}"
            )
            return False
    except Exception as e:
        logger.error(f"Excepción enviando email via Resend a {to_email}: {e}")
        return False


async def _send_via_smtp(
    to_email: str,
    subject: str,
    html_body: str,
    text_body: Optional[str],
) -> bool:
    """Envía usando SMTP con aiosmtplib."""
    try:
        import aiosmtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        message = MIMEMultipart("alternative")
        message["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
        message["To"] = to_email
        message["Subject"] = subject

        if text_body:
            message.attach(MIMEText(text_body, "plain", "utf-8"))
        message.attach(MIMEText(html_body, "html", "utf-8"))

        await aiosmtplib.send(
            message,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
            use_tls=settings.SMTP_USE_TLS,
        )
        logger.info(f"Email enviado via SMTP a {to_email}")
        return True

    except Exception as e:
        logger.error(f"Error enviando email via SMTP a {to_email}: {e}")
        return False


def _extract_text_from_html(html: str) -> str:
    """Extrae texto plano básico de HTML para logging en desarrollo."""
    import re
    # Quitar tags HTML
    text = re.sub(r"<[^>]+>", " ", html)
    # Colapsar espacios
    text = re.sub(r"\s+", " ", text).strip()
    # Limitar longitud para consola
    if len(text) > 500:
        text = text[:500] + "..."
    return text
