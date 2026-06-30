from fastapi import APIRouter, Depends, HTTPException, Request as HTTPRequest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
from sqlalchemy.orm import selectinload
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field
import logging

from .database import get_db
from .models import User, Project, Request as RequestModel, AuditEntry, Notification
from .auth import (
    get_current_user, register_user, login_user, verify_2fa, forgot_password, reset_password,
    UserRegister, UserLogin, VerifyCode, ForgotPassword, ResetPassword
)
from .notifications import (
    notify_status_change, notify_supplier_new, notify_directors_new,
    get_unread_notifications, mark_notifications_read, notify_request_finalized
)

logger = logging.getLogger("routes")
router = APIRouter()

class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1)
    deadline: Optional[str] = None

class RequestCreate(BaseModel):
    project_id: int
    body: str
    priority: str = "medium"
    deadline: str
    estimated_cost: Optional[float] = None
    executor_id: Optional[int] = None

class StatusUpdate(BaseModel):
    new_status: str
    comment: Optional[str] = None
    director_cost: Optional[float] = None

# === АВТОРИЗАЦИЯ ===
@router.post("/register")
async def api_register(user_data: UserRegister, db: AsyncSession = Depends(get_db), http_request: HTTPRequest = None):
    return await register_user(user_data, db, http_request)

@router.post("/verify")
async def api_verify(data: VerifyCode, db: AsyncSession = Depends(get_db)):
    return await verify_2fa(data, db)

@router.post("/login")
async def api_login(login_data: UserLogin, db: AsyncSession = Depends(get_db), http_request: HTTPRequest = None):
    return await login_user(login_data, db, http_request)

@router.post("/forgot-password")
async def api_forgot_password(data: ForgotPassword, db: AsyncSession = Depends(get_db), http_request: HTTPRequest = None):
    return await forgot_password(data, db, http_request)

@router.post("/reset-password")
async def api_reset_password(data: ResetPassword, db: AsyncSession = Depends(get_db)):
    return await reset_password(data, db)

# === ПРОЕКТЫ ===
@router.get("/projects")
async def get_projects(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).where(Project.archived == False))
    projects = result.scalars().all()
    return {"projects": [{"id": p.id, "name": p.name, "deadline": p.deadline} for p in projects]}

@router.post("/projects")
async def create_project(project: ProjectCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if user.role not in ["director", "procurement"]:
        raise HTTPException(403, detail="Недостаточно прав")
    result = await db.execute(select(Project).where(Project.name == project.name))
    if result.scalar_one_or_none():
        raise HTTPException(400, detail="Проект с таким именем уже существует")
    new_project = Project(name=project.name, deadline=project.deadline)
    db.add(new_project)
    await db.commit()
    await db.refresh(new_project)
    return {"ok": True, "project": {"id": new_project.id, "name": new_project.name, "deadline": new_project.deadline}}

@router.post("/projects/{project_id}/archive")
async def archive_project(project_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if user.role != "director":
        raise HTTPException(403, detail="Только руководитель может архивировать проекты")
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, detail="Проект не найден")
    project.archived = True
    await db.commit()
    return {"ok": True, "message": "Проект архивирован"}

@router.delete("/projects/{project_id}")
async def delete_project(project_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if user.role != "director":
        raise HTTPException(403, detail="Только руководитель может удалять проекты")
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, detail="Проект не найден")
    if not project.archived:
        raise HTTPException(400, detail="Можно удалить только архивный проект")
    
    requests_result = await db.execute(select(RequestModel).where(RequestModel.project_id == project_id))
    for req in requests_result.scalars().all():
        await db.execute(delete(Notification).where(Notification.request_id == req.id))
        await db.execute(delete(AuditEntry).where(AuditEntry.request_id == req.id))
        await db.delete(req)
    
    await db.delete(project)
    await db.commit()
    return {"ok": True, "message": "Проект и все его заявки удалены"}

@router.get("/projects/archive")
async def get_archived_projects(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).where(Project.archived == True))
    projects = result.scalars().all()
    return {"projects": [{"id": p.id, "name": p.name, "deadline": p.deadline, "created_at": p.created_at.isoformat() if p.created_at else None} for p in projects]}

