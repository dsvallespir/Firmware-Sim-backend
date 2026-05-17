"""
============================================================
admin.py - Router de Administración
============================================================

Todos los endpoints requieren rol "admin" (get_current_admin).

Stats:
  GET  /api/admin/stats              → Métricas generales

Usuarios:
  GET  /api/admin/users              → Lista paginada
  PATCH /api/admin/users/{id}        → Editar rol / estado / username

Cursos:
  GET  /api/admin/folders            → Carpetas disponibles en CONTENT_BASE_PATH
  GET  /api/admin/courses            → Todos los cursos (incl. no publicados)
  GET  /api/admin/courses/preview-folder  → Preview de una carpeta
  POST /api/admin/courses/create-and-scan → Crear curso + escanear módulos
  POST /api/admin/courses/{id}/rescan → Re-escanear filesystem de un curso
  PATCH /api/admin/courses/{id}      → Actualizar precio, título, publicación

Inscripciones:
  GET  /api/admin/enrollments        → Lista paginada con filtros

Packs:
  GET  /api/admin/packs              → Listar packs
  POST /api/admin/packs              → Crear pack
  GET  /api/admin/packs/{id}         → Detalle de un pack
  PATCH /api/admin/packs/{id}        → Actualizar pack
  DELETE /api/admin/packs/{id}       → Eliminar pack
"""

import os
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func, extract
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as app_settings
from app.core.database import get_db
from app.core.security import get_current_admin
from app.models.user import User
from app.models.course import Course
from app.models.enrollment import Enrollment
from app.models.pack import CoursePack, PackCourse
from app.schemas.admin import (
    AdminStats, TopCourse, RevenueByMonth,
    AdminUserItem, AdminUserUpdate, AdminUsersResponse,
    AdminCourseItem, AdminCourseUpdate, AdminCourseCreate,
    AdminEnrollmentItem, AdminEnrollmentsResponse,
    PackCreate, PackUpdate, PackResponse, PackCourseResponse,
    FolderItem, FolderPreview,
)

router = APIRouter()


# ==============================================================
# STATS
# ==============================================================

@router.get("/stats", response_model=AdminStats)
async def get_admin_stats(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin),
):
    """
    Métricas generales de la plataforma:
    - Totales (usuarios, cursos, inscripciones, revenue)
    - Valores del mes actual
    - Top 5 cursos por inscripciones
    - Revenue por mes (últimos 6 meses)
    """
    now = datetime.now(timezone.utc)

    # Totales de usuarios
    total_users = (await db.execute(select(func.count(User.id)))).scalar() or 0
    active_users = (await db.execute(
        select(func.count(User.id)).where(User.is_active == True)
    )).scalar() or 0

    # Totales de cursos
    total_courses = (await db.execute(select(func.count(Course.id)))).scalar() or 0
    published_courses = (await db.execute(
        select(func.count(Course.id)).where(Course.is_published == True)
    )).scalar() or 0

    # Inscripciones completadas
    total_enrollments = (await db.execute(
        select(func.count(Enrollment.id)).where(
            Enrollment.payment_status == "completed"
        )
    )).scalar() or 0

    # Revenue total (amount_paid está en centavos, convertir a pesos)
    total_revenue_raw = (await db.execute(
        select(func.coalesce(func.sum(Enrollment.amount_paid), 0)).where(
            Enrollment.payment_status == "completed"
        )
    )).scalar() or 0
    total_revenue = total_revenue_raw / 100.0

    # Métricas del mes actual
    revenue_month_raw = (await db.execute(
        select(func.coalesce(func.sum(Enrollment.amount_paid), 0)).where(
            Enrollment.payment_status == "completed",
            extract("year", Enrollment.enrolled_at) == now.year,
            extract("month", Enrollment.enrolled_at) == now.month,
        )
    )).scalar() or 0
    revenue_this_month = revenue_month_raw / 100.0

    enrollments_this_month = (await db.execute(
        select(func.count(Enrollment.id)).where(
            Enrollment.payment_status == "completed",
            extract("year", Enrollment.enrolled_at) == now.year,
            extract("month", Enrollment.enrolled_at) == now.month,
        )
    )).scalar() or 0

    new_users_this_month = (await db.execute(
        select(func.count(User.id)).where(
            extract("year", User.created_at) == now.year,
            extract("month", User.created_at) == now.month,
        )
    )).scalar() or 0

    # Top 5 cursos por inscripciones
    top_result = await db.execute(
        select(
            Course.id,
            Course.title,
            Course.slug,
            func.count(Enrollment.id).label("enrollments"),
            func.coalesce(func.sum(Enrollment.amount_paid), 0).label("revenue_cents"),
        )
        .outerjoin(Enrollment, (Enrollment.course_id == Course.id) & (Enrollment.payment_status == "completed"))
        .group_by(Course.id)
        .order_by(func.count(Enrollment.id).desc())
        .limit(5)
    )
    top_courses = [
        TopCourse(
            id=row.id,
            title=row.title,
            slug=row.slug,
            enrollments=row.enrollments,
            revenue=row.revenue_cents / 100.0,
        )
        for row in top_result.all()
    ]

    # Revenue por mes (últimos 6 meses)
    months_result = await db.execute(
        select(
            extract("year", Enrollment.enrolled_at).label("year"),
            extract("month", Enrollment.enrolled_at).label("month"),
            func.coalesce(func.sum(Enrollment.amount_paid), 0).label("revenue_cents"),
            func.count(Enrollment.id).label("enrollments"),
        )
        .where(Enrollment.payment_status == "completed")
        .group_by("year", "month")
        .order_by("year", "month")
        .limit(6)
    )
    revenue_by_month = [
        RevenueByMonth(
            month=f"{int(row.year):04d}-{int(row.month):02d}",
            revenue=row.revenue_cents / 100.0,
            enrollments=row.enrollments,
        )
        for row in months_result.all()
    ]

    return AdminStats(
        total_users=total_users,
        active_users=active_users,
        total_courses=total_courses,
        published_courses=published_courses,
        total_enrollments=total_enrollments,
        total_revenue=total_revenue,
        revenue_this_month=revenue_this_month,
        enrollments_this_month=enrollments_this_month,
        new_users_this_month=new_users_this_month,
        top_courses=top_courses,
        revenue_by_month=revenue_by_month,
    )


