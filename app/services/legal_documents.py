"""
============================================================
legal_documents.py - Contenido legal centralizado
============================================================

Fuente de verdad para todos los documentos legales de la plataforma.

Diseño:
- Cada documento tiene versión, título, fecha y contenido Markdown
- Las versiones viven en config.py (TERMS_VERSION, etc.)
- El contenido se renderiza en el frontend con el MarkdownRenderer
- Al cambiar versión en config → los usuarios deben reaceptar

¿Por qué no base de datos?
- Los textos legales cambian con deploys, no con UI de admin
- Versionados junto al código fuente
- Sin latencia de DB para contenido estático
- Fáciles de revisar en git diff

¿Por qué no archivos .md sueltos?
- Los datos del proveedor se inyectan desde config (una sola fuente)
- Permite validar versiones consistentes entre contenido y config
- Import directo sin I/O de filesystem
"""

from app.core.config import settings


def _provider(key: str) -> str:
    """Shortcut para datos del proveedor desde config."""
    return getattr(settings, key)


# ==============================================================
# TÉRMINOS Y CONDICIONES
# ==============================================================
def get_terms_content() -> dict:
    return {
        "type": "terms",
        "version": settings.TERMS_VERSION,
        "title": "Términos y Condiciones",
        "last_updated": "2026-03-23",
        "content": f"""# Términos y Condiciones

**Versión:** {settings.TERMS_VERSION}
**Última actualización:** 23 de marzo de 2026

---

## 1. Identificación del Proveedor

| Dato | Detalle |
|------|---------|
| **Razón Social** | {_provider('PROVIDER_LEGAL_NAME')} |
| **CUIT** | {_provider('PROVIDER_TAX_ID')} |
| **Domicilio** | {_provider('PROVIDER_ADDRESS')} |
| **Email de contacto** | {_provider('PROVIDER_EMAIL')} |
| **Soporte** | {_provider('SUPPORT_EMAIL')} |

---

## 2. Objeto del Servicio

{_provider('PROVIDER_NAME')} es una plataforma de educación online que ofrece cursos de desarrollo de software, firmware y sistemas embebidos. Al registrarte y utilizar la plataforma, aceptás estos Términos y Condiciones.

---

## 3. Registro y Acceso

- Para acceder al contenido pago debés crear una cuenta con un email válido.
- Sos responsable de la veracidad de tus datos y de la seguridad de tu contraseña.
- Cada cuenta es personal e intransferible.
- {_provider('PROVIDER_NAME')} se reserva el derecho de suspender o cancelar cuentas que violen estos términos.

---

## 4. Uso Personal e Intransferible

- El acceso a los cursos adquiridos es personal y exclusivo del titular de la cuenta.
- Queda prohibido compartir credenciales, redistribuir, copiar, grabar o reproducir el contenido de los cursos por cualquier medio.
- El incumplimiento de esta cláusula podrá resultar en la suspensión inmediata de la cuenta sin derecho a reembolso.

---

## 5. Propiedad Intelectual

Todo el contenido de la plataforma — incluyendo pero no limitado a textos, código fuente, videos, imágenes, diseños, ejercicios y material didáctico — es propiedad exclusiva de {_provider('PROVIDER_LEGAL_NAME')} o de sus respectivos autores, y está protegido por las leyes argentinas e internacionales de propiedad intelectual.

No se transfiere ningún derecho de propiedad intelectual al usuario. Se otorga únicamente una licencia limitada, personal, no exclusiva, revocable y no transferible para uso educativo personal.

---

## 6. Precios y Pagos

- Los precios de los cursos se expresan en **{_provider('PRICES_CURRENCY')}** (Pesos Argentinos).
- {"Los precios publicados **incluyen IVA**." if settings.PRICES_INCLUDE_TAXES else "Los precios publicados **no incluyen IVA**, el cual se adicionará al momento del pago."}
- Los pagos se procesan a través de **Mercado Pago**, sujeto a los términos y condiciones de dicha plataforma.
- {_provider('PROVIDER_NAME')} no almacena datos de tarjetas de crédito ni información financiera directamente.
- Los precios pueden modificarse en cualquier momento. Los cursos ya adquiridos no se ven afectados por cambios de precio posteriores.

---

## 7. Derecho de Arrepentimiento

De acuerdo con el artículo 34 de la Ley 24.240 de Defensa del Consumidor de la República Argentina, el usuario tiene derecho a revocar la aceptación de la compra dentro de los **{settings.WITHDRAWAL_PERIOD_DAYS} (diez) días corridos** contados a partir de la fecha de compra.

Para ejercer este derecho:

1. Ingresá a tu cuenta y dirigite a la sección "Mis Compras" o "Derecho de Arrepentimiento".
2. Completá el formulario de solicitud indicando el motivo (opcional).
3. La solicitud será procesada en un plazo máximo de **10 días hábiles**.
4. El reembolso se realizará por el mismo medio de pago utilizado.

**Excepciones:** El derecho de arrepentimiento no aplica si el usuario ha consumido más del 30% del contenido del curso, ya que se considera que el servicio ha sido sustancialmente utilizado.

Contacto para arrepentimiento: **{_provider('SUPPORT_EMAIL')}**

---

## 8. Devoluciones

Fuera del plazo de arrepentimiento legal, {_provider('PROVIDER_NAME')} podrá evaluar solicitudes de devolución caso por caso, sin que esto constituya una obligación.

---

## 9. Limitación de Responsabilidad

- {_provider('PROVIDER_NAME')} no garantiza que el contenido de los cursos sea adecuado para todo propósito profesional o comercial.
- No nos responsabilizamos por el uso que el usuario haga del conocimiento adquirido.
- No garantizamos disponibilidad ininterrumpida del servicio, aunque haremos esfuerzos razonables para mantenerlo operativo.
- La responsabilidad máxima de {_provider('PROVIDER_NAME')} se limita al monto efectivamente pagado por el usuario por el curso en cuestión.

---

## 10. Modificaciones

{_provider('PROVIDER_NAME')} se reserva el derecho de modificar estos Términos y Condiciones. Los cambios serán notificados a los usuarios mediante la plataforma y/o email. El uso continuado de la plataforma después de publicados los cambios implica la aceptación de los nuevos términos.

---

## 11. Jurisdicción y Ley Aplicable

Estos Términos y Condiciones se rigen por las leyes de la **República Argentina**. Para cualquier controversia derivada de estos términos, las partes se someten a la jurisdicción de los tribunales ordinarios de la **Ciudad Autónoma de Buenos Aires**, renunciando a cualquier otro fuero que pudiera corresponder.

---

## 12. Contacto

Para consultas sobre estos términos: **{_provider('PROVIDER_EMAIL')}**
Para soporte técnico: **{_provider('SUPPORT_EMAIL')}**
""",
    }


