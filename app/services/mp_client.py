"""
============================================================
mp_client.py - Cliente de Mercado Pago (wrapper del SDK)
============================================================

Encapsula el SDK sincrónico de MP en una interfaz async.
Responsabilidades:
- Inicialización lazy del SDK
- Ejecución en thread pool (run_in_executor)
- Logging estructurado de cada operación
- Manejo de errores del SDK

NO contiene lógica de negocio — solo comunicación con MP.
"""

import asyncio
import logging
from typing import Optional

from fastapi import HTTPException, status

from app.core.config import settings

logger = logging.getLogger("payments.mp_client")


class MercadoPagoClient:
    """Wrapper async del SDK sincrónico de Mercado Pago."""

    def __init__(self):
        self._sdk = None

    def _get_sdk(self):
        """Inicializa el SDK lazily. Lanza 503 si no está configurado."""
        if self._sdk is None:
            import mercadopago

            token = settings.MP_ACCESS_TOKEN
            if not token or token in ("TEST-...", "APP_USR-..."):
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=(
                        "Pagos no configurados. "
                        "Agrega MP_ACCESS_TOKEN en el .env "
                        "(obtenelo en mercadopago.com.ar/developers/panel/credentials)."
                    ),
                )
            self._sdk = mercadopago.SDK(token)
            logger.info("SDK de Mercado Pago inicializado")

        return self._sdk

    async def _run_sync(self, func, *args):
        """Ejecuta función sincrónica en el thread pool del event loop."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, func, *args)

    @property
    def is_sandbox(self) -> bool:
        """True si estamos usando credenciales de sandbox (TEST-...)."""
        return settings.MP_ACCESS_TOKEN.startswith("TEST-")

    async def create_preference(self, preference_data: dict) -> dict:
        """
        Crea una Preference en MP.
        Retorna el dict de la preference creada.
        Lanza HTTPException si falla.
        """
        sdk = self._get_sdk()

        def _create():
            return sdk.preference().create(preference_data)

        ext_ref = preference_data.get("external_reference", "?")
        logger.info("Creando preference en MP: external_ref=%s", ext_ref)

        response = await self._run_sync(_create)

        if response["status"] not in (200, 201):
            error_detail = response.get("response", {})
            logger.error(
                "Error al crear preference: status=%s, response=%s",
                response["status"], error_detail,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Error de Mercado Pago: {error_detail}",
            )

        pref = response["response"]
        logger.info(
            "Preference creada: id=%s, external_ref=%s",
            pref["id"], ext_ref,
        )
        return pref

    async def get_payment(self, payment_id: str) -> Optional[dict]:
        """
        Consulta un pago en MP por su ID.
        Retorna el dict del payment o None si no existe.
        """
        sdk = self._get_sdk()

        def _get():
            return sdk.payment().get(str(payment_id))

        logger.info("Consultando payment en MP: id=%s", payment_id)

        response = await self._run_sync(_get)

        if response["status"] != 200:
            logger.warning(
                "Payment no encontrado en MP: id=%s, http_status=%s",
                payment_id, response["status"],
            )
            return None

        logger.info(
            "Payment obtenido: id=%s, mp_status=%s",
            payment_id, response["response"].get("status"),
        )
        return response["response"]


# Singleton — importar desde aquí en toda la app
mp_client = MercadoPagoClient()
