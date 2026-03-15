from datetime import timedelta, datetime, timezone
from typing import Annotated, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import or_
from starlette import status
from jose import jwt, JWTError
from passlib.context import CryptContext
from models import Users, Role, Profile, Post, Comment
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
        .filter(
            or_(
                Users.username == username,
                Users.email == username,
            )
        )
        .first()
    )
    if not user:
        return None

    # Guard: user hasn't set a password yet (pending registration)
    if not user.password_hash:
        return None

    if not bcrypt_context.verify(password, user.password_hash):
        return None

    # تحقق من حالة الحساب
    if not user.is_active:
        # حساب موقوف من الأدمن
        if getattr(user, "is_suspended", False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account has been disabled by an administrator.",
            )
        # حساب غير موافق عليه
        if user.approval_status != "approved":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is not approved yet.",
            )
        # إعادة تفعيل تلقائية للحساب المعطّل ذاتياً
        user.is_active = True
        profile = db.query(Profile).filter(Profile.user_id == user.id).first()
        if profile:
            profile.is_deleted = False
        db.query(Post).filter(
            Post.author_id == user.id, Post.is_deleted == True
        ).update({Post.is_deleted: False}, synchronize_session=False)
        db.query(Comment).filter(
            Comment.author_id == user.id, Comment.is_deleted == True
        ).update({Comment.is_deleted: False}, synchronize_session=False)
        db.commit()
        db.refresh(user)

    if user.approval_status != "approved":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is not approved yet.",
        )

    return user

#انشاء التوكن
def create_access_token(user_id: UUID, role_code: str, expires_delta: timedelta,
                        username: str | None = None, email: str | None = None,
                        fullname: str | None = None) -> str:
    to_encode = {
        "sub": str(user_id),
        "role": role_code,
    }
    if username:
        to_encode["username"] = username
    if email:
        to_encode["email"] = email
    if fullname:
        to_encode["fullname"] = fullname
    expires = datetime.now(timezone.utc) + expires_delta
    to_encode.update({"exp": expires})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# أداة للتحقق من التوكنات في الطلبات (auto_error=False ليمنع الفشل المباشر لو لم يوجد في الـ Header)
oauth2_bearer = OAuth2PasswordBearer(tokenUrl="auth/token", auto_error=False)

# دالة مخصصة لقراءة التوكن من الكوكيز أولاً ثم الـ Header
async def get_token_from_request(
    request: Request,
    token: Optional[str] = Depends(oauth2_bearer)
) -> str:
    cookie_token = request.cookies.get("access_token")
    if cookie_token:
        if cookie_token.startswith("Bearer "):
            return cookie_token.split(" ")[1]
        return cookie_token
    if token:
        return token
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


async def get_current_user(
    token: Annotated[str, Depends(get_token_from_request)],
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
        "fullname": user.fullname,
    }


# Optional auth: returns None for guests instead of raising 401
async def get_current_user_optional(
    request: Request,
    token: Optional[str] = Depends(oauth2_bearer),
    db: Session = Depends(get_db),
):
    actual_token = request.cookies.get("access_token") or token
    if actual_token and actual_token.startswith("Bearer "):
        actual_token = actual_token.split(" ")[1]

    if not actual_token:
        return None
    try:
        payload = jwt.decode(actual_token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id_str: str | None = payload.get("sub")
        if user_id_str is None:
            return None

        user_id = UUID(user_id_str)
        user: Users | None = db.query(Users).filter(Users.id == user_id).first()
        if user is None:
            return None

        role_code = user.role.code if user.role else "user"
        return {
            "id": str(user.id),
            "username": user.username,
            "email": user.email,
            "role_code": role_code,
            "fullname": user.fullname,
        }
    except (JWTError, ValueError):
        return None


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
    response: Response,
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
        username=user.username,
        email=user.email,
        fullname=user.fullname,
    )

    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=86400,
    )

    return {"access_token": token, "token_type": "bearer"}

@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(response: Response):
    response.delete_cookie(
        key="access_token",
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return {"detail": "Logged out successfully"}

@router.get("/me", status_code=status.HTTP_200_OK)
async def get_auth_me(user: Annotated[dict, Depends(get_current_user)]):
    return user