# ==============================================================
# POLÍTICA DE PRIVACIDAD
# ==============================================================
def get_privacy_content() -> dict:
    return {
        "type": "privacy",
        "version": settings.PRIVACY_VERSION,
        "title": "Política de Privacidad",
        "last_updated": "2026-03-23",
        "content": f"""# Política de Privacidad

**Versión:** {settings.PRIVACY_VERSION}
**Última actualización:** 23 de marzo de 2026

---

## 1. Responsable del Tratamiento

| Dato | Detalle |
|------|---------|
| **Razón Social** | {_provider('PROVIDER_LEGAL_NAME')} |
| **CUIT** | {_provider('PROVIDER_TAX_ID')} |
| **Domicilio** | {_provider('PROVIDER_ADDRESS')} |
| **Email** | {_provider('PROVIDER_EMAIL')} |

---

## 2. Datos que Recopilamos

### Datos proporcionados por el usuario:
- **Datos de registro:** nombre de usuario, dirección de email, contraseña (almacenada como hash, nunca en texto plano).
- **Datos de uso:** progreso en cursos, lecciones completadas.
- **Datos de pago:** procesados por Mercado Pago. {_provider('PROVIDER_NAME')} no almacena números de tarjeta ni datos financieros sensibles.

### Datos recopilados automáticamente:
- **Dirección IP:** para seguridad, prevención de fraude y auditoría.
- **User-Agent del navegador:** para seguridad y compatibilidad.
- **Tokens de sesión:** almacenados en localStorage para mantener la sesión activa.
- **Registros de auditoría:** eventos de seguridad (login, registro, cambios de cuenta).

---

## 3. Finalidades del Tratamiento

Utilizamos tus datos personales para:

1. **Prestación del servicio:** gestionar tu cuenta, darte acceso a los cursos adquiridos, registrar tu progreso.
2. **Seguridad:** prevenir accesos no autorizados, detectar fraude, proteger la plataforma.
3. **Comunicaciones:** enviarte emails transaccionales (verificación de cuenta, confirmaciones de compra, recuperación de contraseña).
4. **Cumplimiento legal:** responder a obligaciones legales y requerimientos de autoridades competentes.
5. **Mejora del servicio:** analizar uso agregado de la plataforma para mejorar la experiencia.

---

## 4. Proveedores y Terceros

Compartimos datos con los siguientes terceros exclusivamente para la prestación del servicio:

| Proveedor | Datos | Propósito |
|-----------|-------|-----------|
| **Mercado Pago** | Email, monto | Procesamiento de pagos |
| **Proveedor de email** (SMTP) | Email | Envío de emails transaccionales |
| **Proveedor de hosting** | Datos técnicos | Infraestructura de servidores |

No vendemos, alquilamos ni compartimos tus datos personales con terceros para fines de marketing.

---

## 5. Conservación de Datos

- **Datos de cuenta:** mientras la cuenta esté activa, más un período razonable después de la baja.
- **Datos de pago:** según los plazos legales y fiscales aplicables en Argentina.
- **Registros de auditoría:** se conservan por un período mínimo de 2 años.
- **Datos anonimizados:** podrán conservarse indefinidamente para análisis estadístico.

---

## 6. Derechos del Usuario

De acuerdo con la Ley 25.326 de Protección de Datos Personales de Argentina, tenés derecho a:

- **Acceso:** solicitar qué datos personales tenemos sobre vos.
- **Rectificación:** corregir datos inexactos o incompletos.
- **Supresión:** solicitar la eliminación de tus datos (sujeto a obligaciones legales de retención).
- **Oposición:** oponerte al tratamiento de tus datos para determinados fines.

Para ejercer estos derechos, escribinos a: **{_provider('SUPPORT_EMAIL')}**

La DIRECCIÓN NACIONAL DE PROTECCIÓN DE DATOS PERSONALES, órgano de control de la Ley 25.326, tiene la atribución de atender las denuncias y reclamos que se interpongan en relación con el incumplimiento de las normas sobre protección de datos personales.

---

## 7. Seguridad

Implementamos medidas técnicas y organizativas para proteger tus datos:

- Contraseñas almacenadas con hash bcrypt (nunca en texto plano)
- Comunicaciones cifradas (HTTPS)
- Verificación de email obligatoria
- Protección contra ataques de fuerza bruta
- Rate limiting en endpoints sensibles
- Auditoría de eventos de seguridad

---

## 8. Menores de Edad

La plataforma está destinada a personas mayores de 18 años. No recopilamos intencionalmente datos de menores. Si detectamos que un menor se ha registrado, procederemos a eliminar su cuenta.

---

## 9. Modificaciones

Nos reservamos el derecho de actualizar esta política. Los cambios se comunicarán a través de la plataforma. La versión vigente siempre estará disponible en esta página.

---

## 10. Contacto

Para consultas sobre privacidad: **{_provider('SUPPORT_EMAIL')}**

Delegado de protección de datos: **{_provider('PROVIDER_EMAIL')}**
""",
    }


