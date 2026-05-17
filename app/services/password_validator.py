"""
============================================================
password_validator.py - Validación de contraseñas seguras
============================================================

Implementa validación de contraseñas con criterio práctico:
- Longitud mínima configurable (default 10 chars)
- Longitud máxima (128 chars) para evitar DoS en hashing
- Lista de contraseñas comunes más usadas (top ~200)
- No impone reglas de UX absurdas (mayúsculas obligatorias, etc.)
- Permite passphrases largas sin restricciones de composición

Filosofía: NIST SP 800-63B recomienda longitud > complejidad.
"""

from app.core.config import settings

# ----------------------------------------------------------
# Top contraseñas más comunes (fuente: SecLists + Have I Been Pwned)
# Mantenemos un set pequeño pero efectivo. En producción se puede
# reemplazar con una búsqueda en HIBP API.
# ----------------------------------------------------------
COMMON_PASSWORDS = {
    "password", "123456", "12345678", "1234567890", "qwerty",
    "abc123", "monkey", "master", "dragon", "111111",
    "baseball", "iloveyou", "trustno1", "sunshine", "princess",
    "football", "charlie", "shadow", "michael", "password1",
    "password123", "welcome", "login", "admin", "qwerty123",
    "letmein", "photoshop", "1234", "12345", "123456789",
    "000000", "654321", "666666", "696969", "batman",
    "superman", "access", "hello", "charlie", "donald",
    "qwertyuiop", "passw0rd", "p@ssword", "p@ssw0rd",
    "starwars", "solo", "whatever", "freedom", "nothing",
    "computer", "master", "internet", "samsung", "google",
    "secret", "1q2w3e4r", "zaq1xsw2", "!@#$%^&*", "aa123456",
    "hunter2", "hunter", "test", "test123", "testing",
    "changeme", "temp", "temp123", "guest", "guest123",
    "default", "root", "toor", "pass", "pass123",
    "administrator", "firmware", "firmware123", "academy",
    "firmware.academy", "firmwareacademy", "cursofirmware",
    "student", "student123", "alumno", "alumno123",
    "contraseña", "contraseña123", "clave123", "hola123",
    "argentina", "buenosaires", "asdf1234", "qweasdzxc",
    "12341234", "abcabc", "aabbcc", "aaaa1111",
}


def validate_password(password: str, email: str = "", username: str = "") -> list[str]:
    """
    Valida una contraseña y retorna una lista de errores.
    Lista vacía = contraseña válida.
    
    Args:
        password: la contraseña a validar
        email: email del usuario (para detectar contraseña = email)
        username: username (para detectar contraseña = username)
    
    Returns:
        Lista de strings con los problemas encontrados
    """
    errors = []

    # Longitud mínima
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        errors.append(
            f"La contraseña debe tener al menos {settings.PASSWORD_MIN_LENGTH} caracteres"
        )

    # Longitud máxima (previene DoS en bcrypt)
    if len(password) > settings.PASSWORD_MAX_LENGTH:
        errors.append(
            f"La contraseña no puede superar {settings.PASSWORD_MAX_LENGTH} caracteres"
        )

    # No puede ser igual al email o username
    pw_lower = password.lower().strip()
    if email and pw_lower == email.lower().strip():
        errors.append("La contraseña no puede ser igual al email")
    if username and pw_lower == username.lower().strip():
        errors.append("La contraseña no puede ser igual al nombre de usuario")

    # Verificar contraseñas comunes
    if settings.PASSWORD_CHECK_COMMON and pw_lower in COMMON_PASSWORDS:
        errors.append("Esta contraseña es demasiado común. Elegí una más segura.")

    # No permitir contraseñas de solo espacios
    if password.strip() == "":
        errors.append("La contraseña no puede estar vacía o contener solo espacios")

    return errors