# ==============================================================
# USUARIOS
# ==============================================================

@router.get("/users", response_model=AdminUsersResponse)
async def list_admin_users(
    search: Optional[str] = Query(None, description="Buscar por email o username"),
    role: Optional[str] = Query(None, description="Filtrar por rol: student|admin"),
    is_active: Optional[bool] = Query(None, description="Filtrar por estado"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin),
):
    """Lista de todos los usuarios con filtros y paginación."""
    query = select(User)

    if search:
        query = query.where(
            User.email.ilike(f"%{search}%") | User.username.ilike(f"%{search}%")
        )
    if role:
        query = query.where(User.role == role)
    if is_active is not None:
        query = query.where(User.is_active == is_active)

    # Total sin paginación
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Con paginación
    query = query.order_by(User.created_at.desc()).offset(skip).limit(limit)
    users_result = await db.execute(query)
    users = users_result.scalars().all()

    # Contar inscripciones por usuario
    items = []
    for u in users:
        enrolled = (await db.execute(
            select(func.count(Enrollment.id)).where(
                Enrollment.user_id == u.id,
                Enrollment.payment_status == "completed",
            )
        )).scalar() or 0

        items.append(AdminUserItem(
            id=u.id,
            email=u.email,
            username=u.username,
            role=u.role,
            is_active=u.is_active,
            created_at=u.created_at,
            enrolled_courses=enrolled,
        ))

    return AdminUsersResponse(total=total, users=items)


