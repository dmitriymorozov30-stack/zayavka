from aiosmtplib import SMTP, SMTPException
from email.message import EmailMessage
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
import os, asyncio, logging
from datetime import datetime
from dotenv import load_dotenv
from .models import User, Request, Notification, AuditEntry

load_dotenv()
logger = logging.getLogger("notifications")

PUBLIC_HOST = os.getenv("PUBLIC_HOST", "localhost")
PORT = os.getenv("PORT", "8000")

SMTP_CONFIG = {
    "hostname": os.getenv("SMTP_SERVER", "mail-01"),
    "port": int(os.getenv("SMTP_PORT", "25")),
    "use_tls": os.getenv("SMTP_USE_TLS", "false").lower() == "true",
    "start_tls": os.getenv("SMTP_START_TLS", "false").lower() == "true",
    "timeout": 30
}

SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_SENDER = os.getenv("SMTP_FROM", "support@stroisservis.ru")
SMTP_MAX_RETRIES = 3
SMTP_RETRY_DELAY = 2

def get_system_url() -> str:
    return f"http://{PUBLIC_HOST}:{PORT}"

def get_service_button(url: str = None, text: str = "СЕРВИС ЗАЯВОК") -> str:
    if url is None:
        url = get_system_url()
    return f"""<div style='text-align:center;margin:24px 0'>
        <a href='{url}' style='display:inline-block;background:#1a3a6b;color:#f5c518;padding:14px 32px;text-decoration:none;border-radius:6px;font-weight:700;font-size:15px;letter-spacing:1.5px;box-shadow:0 4px 12px rgba(26,58,107,0.3);font-family:Arial,sans-serif'>
            {text}
        </a>
    </div>"""

async def send_email(to_email: str, subject: str, html_body: str, max_retries: int = None) -> bool:
    retries = max_retries or SMTP_MAX_RETRIES
    for attempt in range(retries):
        try:
            message = EmailMessage()
            message["From"] = SMTP_SENDER
            message["To"] = to_email
            message["Subject"] = subject
            message.set_content(html_body, subtype="html")
            
            async with SMTP(**SMTP_CONFIG) as smtp:
                if SMTP_USER and SMTP_PASSWORD:
                    await smtp.login(SMTP_USER, SMTP_PASSWORD)
                await smtp.send_message(message)
            
            logger.info(f"✅ Email: {to_email} — {subject}")
            return True
        except Exception as e:
            if attempt < retries - 1:
                logger.warning(f"⚠️ Попытка {attempt+1} не удалась: {e}")
                await asyncio.sleep(SMTP_RETRY_DELAY * (attempt + 1))
            else:
                logger.error(f"❌ Email failed: {e}")
                return False
    return False

async def send_verification_email(email: str, code: str, client_host: str = None) -> bool:
    url = get_system_url()
    html = f"""<div style='font-family:Arial;padding:20px;background:#f8f9fa;text-align:center'>
        <h2 style='color:#1a3a6b'>🔐 Код подтверждения</h2>
        <p style='font-size:24px;letter-spacing:4px;color:#1a3a6b;font-weight:bold'>{code}</p>
        <p style='color:#666'>Действует 15 минут</p>
        {get_service_button(url, "ПЕРЕЙТИ В СЕРВИС ЗАЯВОК")}
    </div>"""
    return await send_email(email, "Код подтверждения — Сервис заявок", html)

async def send_password_reset_email(email: str, code: str, client_host: str = None) -> bool:
    url = get_system_url()
    html = f"""<div style='font-family:Arial;padding:20px;background:#f8f9fa;text-align:center'>
        <h2 style='color:#dc3545'>🔑 Сброс пароля</h2>
        <p style='font-size:24px;letter-spacing:4px;color:#dc3545;font-weight:bold'>{code}</p>
        <p style='color:#666'>Действует 15 минут</p>
        {get_service_button(url, "СБРОСИТЬ ПАРОЛЬ")}
    </div>"""
    return await send_email(email, "Сброс пароля — Сервис заявок", html)

