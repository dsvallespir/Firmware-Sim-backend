"""
============================================================
payment_service.py - Servicio de Pagos (lógica de negocio)
============================================================

Responsabilidades:
1. Crear órdenes de pago (PaymentOrder + Preference en MP)
2. Procesar pagos (consultar MP, actualizar estado, activar enrollment)
3. Idempotencia: múltiples llamadas con el mismo payment_id son seguras
4. Máquina de estados: solo transiciones válidas
5. Concurrencia: SELECT FOR UPDATE previene race conditions
6. Audit trail: PaymentTransaction por cada consulta a MP

NO maneja HTTP, validación de request, ni autenticación.
Eso es responsabilidad del router (payments.py).
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.api.deps.pricing import PricingContext

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.course import Course
from app.models.enrollment import Enrollment
from app.models.payment_notification import PaymentNotification
from app.models.payment_order import (
    PaymentOrder,
    ORDER_STATUS_CREATED,
    ORDER_STATUS_PENDING,
    ORDER_STATUS_PAID,
    ORDER_STATUS_FAILED,
    can_transition,
)
from app.models.payment_transaction import PaymentTransaction
from app.models.user import User
from app.services.mp_client import mp_client

logger = logging.getLogger("payments.service")


# ----------------------------------------------------------
# Mapeo de estados MP → estados de orden
# ----------------------------------------------------------
MP_STATUS_MAP = {
    "approved": ORDER_STATUS_PAID,
    "authorized": ORDER_STATUS_PAID,
    "pending": ORDER_STATUS_PENDING,
    "in_process": ORDER_STATUS_PENDING,
    "rejected": ORDER_STATUS_FAILED,
    "cancelled": ORDER_STATUS_FAILED,
    "refunded": "refunded",
    "charged_back": "refunded",
}


class PaymentService:
    """Servicio central de pagos. Orquesta MP, órdenes y enrollments."""

    # ==========================================================
    # Crear orden de pago
    # ==========================================================
    async def create_order(
        self,
        user: User,
        course: Course,
        db: AsyncSession,
        currency: str = "ARS",
    ) -> dict:
        """
        Crea PaymentOrder + Preference en MP.
        Retorna dict con checkout_url, preference_id, order_id.
        Para cursos gratuitos, inscribe directamente.
        """
        from fastapi import HTTPException, status

        # Verificar si ya está inscrito y pagado
        result = await db.execute(
            select(Enrollment).where(
                Enrollment.user_id == user.id,
                Enrollment.course_id == course.id,
                Enrollment.payment_status == "completed",
            )
        )
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ya estás inscrito en este curso",
            )

        # Cursos gratuitos: inscripción directa
        if course.price == 0:
            await self._enroll_free(user, course, db)
            return {
                "checkout_url": f"{settings.FRONTEND_URL}/courses/{course.slug}",
                "preference_id": "free",
                "order_id": "free",
            }

        # Crear PaymentOrder (en memoria, no en DB todavía)
        order_uuid = str(uuid.uuid4())
        unit_price = float(course.price if currency == "ARS" else course.price_usd)
        amount_cents = int(round(unit_price * 100))

        # Construir preference para MP
        preference_data = {
            "items": [
                {
                    "title": course.title,
                    "description": (course.short_description or "")[:255],
                    "quantity": 1,
                    "unit_price": unit_price,
                    "currency_id": currency,
                }
            ],
            "payer": {"email": user.email},
            "external_reference": order_uuid,
            "notification_url": f"{settings.BACKEND_URL}/api/payments/webhook",
            "statement_descriptor": "FIRMWARE ACADEMY",
        }

        # back_urls solo si el frontend NO es localhost
        frontend = settings.FRONTEND_URL
        if "localhost" not in frontend and "127.0.0.1" not in frontend:
            preference_data["back_urls"] = {
                "success": f"{frontend}/payment/success",
                "failure": f"{frontend}/payment/failure",
                "pending": f"{frontend}/payment/pending",
            }
            preference_data["auto_return"] = "approved"

        # Llamar a MP (si falla, la orden no se persiste — limpio)
        preference = await mp_client.create_preference(preference_data)

        # MP respondió OK → persistir la orden
        order = PaymentOrder(
            order_uuid=order_uuid,
            user_id=user.id,
            course_id=course.id,
            amount_cents=amount_cents,
            currency=currency,
            status=ORDER_STATUS_CREATED,
            preference_id=preference["id"],
        )
        db.add(order)
        await db.commit()

        checkout_url = (
            preference["sandbox_init_point"] if mp_client.is_sandbox
            else preference["init_point"]
        )

        logger.info(
            "Orden creada: uuid=%s, user=%s, course=%s, amount_cents=%s",
            order_uuid, user.id, course.id, amount_cents,
        )

        return {
            "checkout_url": checkout_url,
            "preference_id": preference["id"],
            "order_id": order_uuid,
        }

    # ==========================================================
    # Crear sesión Stripe (oculto — reservado para el futuro)
    # ==========================================================
    async def create_stripe_session(
        self,
        user: User,
        course: Course,
        db: AsyncSession,
        pricing: "PricingContext",
    ) -> dict:
        """
        Crea una Checkout Session en Stripe para usuarios internacionales.

        OCULTO: Stripe no está configurado. Lemon Squeezy es el proveedor activo.
        """
        from fastapi import HTTPException, status as http_status

        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Pagos internacionales no disponibles aún. Escríbenos a hola@firmwareacademy.dev",
        )

    # ==========================================================
    # Crear checkout URL de Lemon Squeezy (Overlay)
    # ==========================================================
    async def create_lemon_squeezy_checkout(
        self,
        user: User,
        course: Course,
        db: AsyncSession,
        pricing: "PricingContext",
    ) -> dict:
        """
        Genera la URL de Lemon Squeezy Checkout Overlay con custom_data.

        Los productos se crean manualmente en el dashboard de LS.
        El course debe tener ls_variant_id (URL del producto en LS).

        custom_data incluye user_id y course_id para asociar la compra
        en el webhook order_created.
        """
        from fastapi import HTTPException, status as http_status

        if not settings.LEMON_SQUEEZY_STORE_ID:
            raise HTTPException(
                status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Pagos internacionales no disponibles aún.",
            )

        # Verificar si ya está inscrito y pagado
        result = await db.execute(
            select(Enrollment).where(
                Enrollment.user_id == user.id,
                Enrollment.course_id == course.id,
                Enrollment.payment_status == "completed",
            )
        )
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="Ya estás inscrito en este curso",
            )

        # Cursos gratuitos: inscripción directa
        if course.price_usd == 0:
            await self._enroll_free(user, course, db)
            return {
                "checkout_url": f"{settings.FRONTEND_URL}/courses/{course.slug}",
                "preference_id": "free",
                "order_id": "free",
            }

        # Crear PaymentOrder
        order_uuid = str(uuid.uuid4())
        unit_price_usd = float(course.price_usd)
        amount_cents = int(round(unit_price_usd * 100))

        order = PaymentOrder(
            order_uuid=order_uuid,
            user_id=user.id,
            course_id=course.id,
            amount_cents=amount_cents,
            currency="USD",
            status=ORDER_STATUS_CREATED,
            payment_provider="lemonsqueezy",
        )
        db.add(order)
        await db.commit()

        # Construir URL de checkout overlay con custom_data
        # El course.ls_checkout_url debe configurarse por curso en la BD
        # Formato: https://STORE.lemonsqueezy.com/checkout/buy/VARIANT_HASH
        ls_checkout_url = getattr(course, "ls_checkout_url", None)
        if not ls_checkout_url:
            raise HTTPException(
                status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Este curso aún no está disponible para compra internacional.",
            )

        # Agregar custom_data como query params para el overlay
        separator = "&" if "?" in ls_checkout_url else "?"
        checkout_url = (
            f"{ls_checkout_url}{separator}"
            f"checkout[custom][user_id]={user.id}"
            f"&checkout[custom][course_id]={course.id}"
            f"&checkout[custom][order_uuid]={order_uuid}"
            f"&checkout[email]={user.email}"
        )

        logger.info(
            "LS checkout creado: uuid=%s, user=%s, course=%s, amount_cents=%s USD",
            order_uuid, user.id, course.id, amount_cents,
        )

        return {
            "checkout_url": checkout_url,
            "preference_id": f"ls-{order_uuid}",
            "order_id": order_uuid,
        }

    # ==========================================================
    # Procesar orden de Lemon Squeezy (llamado desde background)
    # ==========================================================
    async def process_lemon_squeezy_order(
        self,
        user_id: int,
        course_id: int,
        ls_order_id: str,
        amount_cents: int,
        notification_id: int | None = None,
    ) -> None:
        """
        Procesa una orden confirmada de Lemon Squeezy.
        Llamado desde BackgroundTasks tras recibir webhook order_created.

        Crea/actualiza PaymentOrder → paid y activa Enrollment.
        """
        from app.core.database import async_session_maker

        async with async_session_maker() as db:
            try:
                # Buscar orden existente por custom_data o crear nueva
                result = await db.execute(
                    select(PaymentOrder).where(
                        PaymentOrder.user_id == user_id,
                        PaymentOrder.course_id == course_id,
                        PaymentOrder.payment_provider == "lemonsqueezy",
                        PaymentOrder.status.in_([
                            ORDER_STATUS_CREATED, ORDER_STATUS_PENDING,
                        ]),
                    ).with_for_update()
                )
                order = result.scalar_one_or_none()

                if not order:
                    # Crear orden ad-hoc (el usuario compró directamente en LS)
                    order = PaymentOrder(
                        order_uuid=str(uuid.uuid4()),
                        user_id=user_id,
                        course_id=course_id,
                        amount_cents=amount_cents,
                        currency="USD",
                        status=ORDER_STATUS_CREATED,
                        payment_provider="lemonsqueezy",
                    )
                    db.add(order)
                    await db.flush()

                # Transicionar a paid
                if can_transition(order.status, ORDER_STATUS_PAID):
                    order.status = ORDER_STATUS_PAID
                    order.ls_order_id = ls_order_id
                    order.paid_at = datetime.now(timezone.utc)
                    order.updated_at = datetime.now(timezone.utc)

                    await self._activate_enrollment(
                        order, amount_cents, f"ls-{ls_order_id}", db,
                    )

                    logger.info(
                        "LS orden procesada: user=%s, course=%s, ls_order=%s",
                        user_id, course_id, ls_order_id,
                    )
                else:
                    logger.info(
                        "LS orden ya procesada (idempotente): user=%s, course=%s, status=%s",
                        user_id, course_id, order.status,
                    )

                # Vincular notificación
                if notification_id:
                    from app.models.payment_notification import PaymentNotification
                    notif_result = await db.execute(
                        select(PaymentNotification)
                        .where(PaymentNotification.id == notification_id)
                    )
                    notif = notif_result.scalar_one_or_none()
                    if notif:
                        notif.order_id = order.id
                        notif.processed = True
                        notif.processed_at = datetime.now(timezone.utc)

                await db.commit()

            except Exception:
                await db.rollback()
                logger.exception(
                    "Error procesando orden LS: user=%s, course=%s, ls_order=%s",
                    user_id, course_id, ls_order_id,
                )
                raise

    # ==========================================================
    # Procesar pago (confirm o webhook)
    # ==========================================================
    async def process_payment(
        self,
        payment_id: str,
        db: AsyncSession,
        source: str = "confirm",
        notification_id: Optional[int] = None,
    ) -> dict:
        """
        Consulta el pago en MP, actualiza la orden, activa enrollment si approved.

        Idempotente: llamadas repetidas con el mismo payment_id son seguras.
        Usa SELECT FOR UPDATE para prevenir race conditions.

        Args:
            payment_id: ID del payment en Mercado Pago
            db: sesión de base de datos
            source: "confirm" o "webhook"
            notification_id: ID de PaymentNotification para vincular

        Returns:
            dict con status, order_id, mp_status, enrolled, course_slug
        """
        # 1. Consultar pago en MP (SIN lock — operación de red)
        payment = await mp_client.get_payment(payment_id)
        if not payment:
            logger.warning("Payment no encontrado en MP: id=%s", payment_id)
            return {"status": "not_found", "enrolled": False}

        mp_status = payment.get("status", "unknown")
        mp_status_detail = payment.get("status_detail", "")
        external_ref = payment.get("external_reference", "")
        amount_cents = int(round(payment.get("transaction_amount", 0) * 100))
        mp_payment_id = str(payment["id"])

        # 2. Buscar orden CON lock (SELECT FOR UPDATE)
        result = await db.execute(
            select(PaymentOrder)
            .where(PaymentOrder.order_uuid == external_ref)
            .with_for_update()
        )
        order = result.scalar_one_or_none()

        if not order:
            logger.warning(
                "Orden no encontrada: external_ref=%s, payment=%s, source=%s",
                external_ref, payment_id, source,
            )
            return {"status": "unknown_order", "enrolled": False}

        # 3. Registrar transacción (siempre, para audit trail)
        transaction = PaymentTransaction(
            order_id=order.id,
            mp_payment_id=mp_payment_id,
            mp_status=mp_status,
            mp_status_detail=mp_status_detail,
            amount_cents=amount_cents,
            currency=payment.get("currency_id", "ARS"),
            raw_response_json=json.dumps(payment, default=str),
        )
        db.add(transaction)

        # 4. Vincular notificación si corresponde
        if notification_id:
            notif_result = await db.execute(
                select(PaymentNotification)
                .where(PaymentNotification.id == notification_id)
            )
            notif = notif_result.scalar_one_or_none()
            if notif:
                notif.order_id = order.id
                notif.processed = True
                notif.processed_at = datetime.now(timezone.utc)

        # 5. Mapear estado MP → estado de orden
        new_status = MP_STATUS_MAP.get(mp_status)
        if not new_status:
            logger.warning(
                "Estado MP desconocido: %s (payment=%s)", mp_status, payment_id,
            )
            await db.commit()
            return await self._build_response(order, mp_status, db)

        # 6. Idempotencia: ya está en el estado destino
        if order.status == new_status:
            logger.info(
                "Orden %s ya en estado %s (idempotente, source=%s)",
                order.order_uuid, new_status, source,
            )
            await db.commit()
            return await self._build_response(order, mp_status, db)

        # 7. Validar transición en la máquina de estados
        if not can_transition(order.status, new_status):
            logger.warning(
                "Transición inválida: orden=%s, %s → %s (mp=%s, source=%s)",
                order.order_uuid, order.status, new_status, mp_status, source,
            )
            await db.commit()
            resp = await self._build_response(order, mp_status, db)
            resp["warning"] = f"Transición inválida: {order.status} → {new_status}"
            return resp

        # 8. Aplicar transición
        old_status = order.status
        order.status = new_status
        order.mp_payment_id = mp_payment_id
        order.updated_at = datetime.now(timezone.utc)

        if new_status == ORDER_STATUS_PAID:
            order.paid_at = datetime.now(timezone.utc)
            await self._activate_enrollment(order, amount_cents, mp_payment_id, db)

        await db.commit()

        logger.info(
            "Orden %s: %s → %s (payment=%s, source=%s)",
            order.order_uuid, old_status, new_status, payment_id, source,
        )

        return await self._build_response(order, mp_status, db)

    # ==========================================================
    # Consultar estado de orden (para polling del frontend)
    # ==========================================================
    async def get_order_status(
        self,
        order_uuid: str,
        user_id: int,
        db: AsyncSession,
    ) -> Optional[dict]:
        """Retorna estado actual de una orden. Para frontend polling."""
        result = await db.execute(
            select(PaymentOrder, Course.slug)
            .join(Course, PaymentOrder.course_id == Course.id)
            .where(
                PaymentOrder.order_uuid == order_uuid,
                PaymentOrder.user_id == user_id,
            )
        )
        row = result.one_or_none()
        if not row:
            return None

        order, course_slug = row

        return {
            "order_id": order.order_uuid,
            "status": order.status,
            "course_id": order.course_id,
            "course_slug": course_slug,
            "amount_cents": order.amount_cents,
            "currency": order.currency,
            "created_at": order.created_at.isoformat(),
            "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        }

    # ==========================================================
    # Helpers privados
    # ==========================================================
    async def _build_response(
        self, order: PaymentOrder, mp_status: str, db: AsyncSession,
    ) -> dict:
        """Construye dict de respuesta estándar con course_slug."""
        course_result = await db.execute(
            select(Course.slug).where(Course.id == order.course_id)
        )
        course_slug = course_result.scalar_one_or_none() or ""

        return {
            "status": order.status,
            "order_id": order.order_uuid,
            "course_slug": course_slug,
            "mp_status": mp_status,
            "enrolled": order.status == ORDER_STATUS_PAID,
        }

    async def _activate_enrollment(
        self,
        order: PaymentOrder,
        amount_cents: int,
        mp_payment_id: str,
        db: AsyncSession,
    ):
        """Crea o activa Enrollment cuando el pago es aprobado."""
        result = await db.execute(
            select(Enrollment).where(
                Enrollment.user_id == order.user_id,
                Enrollment.course_id == order.course_id,
            )
        )
        enrollment = result.scalar_one_or_none()

        if enrollment:
            enrollment.payment_status = "completed"
            enrollment.payment_provider_id = mp_payment_id
            enrollment.amount_paid = amount_cents
        else:
            enrollment = Enrollment(
                user_id=order.user_id,
                course_id=order.course_id,
                payment_status="completed",
                payment_provider_id=mp_payment_id,
                amount_paid=amount_cents,
            )
            db.add(enrollment)

        logger.info(
            "Enrollment activado: user=%s, course=%s, order=%s",
            order.user_id, order.course_id, order.order_uuid,
        )

    async def _enroll_free(
        self, user: User, course: Course, db: AsyncSession,
    ):
        """Inscripción directa para cursos gratuitos."""
        result = await db.execute(
            select(Enrollment).where(
                Enrollment.user_id == user.id,
                Enrollment.course_id == course.id,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.payment_status = "completed"
            existing.amount_paid = 0
        else:
            db.add(Enrollment(
                user_id=user.id,
                course_id=course.id,
                payment_status="completed",
                amount_paid=0,
            ))

        await db.commit()
        logger.info("Inscripción gratuita: user=%s, course=%s", user.id, course.id)


# Singleton — importar desde aquí en toda la app
payment_service = PaymentService()
