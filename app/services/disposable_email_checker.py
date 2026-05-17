"""
============================================================
disposable_email_checker.py - Detección de emails temporales
============================================================

Lista de dominios de email desechables/temporales conocidos.
Se bloquean en el registro para reducir cuentas fraudulentas.

Configurable via BLOCK_DISPOSABLE_EMAILS en settings.

La lista se mantiene como un frozenset para búsquedas O(1).
En producción se podría consultar un servicio externo o
cargar desde un archivo actualizable.
"""

from app.core.config import settings

# ----------------------------------------------------------
# Dominios de email temporales más usados
# Fuente: https://github.com/disposable-email-domains/disposable-email-domains
# Mantenemos un subset razonable (~100). Para producción,
# cargar la lista completa desde archivo.
# ----------------------------------------------------------
DISPOSABLE_DOMAINS = frozenset({
    "10minutemail.com", "guerrillamail.com", "guerrillamail.de",
    "guerrillamail.net", "guerrillamail.org", "grr.la",
    "mailinator.com", "maildrop.cc", "dispostable.com",
    "yopmail.com", "yopmail.fr", "tempmail.com",
    "temp-mail.org", "throwaway.email", "getnada.com",
    "sharklasers.com", "guerrillamailblock.com", "tempail.com",
    "fakeinbox.com", "mailnesia.com", "trashmail.com",
    "trashmail.me", "trashmail.net", "trashy.email",
    "tempr.email", "discard.email", "mailcatch.com",
    "mytemp.email", "binkmail.com", "safetymail.info",
    "filzmail.com", "harakirimail.com", "crazymailing.com",
    "mailexpire.com", "tempinbox.com", "emailondeck.com",
    "33mail.com", "maildrop.cc", "mailnator.com",
    "trbvm.com", "mohmal.com", "anonbox.net",
    "jetable.org", "nwldx.com", "spam4.me",
    "trashmail.org", "tempmailaddress.com", "burnermail.io",
    "inboxkitten.com", "minutemail.com", "tempmailo.com",
    "emailfake.com", "generator.email", "fakemail.net",
    "throwawaymail.com", "getairmail.com", "mailsac.com",
    "guerrillamail.info", "tempmails.com", "tmpmail.net",
    "tmpmail.org", "mailtemp.info", "throwam.com",
    "spambox.us", "trash-mail.com", "mailzilla.com",
    "anonymbox.com", "coolimpool.org", "mail-temporaire.fr",
    "10minutemail.net", "10minutemail.org", "20minutemail.com",
    "mailtothis.com", "mytrashmail.com", "thankyou2010.com",
    "tempsky.com", "deadfake.com", "spamfree24.org",
})


def is_disposable_email(email: str) -> bool:
    """
    Verifica si un email pertenece a un dominio desechable.
    
    Args:
        email: dirección de email completa
    
    Returns:
        True si el dominio es desechable y el bloqueo está habilitado
    """
    if not settings.BLOCK_DISPOSABLE_EMAILS:
        return False

    try:
        domain = email.lower().strip().split("@")[1]
        return domain in DISPOSABLE_DOMAINS
    except (IndexError, AttributeError):
        return False


def normalize_email(email: str) -> str:
    """
    Normaliza un email para almacenamiento consistente:
    - trim whitespace
    - lowercase completo
    
    No hacemos normalización de aliases (+tag) porque eso
    puede ser legítimamente usado por usuarios reales.
    """
    return email.strip().lower()