async def notify_supplier_new(request: Request, db: AsyncSession, port: int = None, host: str = None):
    await db.refresh(request, ["project_rel"])
    project_name = request.project_rel.name if request.project_rel else "N/A"
    author_name = request.author_name or "Неизвестно"
    
    suppliers_result = await db.execute(
        select(User).where(User.role == "procurement", User.verified == True, User.deleted == False)
    )
    suppliers = suppliers_result.scalars().all()
    
    if not suppliers:
        logger.warning("⚠️ Нет зарегистрированных снабженцев для уведомления")
        return
    
    subject = f"🆕 Новая заявка от {author_name} на закупку"
    url = get_system_url()
    
    for supplier in suppliers:
        # ✅ Не отправляем самому автору заявки
        if supplier.id == request.author_id:
            continue
        
        html = f"""<div style='font-family:Arial;padding:20px;background:#f8f9fa'>
            <h2 style='color:#1a3a6b;margin:0 0 12px 0'>🆕 Новая заявка от {author_name} на закупку</h2>
            
            <table style='width:100%;border-collapse:collapse;margin-bottom:16px;background:white;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.05)'>
                <tr><td style='padding:8px 12px;border-bottom:1px solid #eee;color:#666;width:120px'><b>Номер:</b></td><td style='padding:8px 12px;border-bottom:1px solid #eee'>{request.req_id}</td></tr>
                <tr><td style='padding:8px 12px;border-bottom:1px solid #eee;color:#666'><b>Проект:</b></td><td style='padding:8px 12px;border-bottom:1px solid #eee'>{project_name}</td></tr>
                <tr><td style='padding:8px 12px;border-bottom:1px solid #eee;color:#666'><b>Срок:</b></td><td style='padding:8px 12px;border-bottom:1px solid #eee'>{request.deadline}</td></tr>
                <tr><td style='padding:8px 12px;color:#666'><b>Приоритет:</b></td><td style='padding:8px 12px'>{request.priority}</td></tr>
            </table>
            
            <div style='background:white;padding:12px;border-radius:8px;margin-bottom:16px;border-left:4px solid #1a3a6b'>
                <b>📋 Описание:</b><br>{request.body}
            </div>
            
            <div style='text-align:center;margin:20px 0'>
                <a href='{url}/?project={project_name}&req={request.req_id}' 
                   style='display:inline-block;background:#1a3a6b;color:#f5c518;padding:12px 28px;text-decoration:none;border-radius:6px;font-weight:700;font-size:14px;letter-spacing:1px;box-shadow:0 4px 12px rgba(26,58,107,0.3)'>
                   🔔 ВЗЯТЬ В РАБОТУ
                </a>
            </div>
            
            <div style='margin-top:20px;padding-top:16px;border-top:1px solid #ddd;text-align:center;font-size:12px;color:#666'>
                {get_service_button(url, "СЕРВИС ЗАЯВОК")}
                <p style='margin-top:4px'>Это автоматическое уведомление. Не отвечайте на это письмо.</p>
            </div>
        </div>"""
        
        await send_email(supplier.email, subject, html)
        
        db.add(Notification(
            user_id=supplier.id,
            request_id=request.id,
            title=subject,
            message=f"Новая заявка {request.req_id} от {author_name} по проекту {project_name}",
            notification_type="new_request",
            read=False
        ))
    
    await db.commit()

