from datetime import timedelta, datetime, timezone
from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette import status
from jose import jwt, JWTError
from passlib.context import CryptContext
from models import Users, Role
from database import get_db
import os
from dotenv import load_dotenv

# تحميل المتغيرات من .env
load_dotenv()

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")

# أداة لتشفير/التحقق من كلمات المرور
bcrypt_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
# أداة للتحقق من التوكنات في الطلبات
oauth2_bearer = OAuth2PasswordBearer(tokenUrl="auth/token")
# اختصار للاعتماد على قاعدة البيانات
db_dependency = Annotated[Session, Depends(get_db)]


class CreateUserRequest(BaseModel):
    fullname: str
    email: str


class Token(BaseModel):
    access_token: str
    token_type: str


#التحقق من بيانات المستخدم
def authenticate_user(username: str, password: str, db: Session) -> Users | None:
    user: Users | None = (
        db.query(Users)
        .filter(Users.username == username)
        .first()
    )
    if not user:
        return None

    if not bcrypt_context.verify(password, user.password_hash):
        return None

    # تحقق من حالة الحساب
    if not user.is_active or user.approval_status != "approved":
        # ممكن ترجع None وتخلي الرسالة عامة، أو ترجع خطأ برسالة واضحة
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is not active or not approved yet."
        )

    return user

#انشاء التوكن
def create_access_token(user_id: UUID, role_code: str, expires_delta: timedelta) -> str:
    to_encode = {
        "sub": str(user_id),
        "role": role_code,
    }
    expires = datetime.now(timezone.utc) + expires_delta
    to_encode.update({"exp": expires})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

#التحقق من التوكن
async def get_current_user(
    token: Annotated[str, Depends(oauth2_bearer)],
    db: Session = Depends(get_db),
):
    try:
        # فك تشفير التوكن والتحقق منه
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id_str: str | None = payload.get("sub")
        role_code: str | None = payload.get("role")

        if user_id_str is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate user.",
            )

        user_id = UUID(user_id_str)
    except (JWTError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate user.",
        )

    user: Users | None = db.query(Users).filter(Users.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found.",
        )
    # ممكن تعيد تحميل role من DB لو تريد تتأكد أنه ما تغيّر
    role_code = user.role.code if user.role else role_code or "user"


    if getattr(user, "is_suspended", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account has been disabled by an administrator.",
        )

    if not user.is_active or user.approval_status != "approved":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is not active or not approved.",
        )

    return {
        "id": str(user.id),
        "username": user.username,
        "email": user.email,
        "role_code": role_code,
    }


# ----------------------------------------
# Routes
# ----------------------------------------

@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_user(
    create_user_request: CreateUserRequest,
    db: db_dependency,
):
    # تأكيد عدم تكرار الإيميل/اليوزرنيم
    existing = (
        db.query(Users)
        .filter(Users.email == create_user_request.email).first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or email already exists.",
        )

    # إيجاد role الافتراضي 'user'
    user_role: Role | None = db.query(Role).filter(Role.code == "user").first()
    if user_role is None:
        raise HTTPException(
            status_code=500,
            detail="Default role 'user' is not configured.",
        )

    user = Users(
        email=create_user_request.email,
        username=None,
        role_id=user_role.role_id,
        fullname=create_user_request.fullname,
        password_hash=None,
        is_active=False,              
        approval_status="pending",   
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return {"id": str(user.id), "username": user.username}


@router.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: db_dependency,
):
    user = authenticate_user(form_data.username, form_data.password, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate user.",
        )

    role_code = user.role.code if user.role else "user"
    token = create_access_token(
        user_id=user.id,
        role_code=role_code,
        expires_delta=timedelta(hours=24),
    )

    return {"access_token": token, "token_type": "bearer"}






