"""
============================================================
payments.py - Router de Pagos (Thin Controller)
============================================================

Endpoints:
- POST /api/payments/create-checkout  → Crear orden + Preference de MP o URL de LS
- GET  /api/payments/confirm          → Confirmar pago desde redirect de MP
- GET  /api/payments/status/{order_id}→ Polling de estado (frontend)
- POST /api/payments/webhook          → Webhook/IPN de Mercado Pago
- POST /api/payments/webhook/lemonsqueezy → Webhook de Lemon Squeezy

Toda la lógica de negocio está en:
- services/payment_service.py (órdenes, estados, enrollments)
- services/mp_client.py (comunicación con SDK de MP)

Este router solo maneja:
- Validación de input HTTP
- Autenticación / autorización
- Persistencia de notificaciones crudas
- Validación de firma HMAC
- Delegación al servicio
"""

import hashlib
import hmac
import json
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_verified_user
from app.api.deps.pricing import get_pricing_context, PricingContext
from app.models.user import User
from app.models.course import Course
from app.models.payment_order import PaymentOrder
from app.models.payment_notification import PaymentNotification
from app.services.mp_client import mp_client
from app.services.payment_service import payment_service

router = APIRouter()
logger = logging.getLogger("payments.api")


# ----------------------------------------------------------
# Schemas
# ----------------------------------------------------------

class CheckoutRequest(BaseModel):
    """Request para crear una preferencia de pago."""
    course_id: int


class CheckoutResponse(BaseModel):
    """Response con la URL de Mercado Pago Checkout + order_id."""
    checkout_url: str
    preference_id: str
    order_id: str


class OrderStatusResponse(BaseModel):
    """Response con el estado actual de una orden."""
    order_id: str
    status: str
    course_id: int
    course_slug: str
    amount_cents: int
    currency: str
    created_at: str
    paid_at: Optional[str] = None


# ----------------------------------------------------------
# Utilidad pura para firma HMAC (testeable)
# ----------------------------------------------------------

def compute_mp_signature(
    secret: str, data_id: str, request_id: str, ts: str,
) -> str:
    """
    Computa la firma HMAC-SHA256 esperada para un webhook de MP.
    Formato del manifest según docs de MP:
        "id:{data.id};request-id:{x-request-id};ts:{ts};"
    """
    manifest = f"id:{data_id};request-id:{request_id};ts:{ts};"
    return hmac.new(
        secret.encode(), manifest.encode(), hashlib.sha256,
    ).hexdigest()


# ----------------------------------------------------------
# POST /create-checkout
# ----------------------------------------------------------

@router.post("/create-checkout", response_model=CheckoutResponse)
async def create_checkout(
    data: CheckoutRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_verified_user),
    pricing: PricingContext = Depends(get_pricing_context),
):
    """
    Crea una PaymentOrder + Preference en el procesador de pagos localizado.
    - Argentina (ARS): MercadoPago
    - Internacional (USD): Lemon Squeezy (Checkout Overlay)
    """
    result = await db.execute(
        select(Course).where(Course.id == data.course_id)
    )
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Curso no encontrado")

    # Cursos gratuitos: inscripción directa sin pasar por ningún procesador de pago
    if course.price == 0 and course.price_usd == 0:
        await payment_service._enroll_free(current_user, course, db)
        return CheckoutResponse(
            checkout_url=f"{settings.FRONTEND_URL}/courses/{course.slug}",
            preference_id="free",
            order_id="free",
        )

    if pricing.payment_processor == "lemonsqueezy":
        order_data = await payment_service.create_lemon_squeezy_checkout(
            current_user, course, db, pricing
        )
    elif pricing.payment_processor == "stripe":
        order_data = await payment_service.create_stripe_session(
            current_user, course, db, pricing
        )
    else:
        order_data = await payment_service.create_order(
            current_user, course, db, currency=pricing.currency
        )
    return CheckoutResponse(**order_data)


# ----------------------------------------------------------
# GET /confirm
# ----------------------------------------------------------

@router.get("/confirm")
async def confirm_payment(
    payment_id: str = Query(..., description="ID del pago retornado por MP"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_verified_user),
):
    """
    Confirma un pago consultando la API de MP.
    El frontend llama a este endpoint con el payment_id del redirect de MP.
    Verifica que el pago pertenece al usuario autenticado.
    """
    # Consultar el pago en MP para obtener external_reference
    payment = await mp_client.get_payment(payment_id)
    if not payment:
        raise HTTPException(
            status_code=404, detail="Pago no encontrado en Mercado Pago",
        )

    # Verificar ownership: external_reference → order UUID → user_id
    external_ref = payment.get("external_reference", "")
    result = await db.execute(
        select(PaymentOrder).where(PaymentOrder.order_uuid == external_ref)
    )
    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(
            status_code=400, detail="Referencia de pago no encontrada",
        )

    if order.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Este pago no corresponde a tu cuenta",
        )

    # Procesar el pago (idempotente)
    return await payment_service.process_payment(
        payment_id=payment_id, db=db, source="confirm",
    )


