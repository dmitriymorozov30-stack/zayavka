from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, Float
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

# ✅ Импортируем Base из database.py вместо создания нового
from .database import Base

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, nullable=False)
    
    verified = Column(Boolean, default=False)
    verification_code = Column(String, nullable=True)
    verification_code_expires = Column(DateTime, nullable=True)
    login_attempts = Column(Integer, default=0)
    locked_until = Column(DateTime, nullable=True)
    
    last_seen_update = Column(DateTime, default=func.now())
    last_login = Column(DateTime, nullable=True)
    last_login_ip = Column(String, nullable=True)
    
    deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime, nullable=True)
    
    read_requests = Column(String, default="[]")
    
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")
    requests_as_author = relationship("Request", foreign_keys="Request.author_id", back_populates="author_rel")
    requests_as_executor = relationship("Request", foreign_keys="Request.taken_by_id", back_populates="executor_rel")

class Project(Base):
    __tablename__ = "projects"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    deadline = Column(String, nullable=True)
    archived = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())
    
    requests = relationship("Request", back_populates="project_rel", cascade="all, delete-orphan")

class Request(Base):
    __tablename__ = "requests"
    
    id = Column(Integer, primary_key=True, index=True)
    
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    taken_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    executor_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # ✅ Исполнитель
    
    req_id = Column(String, unique=True, index=True, nullable=False)
    body = Column(Text, nullable=False)
    priority = Column(String, default="medium")
    status = Column(String, default="Отправлено на рассмотрение")
    deadline = Column(String, nullable=True)
    created_date = Column(String, nullable=False)
    comment = Column(Text, nullable=True)
    
    # ✅ Новые поля для стоимости
    estimated_cost = Column(Float, nullable=True)      # Ориентировочная стоимость
    director_cost = Column(Float, nullable=True)       # Стоимость от руководителя
    
    author_name = Column(String, nullable=False)
    
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    project_rel = relationship("Project", back_populates="requests")
    author_rel = relationship("User", foreign_keys=[author_id], back_populates="requests_as_author")
    executor_rel = relationship("User", foreign_keys=[executor_id])
    taken_by_rel = relationship("User", foreign_keys=[taken_by_id], overlaps="requests_as_executor")
    audit_entries = relationship("AuditEntry", back_populates="request_rel", cascade="all, delete-orphan")

class AuditEntry(Base):
    __tablename__ = "audit"
    
    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(Integer, ForeignKey("requests.id"), nullable=False)
    
    timestamp = Column(String, nullable=False)
    actor = Column(String, nullable=False)
    action = Column(String, nullable=False)
    old_status = Column(String, nullable=True)
    new_status = Column(String, nullable=False)
    comment = Column(Text, nullable=True)
    
    request_rel = relationship("Request", back_populates="audit_entries")

class Notification(Base):
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    request_id = Column(Integer, ForeignKey("requests.id"), nullable=True)
    
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    notification_type = Column(String, nullable=False)
    read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())
    
    user = relationship("User", back_populates="notifications")