# ✅ НОВАЯ ФУНКЦИЯ: уведомление директоров (когда нет снабженцев или заявку создал снабженец)
async def notify_directors_new(request: Request, db: AsyncSession, port: int = None, host: str = None):
    await db.refresh(request, ["project_rel"])
    project_name = request.project_rel.name if request.project_rel else "N/A"
    author_name = request.author_name or "Неизвестно"
    
    directors_result = await db.execute(
        select(User).where(User.role == "director", User.verified == True, User.deleted == False)
    )
    directors = directors_result.scalars().all()
    
    if not directors:
        logger.warning("⚠️ Нет зарегистрированных директоров для уведомления")
        return
    
    subject = f"🆕 Новая заявка от {author_name} (требует вашего решения)"
    url = get_system_url()
    
    for director in directors:
        # ✅ Не отправляем самому автору
        if director.id == request.author_id:
            continue
        
        html = f"""<div style='font-family:Arial;padding:20px;background:#f8f9fa'>
            <h2 style='color:#1a3a6b;margin:0 0 12px 0'>🆕 Новая заявка от {author_name}</h2>
            <p style='color:#666;margin-bottom:16px'>⚠️ Заявка отправлена вам напрямую, так как требует вашего решения.</p>
            
            <table style='width:100%;border-collapse:collapse;margin-bottom:16px;background:white;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.05)'>
                <tr><td style='padding:8px 12px;border-bottom:1px solid #eee;color:#666;width:120px'><b>Номер:</b></td><td style='padding:8px 12px;border-bottom:1px solid #eee'>{request.req_id}</td></tr>
                <tr><td style='padding:8px 12px;border-bottom:1px solid #eee;color:#666'><b>Проект:</b></td><td style='padding:8px 12px;border-bottom:1px solid #eee'>{project_name}</td></tr>
                <tr><td style='padding:8px 12px;border-bottom:1px solid #eee;color:#666'><b>Срок:</b></td><td style='padding:8px 12px;border-bottom:1px solid #eee'>{request.deadline}</td></tr>
                <tr><td style='padding:8px 12px;color:#666'><b>Приоритет:</b></td><td style='padding:8px 12px'>{request.priority}</td></tr>
            </table>
            
            <div style='background:white;padding:12px;border-radius:8px;margin-bottom:16px;border-left:4px solid #f5c518'>
                <b>📋 Описание:</b><br>{request.body}
            </div>
            
            <div style='text-align:center;margin:20px 0'>
                <a href='{url}/?req={request.req_id}' 
                   style='display:inline-block;background:#1a3a6b;color:#f5c518;padding:12px 28px;text-decoration:none;border-radius:6px;font-weight:700;font-size:14px;letter-spacing:1px;box-shadow:0 4px 12px rgba(26,58,107,0.3)'>
                   🔍 ОТКРЫТЬ ЗАЯВКУ
                </a>
            </div>
            
            <div style='margin-top:20px;padding-top:16px;border-top:1px solid #ddd;text-align:center;font-size:12px;color:#666'>
                {get_service_button(url, "СЕРВИС ЗАЯВОК")}
                <p style='margin-top:4px'>Это автоматическое уведомление. Не отвечайте на это письмо.</p>
            </div>
        </div>"""
        
        await send_email(director.email, subject, html)
        
        db.add(Notification(
            user_id=director.id,
            request_id=request.id,
            title=subject,
            message=f"Новая заявка {request.req_id} от {author_name} (прямое обращение)",
            notification_type="new_request_director",
            read=False
        ))
    
    await db.commit()

async def generate_approval_document(request: Request, db: AsyncSession, port: int = None, host: str = None) -> str:
    await db.refresh(request, ["project_rel", "audit_entries"])
    
    audit_entries = request.audit_entries
    
    stages_html = ""
    for entry in sorted(audit_entries, key=lambda x: x.timestamp):
        stamp = "✅" if entry.new_status in ["Оплачено", "Договорённость"] else "⏳"
        stages_html += f"""<tr><td>{stamp}</td><td>{entry.timestamp}</td><td>{entry.actor}</td>
        <td>{entry.action}</td><td><b>{entry.old_status or '—'}</b> → <b>{entry.new_status}</b></td>
        <td>{entry.comment or '—'}</td></tr>"""
    
    project_name = request.project_rel.name if request.project_rel else "N/A"
    url = get_system_url()
    
    if request.status in ["Оплачено", "Договорённость"]:
        stamp_html = """<div style='text-align:center;margin:40px auto;border:5px solid #28a745;color:#28a745;
            font-size:32px;font-weight:bold;padding:12px 24px;transform:rotate(-8deg);border-radius:10px;
            display:inline-block;opacity:0.85'>[ОДОБРЕНО]</div>"""
    elif request.status == "Отклонено":
        stamp_html = """<div style='text-align:center;margin:40px auto;border:5px solid #dc3545;color:#dc3545;
            font-size:32px;font-weight:bold;padding:12px 24px;transform:rotate(-8deg);border-radius:10px;
            display:inline-block;opacity:0.85'>[ОТКЛОНЕНО]</div>"""
    else:
        stamp_html = ""
    
    html = f"""<!DOCTYPE html><html><head><meta charset='UTF-8'><style>
        body{{font-family:Arial,sans-serif;padding:40px;max-width:800px;margin:0 auto;line-height:1.6}}
        .header{{text-align:center;border-bottom:2px solid #1a3a6b;padding-bottom:20px;margin-bottom:30px}}
        table{{width:100%;border-collapse:collapse;margin:20px 0}}th,td{{border:1px solid #ddd;padding:12px;text-align:left}}th{{background:#f8f9fa}}
        .footer{{margin-top:40px;padding-top:20px;border-top:1px solid #ddd;font-size:12px;color:#666;text-align:center}}
    </style></head><body>
    <div class='header'><h1 style='color:#1a3a6b;margin:0'>📋 ЗАЯВКА {request.req_id}</h1><p style='margin:8px 0 0;color:#666'>Проект: {project_name}</p></div>
    
    <h3>📋 Описание</h3><p>{request.body}</p>
    
    <h3>📅 Этапы согласования</h3>
    <table><thead><tr><th>Статус</th><th>Дата</th><th>Исполнитель</th><th>Действие</th><th>Переход</th><th>Комментарий</th></tr></thead><tbody>
    {stages_html}
    </tbody></table>
    
    <div class='footer'>
        {stamp_html}
        <p>Документ сформирован автоматически системой «Сервис заявок»</p>
        <p>Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}</p>
        {get_service_button(url, "СЕРВИС ЗАЯВОК")}
    </div>
    </body></html>"""
    return html