# === ПОЛЬЗОВАТЕЛИ ===
@router.get("/users/procurement")
async def get_procurement_users(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(User).where(User.role == "procurement", User.verified == True, User.deleted == False)
    )
    users = result.scalars().all()
    return {"users": [{"id": u.id, "name": u.name, "email": u.email} for u in users]}

@router.get("/users")
async def get_all_users(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if user.role != "director":
        raise HTTPException(403, detail="Только для руководителя")
    result = await db.execute(select(User).where(User.deleted == False))
    users = result.scalars().all()
    return {"users": [{
        "id": u.id, "name": u.name, "email": u.email, "role": u.role,
        "verified": u.verified, "last_login": u.last_login.isoformat() if u.last_login else None
    } for u in users]}

@router.delete("/users/{user_id}")
async def delete_user(user_id: int, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current_user.role != "director":
        raise HTTPException(403, detail="Только руководитель может удалять пользователей")
    if user_id == current_user.id:
        raise HTTPException(400, detail="Нельзя удалить самого себя")
    
    target_user = await db.get(User, user_id)
    if not target_user or target_user.deleted:
        raise HTTPException(404, detail="Пользователь не найден")
    if target_user.role == "director":
        raise HTTPException(400, detail="Нельзя удалить другого руководителя")
    
    requests_result = await db.execute(select(RequestModel).where(RequestModel.author_id == user_id))
    for req in requests_result.scalars().all():
        await db.execute(delete(Notification).where(Notification.request_id == req.id))
        await db.execute(delete(AuditEntry).where(AuditEntry.request_id == req.id))
        await db.delete(req)
    
    await db.execute(delete(Notification).where(Notification.user_id == user_id))
    await db.delete(target_user)
    await db.commit()
    return {"ok": True, "message": "Пользователь удалён"}

# === СТАТИСТИКА ===
@router.get("/statistics")
async def get_statistics(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if user.role != "director":
        raise HTTPException(403, detail="Только для руководителя")
    
    approved_result = await db.execute(
        select(RequestModel).options(selectinload(RequestModel.project_rel)).where(
            RequestModel.status.in_(["Оплачено", "Договорённость"])
        )
    )
    approved = approved_result.scalars().all()
    approved_sum = sum(r.director_cost or r.estimated_cost or 0 for r in approved)
    
    rejected_result = await db.execute(
        select(RequestModel).options(selectinload(RequestModel.project_rel)).where(
            RequestModel.status == "Отклонено"
        )
    )
    rejected = rejected_result.scalars().all()
    rejected_sum = sum(r.director_cost or r.estimated_cost or 0 for r in rejected)
    
    in_progress_result = await db.execute(
        select(RequestModel).where(RequestModel.status == "Выполняется")
    )
    in_progress = in_progress_result.scalars().all()
    in_progress_sum = sum(r.estimated_cost or 0 for r in in_progress)
    
    pending_result = await db.execute(
        select(RequestModel).where(RequestModel.status == "Отправлено на рассмотрение")
    )
    pending = pending_result.scalars().all()
    pending_sum = sum(r.estimated_cost or 0 for r in pending)
    
    return {
        "approved": {
            "count": len(approved), "sum": approved_sum,
            "items": [{"req_id": r.req_id, "project": r.project_rel.name if r.project_rel else "N/A",
                       "author": r.author_name, "cost": r.director_cost or r.estimated_cost or 0, "status": r.status} for r in approved]
        },
        "rejected": {
            "count": len(rejected), "sum": rejected_sum,
            "items": [{"req_id": r.req_id, "project": r.project_rel.name if r.project_rel else "N/A",
                       "author": r.author_name, "cost": r.director_cost or r.estimated_cost or 0,
                       "status": r.status, "comment": r.comment} for r in rejected]
        },
        "in_progress": {"count": len(in_progress), "sum": in_progress_sum},
        "pending": {"count": len(pending), "sum": pending_sum},
        "total_sum": approved_sum + rejected_sum + in_progress_sum + pending_sum
    }

# === ЗАЯВКИ ===
@router.get("/requests")
async def get_requests(db: AsyncSession = Depends(get_db), project_id: Optional[int] = None, status_filter: Optional[str] = None):
    query = select(RequestModel).options(
        selectinload(RequestModel.project_rel), selectinload(RequestModel.author_rel)
    )
    if project_id:
        query = query.where(RequestModel.project_id == project_id)
    if status_filter:
        query = query.where(RequestModel.status == status_filter)
    result = await db.execute(query)
    requests = result.scalars().all()
    
    return {
        "requests": [{
            "id": r.id, "req_id": r.req_id, "project_id": r.project_id,
            "project_name": r.project_rel.name if r.project_rel else "N/A",
            "author_id": r.author_id, "author_name": r.author_name,
            "body": r.body, "priority": r.priority, "status": r.status,
            "deadline": r.deadline, "created_date": r.created_date,
            "comment": r.comment, "taken_by_id": r.taken_by_id,
            "executor_id": r.executor_id, "estimated_cost": r.estimated_cost,
            "director_cost": r.director_cost
        } for r in requests]
    }

@router.post("/requests")
async def create_request(req: RequestCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), http_request: HTTPRequest = None):
    project = await db.get(Project, req.project_id)
    if not project: 
        raise HTTPException(404, detail="Проект не найден")
    
    if datetime.strptime(req.deadline, "%Y-%m-%d").date() < datetime.now().date():
        raise HTTPException(400, detail="Срок не может быть в прошлом")
    
    count = await db.execute(select(func.count(RequestModel.id)))
    req_id = f"REQ-{count.scalar() + 1:03d}"
    
    new_request = RequestModel(
        req_id=req_id, project_id=project.id, author_id=user.id, 
        author_name=user.name, body=req.body, priority=req.priority, 
        deadline=req.deadline, estimated_cost=req.estimated_cost,
        executor_id=req.executor_id, created_date=datetime.now().strftime("%Y-%m-%d")
    )
    
    db.add(new_request)
    await db.commit()
    await db.refresh(new_request)
    
    audit = AuditEntry(
        request_id=new_request.id,
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
        actor=user.name, action="Создание заявки", 
        new_status="Отправлено на рассмотрение"
    )
    db.add(audit)
    await db.commit()
    
    client_host = http_request.client.host if http_request and http_request.client else "localhost"
    
    # ✅ ЛОГИКА МАРШРУТИЗАЦИИ ЗАЯВКИ
    suppliers = await db.execute(select(User).where(User.role == "procurement", User.verified == True, User.deleted == False))
    has_suppliers = suppliers.scalars().first() is not None
    
    if user.role == "client":
        if has_suppliers:
            # Стандартный маршрут: Client → Снабженцы
            await notify_supplier_new(new_request, db, host=client_host)
        else:
            # Нет снабженцев: Client → Директора напрямую
            logger.warning(f"⚠️ Заявка {req_id} создана без снабженцев — отправлена директорам напрямую")
            await notify_directors_new(new_request, db, host=client_host)
    
    elif user.role == "procurement":
        # Снабженец создаёт заявку → только директорам (без само-уведомления)
        await notify_directors_new(new_request, db, host=client_host)
    
    elif user.role == "director":
        # Директор создаёт заявку → снабженцам (если есть)
        if has_suppliers:
            await notify_supplier_new(new_request, db, host=client_host)
        # Если нет снабженцев — заявка создана директором, он сам её обработает
    
    return {
        "ok": True, 
        "request": {
            "id": new_request.id, "req_id": new_request.req_id,
            "project_id": new_request.project_id, "author_name": new_request.author_name,
            "body": new_request.body, "priority": new_request.priority,
            "status": new_request.status, "deadline": new_request.deadline,
            "created_date": new_request.created_date
        },
        "route": "direct_to_director" if (user.role == "client" and not has_suppliers) else "standard"
    }

@router.post("/requests/{req_id}/status")
async def update_request_status(req_id: str, status_update: StatusUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), http_request: HTTPRequest = None):
    result = await db.execute(
        select(RequestModel).where(RequestModel.req_id == req_id).options(selectinload(RequestModel.project_rel))
    )
    request = result.scalar_one_or_none()
    
    if not request: 
        raise HTTPException(404, detail="Заявка не найдена")
    
    # ✅ Расширенные переходы: директор может утвердить напрямую из "Отправлено на рассмотрение"
    valid_transitions = {
        "Отправлено на рассмотрение": {
            "Выполняется": ["procurement"],
            "Оплачено": ["director"],
            "Договорённость": ["director"],
            "Отклонено": ["procurement", "client", "director"]
        },
        "Выполняется": {
            "Оплачено": ["director"],
            "Договорённость": ["director"],
            "Отклонено": ["director", "procurement"]
        }
    }
    
    allowed_roles = valid_transitions.get(request.status, {}).get(status_update.new_status, [])
    if user.role not in allowed_roles:
        raise HTTPException(403, detail=f"Нельзя перевести в '{status_update.new_status}'")
    
    old_status = request.status
    request.status = status_update.new_status
    request.comment = status_update.comment
    
    if status_update.director_cost is not None and user.role == "director":
        request.director_cost = status_update.director_cost
    
    if status_update.new_status == "Выполняется" and not request.taken_by_id:
        request.taken_by_id = user.id
    
    audit = AuditEntry(
        request_id=request.id,
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
        actor=user.name, action="Изменение статуса", 
        old_status=old_status, new_status=status_update.new_status, 
        comment=status_update.comment
    )
    db.add(audit)
    await db.commit()
    
    client_host = http_request.client.host if http_request and http_request.client else "localhost"
    
    if status_update.new_status in ["Оплачено", "Договорённость", "Отклонено"]:
        await notify_request_finalized(request, db, host=client_host)
    else:
        await notify_status_change(request, status_update.new_status, user.name, status_update.comment or "", db, host=client_host)
    
    return {"ok": True}

@router.get("/requests/{req_id}/details")
async def get_request_details(req_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(RequestModel).where(RequestModel.req_id == req_id).options(
            selectinload(RequestModel.project_rel), selectinload(RequestModel.author_rel),
            selectinload(RequestModel.executor_rel), selectinload(RequestModel.audit_entries)
        )
    )
    request = result.scalar_one_or_none()
    
    if not request:
        raise HTTPException(404, detail="Заявка не найдена")
    
    audit = []
    for entry in sorted(request.audit_entries, key=lambda x: x.timestamp):
        audit.append({
            "timestamp": entry.timestamp, "actor": entry.actor, "action": entry.action,
            "old_status": entry.old_status, "new_status": entry.new_status, "comment": entry.comment
        })
    
    return {
        "id": request.id, "req_id": request.req_id,
        "project_name": request.project_rel.name if request.project_rel else "N/A",
        "author_name": request.author_name,
        "executor_name": request.executor_rel.name if request.executor_rel else "Не назначен",
        "body": request.body, "priority": request.priority, "status": request.status,
        "deadline": request.deadline, "created_date": request.created_date,
        "comment": request.comment, "estimated_cost": request.estimated_cost,
        "director_cost": request.director_cost, "audit": audit
    }

# === УВЕДОМЛЕНИЯ ===
@router.get("/notifications/unread")
async def api_get_unread(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    notifs = await get_unread_notifications(user.id, db)
    return {
        "notifications": [{
            "id": n.id, "title": n.title, "message": n.message,
            "type": n.notification_type, "read": n.read,
            "created_at": n.created_at.isoformat() if n.created_at else None
        } for n in notifs],
        "count": len(notifs)
    }

@router.post("/notifications/read")
async def api_mark_read(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await mark_notifications_read(user.id, db)
    return {"ok": True}

# === ОБРАТНАЯ СОВМЕСТИМОСТЬ ===
@router.get("/dat")
async def get_data(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    projects_result = await db.execute(select(Project).where(Project.archived == False))
    projects = projects_result.scalars().all()
    
    requests_result = await db.execute(
        select(RequestModel).options(selectinload(RequestModel.project_rel), selectinload(RequestModel.author_rel))
    )
    requests = requests_result.scalars().all()
    
    return {
        "projects": {
            "active": [{"id": p.id, "name": p.name, "deadline": p.deadline} for p in projects],
            "archive": []
        },
        "requests": [{
            "id": r.id, "req_id": r.req_id, "project_id": r.project_id,
            "project_name": r.project_rel.name if r.project_rel else "N/A",
            "author_id": r.author_id, "author_name": r.author_name,
            "body": r.body, "priority": r.priority, "status": r.status,
            "deadline": r.deadline, "created_date": r.created_date,
            "comment": r.comment, "taken_by_id": r.taken_by_id,
            "executor_id": r.executor_id, "estimated_cost": r.estimated_cost,
            "director_cost": r.director_cost
        } for r in requests],
        "system": {"statuses": []}
    }