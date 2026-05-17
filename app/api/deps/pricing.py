"""
============================================================
deps/pricing.py - Dependency de localización de precios
============================================================

Detecta el país del usuario a través del header cf-ipcountry
provisto automáticamente por Cloudflare, y produce un
PricingContext que expone:

    currency          → "ARS" | "USD"
    payment_processor → "mercadopago" | "stripe"
    country_code      → "AR" | "US" | "XX" | "MANUAL"
    is_manual_override→ True si el usuario forzó ?currency=XXX

Orden de prioridad:
    1. Query param ?currency=ARS|USD   (override manual del frontend)
    2. Header cf-ipcountry             (geolocalización Cloudflare)
    3. Fallback                        → USD + Stripe

Uso en un router:
    from app.api.deps.pricing import get_pricing_context, PricingContext

    @router.get("/")
    async def list_courses(
        pricing: PricingContext = Depends(get_pricing_context),
    ):
        ...

Simulación en tests:
    scope = {"type": "http", "method": "GET",
             "headers": [(b"cf-ipcountry", b"AR")],
             "query_string": b""}
    request = Request(scope)
    ctx = get_pricing_context(request)          # ctx.currency == "ARS"
    ctx = get_pricing_context(request, "USD")   # ctx.is_manual_override == True
"""

from dataclasses import dataclass
from typing import Literal, Optional

from fastapi import Query, Request

from app.core.config import settings

# Monedas soportadas. Cualquier valor fuera de este set se ignora.
ALLOWED_CURRENCIES: frozenset[str] = frozenset({"ARS", "USD"})

# Mapeo moneda → procesador de pago
_PROCESSOR: dict[str, str] = {
    "ARS": "mercadopago",
    "USD": "lemonsqueezy",
}


@dataclass(frozen=True)
class PricingContext:
    """
    Contexto de precios resuelto para un request específico.

    Atributos:
        currency          Código ISO 4217: "ARS" o "USD"
        payment_processor Procesador de pago a usar: "mercadopago" o "stripe"
        country_code      Código ISO 3166-1 alpha-2 del país detectado,
                          "XX" si desconocido, "MANUAL" si fue un override.
        is_manual_override True si la moneda viene de ?currency= y no de geo.
    """

    currency: Literal["ARS", "USD"]
    payment_processor: Literal["mercadopago", "stripe", "lemonsqueezy"]
    country_code: str
    is_manual_override: bool


def get_pricing_context(
    request: Request,
    currency: Optional[str] = Query(
        default=None,
        description=(
            "Override manual de moneda. Valores aceptados: 'ARS', 'USD'. "
            "Tiene prioridad sobre la geolocalización automática."
        ),
    ),
) -> PricingContext:
    """
    FastAPI Dependency que resuelve el PricingContext para el request.

    Puede inyectarse con Depends() en cualquier endpoint:
        pricing: PricingContext = Depends(get_pricing_context)

    La dependency no accede a la BD ni realiza llamadas externas.
    Es síncrona y extremadamente ligera.
    """

    # ── 1. Override manual por query param ──────────────────────────────────
    if currency:
        normalized = currency.upper().strip()
        if normalized in ALLOWED_CURRENCIES:
            return PricingContext(
                currency=normalized,                   # type: ignore[arg-type]
                payment_processor=_PROCESSOR[normalized],
                country_code="MANUAL",
                is_manual_override=True,
            )
        # Valor inválido (ej. ?currency=BTC) → se ignora, cae al geo

    # ── 2. Geolocalización por header Cloudflare ─────────────────────────────
    #
    # cf-ipcountry contiene el código ISO 3166-1 alpha-2 del país del cliente.
    # Está disponible en producción tras Cloudflare proxy.
    # En local/dev no existe → el fallback es correcto.
    #
    # Valor especial: "T1" = Tor network (tratamos como no-AR)
    # Valor especial: "XX" = Cloudflare no pudo determinar el país
    cf_country = request.headers.get("cf-ipcountry", "").upper().strip()
    if not cf_country and settings.DEFAULT_PAYMENT_COUNTRY:
        cf_country = settings.DEFAULT_PAYMENT_COUNTRY.upper().strip()

    if cf_country == "AR":
        return PricingContext(
            currency="ARS",
            payment_processor="mercadopago",
            country_code="AR",
            is_manual_override=False,
        )

    # ── 3. Fallback: USD + Lemon Squeezy ─────────────────────────────────────
    return PricingContext(
        currency="USD",
        payment_processor="lemonsqueezy",
        country_code=cf_country if cf_country else "XX",
        is_manual_override=False,
    )