async def notify_request_finalized(request: Request, db: AsyncSession, port: int = None, host: str = None):
    await db.refresh(request, ["project_rel", "author_rel", "executor_rel", "audit_entries"])
    
    participants = set()
    
    if request.author_rel:
        participants.add(request.author_rel.email)
    
    if request.taken_by_id and request.executor_rel:
        participants.add(request.executor_rel.email)
    
    directors_result = await db.execute(select(User).where(User.role == "director", User.verified == True, User.deleted == False))
    for d in directors_result.scalars().all():
        participants.add(d.email)
    
    last_audit = sorted(request.audit_entries, key=lambda x: x.timestamp)[-1] if request.audit_entries else None
    
    if request.status in ["Оплачено", "Договорённость"]:
        subject = f"✅ Заявка {request.req_id} УТВЕРЖДЕНА"
        status_color = "#28a745"
        status_icon = "✅"
        status_text = "УТВЕРЖДЕНА"
    else:
        subject = f"❌ Заявка {request.req_id} ОТКЛОНЕНА"
        status_color = "#dc3545"
        status_icon = "❌"
        status_text = "ОТКЛОНЕНА"
    
    url = get_system_url()
    
    for email in participants:
        html = f"""<div style='font-family:Arial,sans-serif;padding:20px;background:#f8f9fa;max-width:600px;margin:0 auto'>
            <div style='background:{status_color};color:white;padding:16px;border-radius:8px 8px 0 0;text-align:center'>
                <h2 style='margin:0;font-size:20px'>{status_icon} Заявка {request.req_id} {status_text}</h2>
            </div>
            
            <div style='background:white;padding:20px;border-radius:0 0 8px 8px'>
                <table style='width:100%;border-collapse:collapse;margin-bottom:16px'>
                    <tr>
                        <td style='padding:8px 12px;border-bottom:1px solid #eee;color:#666;width:140px'><b>📁 Проект:</b></td>
                        <td style='padding:8px 12px;border-bottom:1px solid #eee'><b>{request.project_rel.name if request.project_rel else 'N/A'}</b></td>
                    </tr>
                    <tr>
                        <td style='padding:8px 12px;border-bottom:1px solid #eee;color:#666'><b>👤 Автор:</b></td>
                        <td style='padding:8px 12px;border-bottom:1px solid #eee'>{request.author_name}</td>
                    </tr>
                    <tr>
                        <td style='padding:8px 12px;border-bottom:1px solid #eee;color:#666'><b>🔧 Исполнитель:</b></td>
                        <td style='padding:8px 12px;border-bottom:1px solid #eee'>{request.executor_rel.name if request.executor_rel else 'Не назначен'}</td>
                    </tr>
                    <tr>
                        <td style='padding:8px 12px;border-bottom:1px solid #eee;color:#666'><b>📅 Срок:</b></td>
                        <td style='padding:8px 12px;border-bottom:1px solid #eee'>{request.deadline or '—'}</td>
                    </tr>
                    <tr>
                        <td style='padding:8px 12px;color:#666'><b>🎯 Приоритет:</b></td>
                        <td style='padding:8px 12px'>{request.priority}</td>
                    </tr>
                </table>
                
                <div style='background:#f8f9fa;padding:12px;border-radius:6px;border-left:4px solid #1a3a6b;margin-bottom:16px'>
                    <b>📋 Описание:</b><br>
                    <span style='color:#333'>{request.body}</span>
                </div>
                
                <div style='background:{status_color}15;padding:12px;border-radius:6px;border-left:4px solid {status_color};margin-bottom:16px'>
                    <b>📌 Решение:</b> {status_text}<br>
                    {f'<b>👤 Кто принял:</b> {last_audit.actor if last_audit else "—"}<br>' if last_audit else ''}
                    {f'<b>🕐 Когда:</b> {last_audit.timestamp if last_audit else "—"}<br>' if last_audit else ''}
                    {f'<b>💬 Комментарий:</b> {request.comment or "Не указан"}' if request.comment else '<b>💬 Комментарий:</b> Не указан'}
                </div>
                
                <div style='text-align:center;margin:20px 0'>
                    <a href='{url}/?req={request.req_id}' 
                       style='display:inline-block;background:#1a3a6b;color:#f5c518;padding:12px 28px;text-decoration:none;border-radius:6px;font-weight:700;font-size:14px;letter-spacing:1px;box-shadow:0 4px 12px rgba(26,58,107,0.3)'>
                       🔍 ОТКРЫТЬ ЗАЯВКУ
                    </a>
                </div>
                
                <div style='text-align:center;margin:20px 0'>
                    <div style='display:inline-block;border:3px solid {status_color};color:{status_color};font-size:20px;font-weight:bold;padding:8px 16px;transform:rotate(-8deg);border-radius:8px;opacity:0.8'>
                        [{status_text}]
                    </div>
                </div>
                
                <div style='margin-top:20px;padding-top:16px;border-top:1px solid #ddd;text-align:center;font-size:11px;color:#666'>
                    {get_service_button(url, "СЕРВИС ЗАЯВОК")}
                    <p style='margin-top:4px'>Документ сформирован автоматически {datetime.now().strftime('%d.%m.%Y %H:%M')}</p>
                </div>
            </div>
        </div>"""
        
        await send_email(email, subject, html)
    
    await db.commit()