@router.patch("/users/{user_id}", response_model=AdminUserItem)
async def update_admin_user(
    user_id: int,
    data: AdminUserUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Actualiza rol, estado o username de un usuario."""
    if user_id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No podés modificar tu propia cuenta desde el panel admin",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    if data.role is not None:
        user.role = data.role
    if data.is_active is not None:
        user.is_active = data.is_active
    if data.username is not None:
        user.username = data.username

    await db.commit()
    await db.refresh(user)

    enrolled = (await db.execute(
        select(func.count(Enrollment.id)).where(
            Enrollment.user_id == user.id,
            Enrollment.payment_status == "completed",
        )
    )).scalar() or 0

    return AdminUserItem(
        id=user.id,
        email=user.email,
        username=user.username,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
        enrolled_courses=enrolled,
    )


# ==============================================================
# CURSOS
# ==============================================================

@router.get("/folders", response_model=List[FolderItem])
async def list_folders(
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Lista todas las carpetas disponibles en CONTENT_BASE_PATH.
    Marca cuáles ya están en uso como source_path de algún curso.
    """
    # source_paths ya ocupados
    result = await db.execute(select(Course.source_path))
    used = {row[0] for row in result.all() if row[0]}

    folders = []
    try:
        for entry in sorted(os.listdir(app_settings.CONTENT_BASE_PATH)):
            full_path = os.path.join(app_settings.CONTENT_BASE_PATH, entry)
            if os.path.isdir(full_path) and not entry.startswith("."):
                folders.append(FolderItem(name=entry, in_use=(entry in used)))
    except OSError:
        pass

    return folders


@router.get("/courses", response_model=List[AdminCourseItem])
async def list_admin_courses(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin),
):
    """Lista todos los cursos (publicados y no publicados)."""
    result = await db.execute(select(Course).order_by(Course.id))
    courses = result.scalars().all()

    items = []
    for c in courses:
        enrollments = (await db.execute(
            select(func.count(Enrollment.id)).where(
                Enrollment.course_id == c.id,
                Enrollment.payment_status == "completed",
            )
        )).scalar() or 0

        revenue_raw = (await db.execute(
            select(func.coalesce(func.sum(Enrollment.amount_paid), 0)).where(
                Enrollment.course_id == c.id,
                Enrollment.payment_status == "completed",
            )
        )).scalar() or 0

        items.append(AdminCourseItem(
            id=c.id,
            title=c.title,
            slug=c.slug,
            price=c.price,
            price_usd=c.price_usd,
            is_published=c.is_published,
            language=c.language,
            difficulty=c.difficulty,
            enrollments=enrollments,
            revenue=revenue_raw / 100.0,
            created_at=c.created_at,
            description=c.description,
            short_description=c.short_description,
            title_en=c.title_en,
            description_en=c.description_en,
            short_description_en=c.short_description_en,
            ls_checkout_url=c.ls_checkout_url,
        ))

    return items


@router.get("/courses/preview-folder", response_model=FolderPreview)
async def preview_folder(
    source_path: str = Query(..., description="Nombre de la carpeta en CONTENT_BASE_PATH"),
    _admin: User = Depends(get_current_admin),
):
    """
    Analiza una carpeta y devuelve los módulos y lecciones que
    se detectarían al crear el curso, sin escribir nada en BD.
    """
    from app.services.content_scanner import preview_course_folder
    try:
        return preview_course_folder(source_path)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/courses/create-and-scan", response_model=AdminCourseItem, status_code=201)
async def create_and_scan_course(
    data: AdminCourseCreate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin),
):
    """
    Crea un curso nuevo con todos sus metadatos y escanea automáticamente
    la carpeta source_path para generar módulos y lecciones.
    """
    from app.services.content_scanner import create_course_with_scan
    try:
        result = await create_course_with_scan(data.model_dump(), db)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # Cargar el curso recién creado para construir la respuesta
    course_result = await db.execute(select(Course).where(Course.id == result["id"]))
    course = course_result.scalar_one()

    return AdminCourseItem(
        id=course.id,
        title=course.title,
        slug=course.slug,
        price=course.price,
        price_usd=course.price_usd,
        is_published=course.is_published,
        language=course.language,
        difficulty=course.difficulty,
        enrollments=0,
        revenue=0.0,
        module_count=result["module_count"],
        created_at=course.created_at,
    )


@router.post("/courses/{course_id}/rescan")
async def rescan_course(
    course_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin),
):
    """
    Elimina todos los módulos y lecciones del curso y re-escanea el filesystem.

    Útil cuando el usuario ha dividido manualmente un README.md grande en
    múltiples archivos numerados (01_intro.md, 02_conceptos.md, …).

    ADVERTENCIA: Elimina el progreso de todos los estudiantes del curso
    porque las lecciones antiguas desaparecen (ondelete=CASCADE).
    """
    from app.services.content_scanner import _scan_modules_for_course, resolve_course_content_path
    from app.models.course import Module
    from sqlalchemy import delete

    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Curso no encontrado")

    course_path = resolve_course_content_path(course.source_path, "es")
    if not os.path.isdir(course_path):
        raise HTTPException(
            status_code=400,
            detail=f"Carpeta no encontrada: {course_path}",
        )

    # Eliminar todos los módulos del curso (CASCADE borra lecciones y progreso)
    await db.execute(delete(Module).where(Module.course_id == course_id))
    await db.flush()

    module_count = await _scan_modules_for_course(course, course_path, db)
    await db.commit()

    return {
        "course_id": course_id,
        "slug": course.slug,
        "module_count": module_count,
        "warning": "El progreso de los estudiantes fue reseteado.",
    }