# ==============================================================
# POLÍTICA DE COOKIES
# ==============================================================
def get_cookies_content() -> dict:
    return {
        "type": "cookies",
        "version": settings.COOKIES_VERSION,
        "title": "Política de Cookies",
        "last_updated": "2026-03-23",
        "content": f"""# Política de Cookies y Almacenamiento Local

**Versión:** {settings.COOKIES_VERSION}
**Última actualización:** 23 de marzo de 2026

---

## 1. ¿Qué son las cookies y el almacenamiento local?

Las cookies son pequeños archivos que se almacenan en tu navegador. El almacenamiento local (localStorage) es un mecanismo similar que permite guardar datos en tu dispositivo.

---

## 2. Tecnologías que utilizamos

### Almacenamiento local (localStorage)

| Dato | Propósito | Duración |
|------|-----------|----------|
| **access_token** | Mantener tu sesión activa | 30 minutos |
| **refresh_token** | Renovar tu sesión sin reiniciar login | 7 días |
| **cookie_consent** | Recordar tu preferencia de cookies | Permanente |

### Cookies técnicas

| Cookie | Propósito | Tipo |
|--------|-----------|------|
| Cookies de seguridad (CAPTCHA) | Protección contra bots (Cloudflare Turnstile) | Estrictamente necesaria |

---

## 3. Tipos de cookies

### Estrictamente necesarias
Son esenciales para el funcionamiento de la plataforma. No se pueden desactivar. Incluyen tokens de sesión y protección contra bots.

### De preferencias
Almacenan tus preferencias (como la aceptación de este aviso). No recopilan información personal.

### Analíticas
Actualmente **no utilizamos cookies de analítica** de terceros. Si en el futuro incorporamos herramientas de análisis, actualizaremos esta política y te informaremos.

---

## 4. Control de cookies

Podés gestionar las cookies desde la configuración de tu navegador:

- **Chrome:** Configuración → Privacidad y seguridad → Cookies
- **Firefox:** Opciones → Privacidad y seguridad
- **Safari:** Preferencias → Privacidad

**Nota:** desactivar el almacenamiento local impedirá el funcionamiento correcto de la plataforma, ya que los tokens de sesión son necesarios para mantener tu login.

---

## 5. Contacto

Para consultas sobre nuestra política de cookies: **{_provider('SUPPORT_EMAIL')}**
""",
    }


# ==============================================================
# Mapa de documentos por tipo
# ==============================================================
LEGAL_DOCUMENTS = {
    "terms": get_terms_content,
    "privacy": get_privacy_content,
    "cookies": get_cookies_content,
}


def get_legal_document(doc_type: str) -> dict | None:
    """Obtiene un documento legal por tipo. Retorna None si no existe."""
    getter = LEGAL_DOCUMENTS.get(doc_type)
    return getter() if getter else None


def get_all_legal_documents() -> list[dict]:
    """Retorna todos los documentos legales (sin contenido completo)."""
    docs = []
    for getter in LEGAL_DOCUMENTS.values():
        doc = getter()
        docs.append({
            "type": doc["type"],
            "version": doc["version"],
            "title": doc["title"],
            "last_updated": doc["last_updated"],
        })
    return docs


def get_current_version(doc_type: str) -> str:
    """Retorna la versión vigente de un documento."""
    version_map = {
        "terms": settings.TERMS_VERSION,
        "privacy": settings.PRIVACY_VERSION,
        "cookies": settings.COOKIES_VERSION,
    }
    return version_map.get(doc_type, "unknown")