async def notify_status_change(request: Request, new_status: str, actor_name: str, comment: str, db: AsyncSession, port: int = None, host: str = None):
    await db.refresh(request, ["project_rel", "author_rel"])
    
    if not request.author_rel:
        return
    
    subject = f"Заявка {request.req_id}: {new_status}"
    url = get_system_url()
    
    html = f"""<div style='font-family:Arial;padding:20px;background:#f8f9fa'>
        <h3 style='color:#1a3a6b;margin-bottom:12px'>🔄 Изменение статуса заявки</h3>
        <p><b>{actor_name}</b> изменил статус заявки <b>{request.req_id}</b> на <b>{new_status}</b>.</p>
        <p><b>Проект:</b> {request.project_rel.name if request.project_rel else 'N/A'}</p>
        {f'<p><b>Комментарий:</b> {comment}</p>' if comment else ''}
        
        <div style='text-align:center;margin:20px 0'>
            <a href='{url}/?project={request.project_rel.name if request.project_rel else ''}&req={request.req_id}' 
               style='display:inline-block;background:#1a3a6b;color:#f5c518;padding:12px 28px;text-decoration:none;border-radius:6px;font-weight:700;font-size:14px;letter-spacing:1px;box-shadow:0 4px 12px rgba(26,58,107,0.3)'>
               🔍 ОТКРЫТЬ ЗАЯВКУ
            </a>
        </div>
        
        <div style='margin-top:20px;padding-top:16px;border-top:1px solid #ddd;text-align:center;font-size:12px;color:#666'>
            {get_service_button(url, "СЕРВИС ЗАЯВОК")}
        </div>
    </div>"""
    await send_email(request.author_rel.email, subject, html)
    
    db.add(Notification(user_id=request.author_rel.id, request_id=request.id, title="🔄 Изменение статуса", message=f"Заявка {request.req_id}: {new_status}", notification_type="status_change", read=False))
    await db.commit()

async def get_unread_notifications(user_id: int, db: AsyncSession):
    result = await db.execute(select(Notification).where(Notification.user_id == user_id, Notification.read == False).order_by(Notification.created_at.desc()).limit(20))
    return result.scalars().all()

async def mark_notifications_read(user_id: int, db: AsyncSession):
    await db.execute(update(Notification).where(Notification.user_id == user_id, Notification.read == False).values(read=True))
    await db.execute(update(User).where(User.id == user_id).values(last_seen_update=datetime.utcnow()))
    await db.commit()