@router.patch("/courses/{course_id}", response_model=AdminCourseItem)
async def update_admin_course(
    course_id: int,
    data: AdminCourseUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin),
):
    """Actualiza precio, título, descripción o estado de publicación."""
    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Curso no encontrado")

    if data.title is not None:
        course.title = data.title
    if data.slug is not None:
        course.slug = data.slug
    if data.price is not None:
        course.price = data.price
    if data.price_usd is not None:
        course.price_usd = data.price_usd
    if data.is_published is not None:
        course.is_published = data.is_published
    if data.short_description is not None:
        course.short_description = data.short_description
    if data.description is not None:
        course.description = data.description
    if data.title_en is not None:
        course.title_en = data.title_en
    if data.description_en is not None:
        course.description_en = data.description_en
    if data.short_description_en is not None:
        course.short_description_en = data.short_description_en
    if data.ls_checkout_url is not None:
        course.ls_checkout_url = data.ls_checkout_url

    await db.commit()
    await db.refresh(course)

    enrollments = (await db.execute(
        select(func.count(Enrollment.id)).where(
            Enrollment.course_id == course.id,
            Enrollment.payment_status == "completed",
        )
    )).scalar() or 0

    revenue_raw = (await db.execute(
        select(func.coalesce(func.sum(Enrollment.amount_paid), 0)).where(
            Enrollment.course_id == course.id,
            Enrollment.payment_status == "completed",
        )
    )).scalar() or 0

    return AdminCourseItem(
        id=course.id,
        title=course.title,
        slug=course.slug,
        price=course.price,
        price_usd=course.price_usd,
        is_published=course.is_published,
        language=course.language,
        difficulty=course.difficulty,
        enrollments=enrollments,
        revenue=revenue_raw / 100.0,
        created_at=course.created_at,
        description=course.description,
        short_description=course.short_description,
        title_en=course.title_en,
        description_en=course.description_en,
        short_description_en=course.short_description_en,
        ls_checkout_url=course.ls_checkout_url,
    )


# ==============================================================
# INSCRIPCIONES
# ==============================================================

@router.get("/enrollments", response_model=AdminEnrollmentsResponse)
async def list_admin_enrollments(
    search: Optional[str] = Query(None, description="Buscar por email"),
    payment_status: Optional[str] = Query(None, description="pending|completed|rejected|refunded"),
    course_id: Optional[int] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin),
):
    """Lista de inscripciones con info de usuario y curso."""
    query = (
        select(Enrollment, User, Course)
        .join(User, Enrollment.user_id == User.id)
        .join(Course, Enrollment.course_id == Course.id)
    )

    if search:
        query = query.where(User.email.ilike(f"%{search}%"))
    if payment_status:
        query = query.where(Enrollment.payment_status == payment_status)
    if course_id:
        query = query.where(Enrollment.course_id == course_id)

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(Enrollment.enrolled_at.desc()).offset(skip).limit(limit)
    rows = (await db.execute(query)).all()

    enrollments = [
        AdminEnrollmentItem(
            id=e.id,
            user_id=e.user_id,
            user_email=u.email,
            user_username=u.username,
            course_id=e.course_id,
            course_title=c.title,
            payment_status=e.payment_status,
            amount_paid=e.amount_paid,
            enrolled_at=e.enrolled_at,
        )
        for e, u, c in rows
    ]

    return AdminEnrollmentsResponse(total=total, enrollments=enrollments)


# ==============================================================
# PACKS DE CURSOS
# ==============================================================

def _build_pack_response(pack: CoursePack) -> PackResponse:
    """Helper: construye PackResponse calculando precios."""
    courses_out = []
    original_price = 0.0

    for pc in sorted(pack.pack_courses, key=lambda x: x.order):
        c = pc.course
        courses_out.append(PackCourseResponse(
            course_id=c.id,
            title=c.title,
            slug=c.slug,
            price=c.price,
            order=pc.order,
        ))
        original_price += c.price

    final_price = round(original_price * (1 - pack.discount_percent / 100), 2)

    return PackResponse(
        id=pack.id,
        name=pack.name,
        slug=pack.slug,
        description=pack.description,
        discount_percent=pack.discount_percent,
        is_active=pack.is_active,
        created_at=pack.created_at,
        courses=courses_out,
        original_price=round(original_price, 2),
        final_price=final_price,
    )


