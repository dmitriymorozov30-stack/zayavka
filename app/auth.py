from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, Field, field_validator
import os, random, string, re
from dotenv import load_dotenv

from .database import get_db
from .models import User

load_dotenv()

SECRET_KEY = os.getenv("JWT_SECRET", "fallback-secret-key-change-in-production-1234567890")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)

class UserRegister(BaseModel):
    username: str
    password: str = Field(..., min_length=6)
    role: str
    name: str
    
    @field_validator('username')
    @classmethod
    def validate_email(cls, v: str) -> str:
        if not v.endswith('@stroisservis.ru'):
            raise ValueError('Только @stroisservis.ru')
        if not re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', v):
            raise ValueError('Неверный формат email')
        return v.lower()

class UserLogin(BaseModel):
    username: str
    password: str

class VerifyCode(BaseModel):
    username: str
    code: str = Field(..., min_length=6, max_length=6)

class ForgotPassword(BaseModel):
    email: str

class ResetPassword(BaseModel):
    email: str
    code: str = Field(..., min_length=6, max_length=6)
    new_password: str = Field(..., min_length=6)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def generate_secure_code(length: int = 6) -> str:
    return ''.join(random.choices(string.digits, k=length))

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security), 
    db: AsyncSession = Depends(get_db)
) -> User:
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        token_type: str = payload.get("type")
        if not username or token_type != "access":
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    result = await db.execute(select(User).where(User.username == username, User.deleted == False))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

async def register_user(user_data: UserRegister, db: AsyncSession, request: Request = None) -> dict:
    from .notifications import send_verification_email
    
    if not user_data.username.endswith('@stroisservis.ru'):
        raise HTTPException(400, detail="Только корпоративные email @stroisservis.ru")
    
    result = await db.execute(select(User).where(User.username == user_data.username, User.deleted == False))
    if result.scalar_one_or_none():
        raise HTTPException(400, detail="Email уже зарегистрирован")
    
    code = generate_secure_code()
    expires = datetime.utcnow() + timedelta(minutes=15)
    
    new_user = User(
        username=user_data.username, email=user_data.username, name=user_data.name,
        hashed_password=get_password_hash(user_data.password), role=user_data.role,
        verified=False, verification_code=code, verification_code_expires=expires,
        deleted=False, last_seen_update=datetime.utcnow(), login_attempts=0, locked_until=None
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    
    client_host = request.client.host if request else "localhost"
    await send_verification_email(user_data.username, code, client_host)
    
    return {"ok": True, "message": "Код подтверждения отправлен на email"}

async def verify_2fa(data: VerifyCode, db: AsyncSession) -> dict:
    result = await db.execute(select(User).where(User.username == data.username, User.verified == False, User.deleted == False))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(400, detail="Пользователь не найден или уже подтверждён")
    if user.verification_code_expires and user.verification_code_expires < datetime.utcnow():
        raise HTTPException(400, detail="Код истёк")
    if user.verification_code != data.code:
        raise HTTPException(400, detail="Неверный код")
    
    user.verified = True
    user.verification_code = None
    user.verification_code_expires = None
    await db.commit()
    
    return {"ok": True, "message": "Аккаунт подтверждён"}

async def login_user(login_data: UserLogin, db: AsyncSession, request: Request = None) -> dict:
    result = await db.execute(select(User).where(User.username == login_data.username, User.deleted == False))
    user = result.scalar_one_or_none()
    
    if not user or not verify_password(login_data.password, user.hashed_password):
        raise HTTPException(401, detail="Неверный email или пароль")
    if not user.verified:
        raise HTTPException(401, detail="Подтвердите email кодом из письма")
    
    token = create_access_token(data={"sub": user.username})
    
    return {
        "ok": True, "access_token": token, "token_type": "bearer",
        "user": {"username": user.username, "role": user.role, "name": user.name, "read_requests": user.read_requests or []}
    }

# ✅ ИСПРАВЛЕННАЯ ФУНКЦИЯ: явная ошибка если email не зарегистрирован
async def forgot_password(data: ForgotPassword, db: AsyncSession, request: Request = None) -> dict:
    from .notifications import send_password_reset_email
    
    result = await db.execute(select(User).where(User.username == data.email, User.deleted == False))
    user = result.scalar_one_or_none()
    
    # ✅ Явная ошибка если email не зарегистрирован
    if not user:
        raise HTTPException(400, detail="❌ Email не зарегистрирован в системе")
    
    code = generate_secure_code()
    expires = datetime.utcnow() + timedelta(minutes=15)
    user.verification_code = code
    user.verification_code_expires = expires
    await db.commit()
    
    client_host = request.client.host if request else "localhost"
    await send_password_reset_email(data.email, code, client_host)
    
    return {"ok": True, "message": "Код отправлен на email"}

async def reset_password(data: ResetPassword, db: AsyncSession) -> dict:
    result = await db.execute(select(User).where(User.username == data.email, User.verification_code == data.code, User.deleted == False))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(400, detail="Неверный код или email")
    if user.verification_code_expires and user.verification_code_expires < datetime.utcnow():
        raise HTTPException(400, detail="Код истёк")
    
    user.hashed_password = get_password_hash(data.new_password)
    user.verification_code = None
    user.verification_code_expires = None
    user.verified = True
    await db.commit()
    
    return {"ok": True, "message": "Пароль успешно изменён"}