# ----------------------------------------------------------
# GET /status/{order_id} — Polling desde el frontend
# ----------------------------------------------------------

@router.get("/status/{order_id}", response_model=OrderStatusResponse)
async def get_order_status(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_verified_user),
):
    """
    Retorna el estado actual de una orden de pago.
    Usado por el frontend para polling después del redirect de MP.
    """
    result = await payment_service.get_order_status(
        order_id, current_user.id, db,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Orden no encontrada")

    return OrderStatusResponse(**result)


# ----------------------------------------------------------
# POST /webhook — Mercado Pago webhook/IPN
# ----------------------------------------------------------

@router.post("/webhook")
async def mp_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Recibe notificaciones de pago de Mercado Pago.
    Siempre retorna HTTP 200 para evitar reintentos excesivos de MP.

    Flujo:
    1. Persistir notificación cruda (antes de procesar)
    2. Validar firma HMAC-SHA256
    3. Extraer payment_id
    4. Delegar a payment_service.process_payment()
    """
    # --- 1. Leer y persistir el request crudo ---
    body_bytes = await request.body()
    body_text = body_bytes.decode("utf-8", errors="replace")

    relevant_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() in ("x-signature", "x-request-id", "content-type", "user-agent")
    }

    notification = PaymentNotification(
        source="webhook",
        headers_json=json.dumps(relevant_headers),
        body_json=body_text,
        query_params=json.dumps(dict(request.query_params)),
        ip_address=request.client.host if request.client else None,
    )

    # --- 2. Validar firma HMAC ---
    signature_valid = _validate_webhook_signature(request)
    notification.signature_valid = signature_valid

    if signature_valid is False:
        notification.processing_error = "Firma HMAC inválida"
        db.add(notification)
        await db.commit()
        logger.warning(
            "Webhook con firma inválida desde %s",
            request.client.host if request.client else "unknown",
        )
        return {"status": "invalid_signature"}

    # --- 3. Extraer payment_id ---
    payment_id = None

    # Formato nuevo: JSON body
    try:
        body = json.loads(body_text) if body_text else {}
        if body.get("type") == "payment":
            payment_id = body.get("data", {}).get("id")
    except (json.JSONDecodeError, AttributeError):
        pass

    # Formato legacy: IPN query params
    if not payment_id:
        topic = request.query_params.get("topic", "")
        if topic == "payment":
            payment_id = request.query_params.get("id")

    if not payment_id:
        notification.processing_error = "No se encontró payment_id"
        db.add(notification)
        await db.commit()
        return {"status": "ignored"}

    notification.mp_payment_id = str(payment_id)
    db.add(notification)
    await db.flush()  # Obtener notification.id para vincular

    # --- 4. Procesar pago ---
    try:
        result = await payment_service.process_payment(
            payment_id=str(payment_id),
            db=db,
            source="webhook",
            notification_id=notification.id,
        )
        logger.info(
            "Webhook procesado: payment=%s, status=%s",
            payment_id, result.get("mp_status"),
        )
        return {"status": "ok", "mp_status": result.get("mp_status")}

    except Exception as e:
        notification.processing_error = str(e)
        await db.commit()
        logger.exception("Error procesando webhook: payment=%s", payment_id)
        return {"status": "error", "detail": str(e)}


# ----------------------------------------------------------
# Helper privado de validación de firma
# ----------------------------------------------------------

def _validate_webhook_signature(request: Request) -> Optional[bool]:
    """
    Valida la firma HMAC-SHA256 del webhook de MP.
    Retorna True (válida), False (inválida), None (sin secreto o sin firma).
    """
    secret = settings.MP_WEBHOOK_SECRET_KEY
    if not secret:
        return None

    x_signature = request.headers.get("x-signature", "")
    x_request_id = request.headers.get("x-request-id", "")

    # Parsear "ts=...,v1=..."
    sig_parts = {}
    for part in x_signature.split(","):
        kv = part.strip().split("=", 1)
        if len(kv) == 2:
            sig_parts[kv[0].strip()] = kv[1].strip()

    ts = sig_parts.get("ts", "")
    v1 = sig_parts.get("v1", "")

    if not ts or not v1:
        return None  # Sin firma para validar

    data_id = request.query_params.get("data.id", "")
    expected = compute_mp_signature(secret, data_id, x_request_id, ts)

    return hmac.compare_digest(expected, v1)


# ----------------------------------------------------------
# Utilidad: firma HMAC para Lemon Squeezy (testeable)
# ----------------------------------------------------------

def verify_lemon_squeezy_signature(
    secret: str, body: bytes, signature: str,
) -> bool:
    """
    Valida la firma HMAC-SHA256 del webhook de Lemon Squeezy.
    LS envía el header X-Signature con el hex digest.
    """
    expected = hmac.new(
        secret.encode(), body, hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


# ----------------------------------------------------------
# POST /webhook/lemonsqueezy — Lemon Squeezy webhook
# ----------------------------------------------------------

@router.post("/webhook/lemonsqueezy")
async def lemon_squeezy_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Recibe notificaciones de Lemon Squeezy.
    Retorna HTTP 200 inmediatamente y procesa en background.

    Flujo:
    1. Leer body crudo
    2. Validar firma HMAC-SHA256 (X-Signature)
    3. Solo procesar evento 'order_created'
    4. Extraer user_id y course_id de meta.custom_data
    5. Activar enrollment en background
    """
    # --- 1. Leer body crudo ---
    body_bytes = await request.body()
    body_text = body_bytes.decode("utf-8", errors="replace")

    # Persistir notificación cruda
    relevant_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() in ("x-signature", "x-event-name", "content-type", "user-agent")
    }
    notification = PaymentNotification(
        source="lemonsqueezy",
        headers_json=json.dumps(relevant_headers),
        body_json=body_text,
        query_params=json.dumps(dict(request.query_params)),
        ip_address=request.client.host if request.client else None,
    )

    # --- 2. Validar firma HMAC ---
    secret = settings.LEMON_SQUEEZY_WEBHOOK_SECRET
    signature = request.headers.get("x-signature", "")

    if not secret:
        logger.warning("LEMON_SQUEEZY_WEBHOOK_SECRET no configurado")
        notification.signature_valid = None
        notification.processing_error = "Webhook secret no configurado"
        db.add(notification)
        await db.commit()
        return {"status": "ok"}

    if not verify_lemon_squeezy_signature(secret, body_bytes, signature):
        notification.signature_valid = False
        notification.processing_error = "Firma HMAC inválida"
        db.add(notification)
        await db.commit()
        logger.warning(
            "Webhook LS con firma inválida desde %s",
            request.client.host if request.client else "unknown",
        )
        return {"status": "ok"}  # 200 para no provocar reintentos

    notification.signature_valid = True

    # --- 3. Parsear y filtrar evento ---
    try:
        payload = json.loads(body_text)
    except json.JSONDecodeError:
        notification.processing_error = "JSON inválido"
        db.add(notification)
        await db.commit()
        return {"status": "ok"}

    event_name = payload.get("meta", {}).get("event_name", "")

    if event_name != "order_created":
        notification.processing_error = f"Evento ignorado: {event_name}"
        db.add(notification)
        await db.commit()
        logger.info("Webhook LS evento ignorado: %s", event_name)
        return {"status": "ok"}

    # --- 4. Extraer custom_data ---
    meta = payload.get("meta", {})
    custom_data = meta.get("custom_data", {})
    user_id = custom_data.get("user_id")
    course_id = custom_data.get("course_id")

    ls_order_id = str(payload.get("data", {}).get("id", ""))
    amount_cents = int(
        float(payload.get("data", {}).get("attributes", {}).get("total", 0))
    )

    if not user_id or not course_id:
        notification.processing_error = (
            f"custom_data incompleto: user_id={user_id}, course_id={course_id}"
        )
        db.add(notification)
        await db.commit()
        logger.warning("Webhook LS sin user_id/course_id en custom_data")
        return {"status": "ok"}

    notification.processed = True
    db.add(notification)
    await db.flush()

    # --- 5. Procesar en background ---
    background_tasks.add_task(
        payment_service.process_lemon_squeezy_order,
        user_id=int(user_id),
        course_id=int(course_id),
        ls_order_id=ls_order_id,
        amount_cents=amount_cents,
        notification_id=notification.id,
    )

    logger.info(
        "Webhook LS recibido: order=%s, user=%s, course=%s → background",
        ls_order_id, user_id, course_id,
    )
    return {"status": "ok"}