@router.get("/packs", response_model=List[PackResponse])
async def list_packs(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin),
):
    """Lista todos los packs (activos e inactivos)."""
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(CoursePack)
        .options(selectinload(CoursePack.pack_courses).selectinload(PackCourse.course))
        .order_by(CoursePack.id)
    )
    packs = result.scalars().all()
    return [_build_pack_response(p) for p in packs]


@router.post("/packs", response_model=PackResponse, status_code=201)
async def create_pack(
    data: PackCreate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin),
):
    """Crea un nuevo pack de cursos."""
    # Verificar slug único
    existing = await db.execute(
        select(CoursePack).where(CoursePack.slug == data.slug)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail=f"Ya existe un pack con slug '{data.slug}'",
        )

    pack = CoursePack(
        name=data.name,
        slug=data.slug,
        description=data.description,
        discount_percent=data.discount_percent,
        is_active=data.is_active,
    )
    db.add(pack)
    await db.flush()  # Obtener el ID

    for item in data.courses:
        course_exists = await db.execute(
            select(Course).where(Course.id == item.course_id)
        )
        if not course_exists.scalar_one_or_none():
            raise HTTPException(
                status_code=404,
                detail=f"Curso {item.course_id} no encontrado",
            )
        db.add(PackCourse(
            pack_id=pack.id,
            course_id=item.course_id,
            order=item.order,
        ))

    await db.commit()

    # Recargar con relaciones
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(CoursePack)
        .where(CoursePack.id == pack.id)
        .options(selectinload(CoursePack.pack_courses).selectinload(PackCourse.course))
    )
    pack = result.scalar_one()
    return _build_pack_response(pack)


@router.get("/packs/{pack_id}", response_model=PackResponse)
async def get_pack(
    pack_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin),
):
    """Detalle de un pack."""
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(CoursePack)
        .where(CoursePack.id == pack_id)
        .options(selectinload(CoursePack.pack_courses).selectinload(PackCourse.course))
    )
    pack = result.scalar_one_or_none()
    if not pack:
        raise HTTPException(status_code=404, detail="Pack no encontrado")
    return _build_pack_response(pack)


@router.patch("/packs/{pack_id}", response_model=PackResponse)
async def update_pack(
    pack_id: int,
    data: PackUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin),
):
    """Actualiza nombre, descuento, estado o lista de cursos."""
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(CoursePack)
        .where(CoursePack.id == pack_id)
        .options(selectinload(CoursePack.pack_courses).selectinload(PackCourse.course))
    )
    pack = result.scalar_one_or_none()
    if not pack:
        raise HTTPException(status_code=404, detail="Pack no encontrado")

    if data.name is not None:
        pack.name = data.name
    if data.description is not None:
        pack.description = data.description
    if data.discount_percent is not None:
        pack.discount_percent = data.discount_percent
    if data.is_active is not None:
        pack.is_active = data.is_active

    # Reemplazar cursos si se envía la lista
    if data.courses is not None:
        # Eliminar PackCourse existentes
        existing_pcs = await db.execute(
            select(PackCourse).where(PackCourse.pack_id == pack_id)
        )
        for pc in existing_pcs.scalars().all():
            await db.delete(pc)
        await db.flush()

        for item in data.courses:
            course_exists = await db.execute(
                select(Course).where(Course.id == item.course_id)
            )
            if not course_exists.scalar_one_or_none():
                raise HTTPException(
                    status_code=404,
                    detail=f"Curso {item.course_id} no encontrado",
                )
            db.add(PackCourse(
                pack_id=pack_id,
                course_id=item.course_id,
                order=item.order,
            ))

    await db.commit()

    # Recargar
    result = await db.execute(
        select(CoursePack)
        .where(CoursePack.id == pack_id)
        .options(selectinload(CoursePack.pack_courses).selectinload(PackCourse.course))
    )
    pack = result.scalar_one()
    return _build_pack_response(pack)


@router.delete("/packs/{pack_id}", status_code=204)
async def delete_pack(
    pack_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin),
):
    """Elimina un pack permanentemente."""
    result = await db.execute(select(CoursePack).where(CoursePack.id == pack_id))
    pack = result.scalar_one_or_none()
    if not pack:
        raise HTTPException(status_code=404, detail="Pack no encontrado")
    await db.delete(pack)
    await db.commit()
