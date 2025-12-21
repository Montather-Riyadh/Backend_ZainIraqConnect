from typing import Annotated
from sqlmodel import Session
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Path
from starlette import status
from .auth import get_current_user
from models import Users, Post, Comment, Profile, reaction as Reaction
from passlib.context import CryptContext
from core.permissions import require_authenticated, require_role
from database import get_db
from datetime import datetime, timedelta,timezone
from uuid import UUID
import secrets
from fastapi_mail import FastMail, MessageSchema, MessageType
from core.config import conf

fm = FastMail(conf)


router = APIRouter(
    prefix='/user',
    tags=['user']
)


db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]
bcrypt_context = CryptContext(schemes=['bcrypt'], deprecated='auto')



class UserVerification(BaseModel):
    password: str
    new_password: str = Field(min_length=6)


class CompleteRegistrationRequest(BaseModel):
    token: str
    username: str
    password: str


class ReactivateRequest(BaseModel):
    username_or_email: str
    password: str


@router.get('/all', status_code=status.HTTP_200_OK)
async def get_user(user: user_dependency, db: db_dependency):
    require_authenticated(user)

    if user.get("role_code") == "admin":
        return db.query(Users).all()

    return db.query(Users).filter(Users.id == user.get('id')).first()



@router.post("/complete-registration")
async def complete_registration(
    data: CompleteRegistrationRequest,
    db: db_dependency,
):
    user = (
        db.query(Users)
        .filter(Users.registration_token == data.token)
        .first()
    )

    if not user:
        raise HTTPException(400, "Invalid or expired token")

    if user.approval_status != "approved":
        raise HTTPException(400, "Account is not approved")

    now_utc = datetime.now(timezone.utc)
    if user.registration_token_expires_at and user.registration_token_expires_at < now_utc:
    # التوكن منتهي
        raise HTTPException(status_code=400, detail="Registration link has expired")


    # تأكد أن اليوزرنيم غير مكرر
    existing = db.query(Users).filter(Users.username == data.username).first()
    if existing:
        raise HTTPException(400, "Username already taken")

    # نكمل البيانات
    user.username = data.username
    user.password_hash = bcrypt_context.hash(data.password)
    user.is_active = True
    user.registration_token = None
    user.registration_token_expires_at = None
    user.registration_completed_at = datetime.utcnow()

    db.add(user)
    db.commit()
    db.refresh(user)

    return {"detail": "تم إكمال التسجيل، يمكنك الآن تسجيل الدخول."}



@router.put("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(user: user_dependency, db: db_dependency,user_verification: UserVerification):
    require_authenticated(user)
    
    user_model = db.query(Users).filter(Users.id == user.get('id')).first()

    if not bcrypt_context.verify(user_verification.password, user_model.password_hash):
        raise HTTPException(status_code=401, detail='Error on password change')
    user_model.password_hash = bcrypt_context.hash(user_verification.new_password)
    db.add(user_model)
    db.commit()



@router.put("/me/deactivate", status_code=status.HTTP_200_OK)
def deactivate_my_account(
    user: user_dependency,
    db: db_dependency,
):

    require_authenticated(user)

    user_id = user["id"]

    user_model = db.query(Users).filter(Users.id == user_id).first()
    if not user_model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if not user_model.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Account is already inactive",
        )

    user_model.is_active = False

    #  إخفاء/أنونمة البروفايل
    profile = db.query(Profile).filter(Profile.user_id == user_id).first()
    if profile:
        profile.is_deleted = True


    #  إخفاء كل البوستات 
    db.query(Post).filter(Post.author_id == user_id).update(
        {Post.is_deleted: True},
        synchronize_session=False,
    )

    #  إخفاء كل الكومنتات (soft delete)
    db.query(Comment).filter(Comment.author_id == user_id).update(
        {Comment.is_deleted: True},
        synchronize_session=False,
    )

    #  حذف كل اللايكات/الريأكشنز
    db.query(Reaction).filter(Reaction.user_id == user_id).delete(
        synchronize_session=False
    )

    db.add(user_model)
    db.commit()

    return {
        "detail": "تم تعطيل الحساب وإخفاء جميع البيانات المرتبطة به."
    }


@router.post("/reactivate", status_code=status.HTTP_200_OK)
def reactivate_my_account(
    data: ReactivateRequest,
    db: db_dependency,
):

    # نبحث عن اليوزر باليوزرنيم أو الإيميل
    user_model = (
        db.query(Users)
        .filter(
            (Users.username == data.username_or_email)
            | (Users.email == data.username_or_email)
        )
        .first()
    )

    if not user_model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # تأكيد كلمة السر
    if not bcrypt_context.verify(data.password, user_model.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    

    # ما نسمح بإعادة تفعيل حساب موقوف من الأدمن
    if getattr(user_model, "is_suspended", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account has been disabled by an administrator and cannot be reactivated by the user.",
        )

    # ما نسمح بإعادة تفعيل حساب مرفوض أو غير موافَق عليه
    if user_model.approval_status != "approved":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is not approved; cannot be reactivated.",
        )

    # لو الحساب أصلاً فعال
    if user_model.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Account is already active.",
        )
    user_model.is_active = True

# 1) إعادة إظهار البروفايل
    profile = db.query(Profile).filter(Profile.user_id == user_model.id).first()
    if profile:
        profile.is_deleted = False

    db.query(Post).filter(
        Post.author_id == user_model.id,
        Post.is_deleted == True
    ).update(
        {Post.is_deleted: False},
        synchronize_session=False,
    )

    db.query(Comment).filter(
        Comment.author_id == user_model.id,
        Comment.is_deleted == True
    ).update(
        {Comment.is_deleted: False},
        synchronize_session=False,
    )

    db.add(user_model)
    db.commit()

    return {
        "detail": "تمت إعادة تفعيل الحساب وإظهار المنشورات والتعليقات المخفية. يمكنك الآن تسجيل الدخول من جديد."
    }




@router.delete("/me", status_code=status.HTTP_200_OK)
def delete_my_account(
    current_user: user_dependency,
    db: db_dependency,
):
    """
    حذف الحساب الحالي + كل البيانات المرتبطة به نهائياً من قاعدة البيانات.
    """

    # نتأكد أن المستخدم مسجّل دخول
    require_authenticated(current_user)

    user_id = current_user["id"]

    user_model = db.get(Users, user_id)
    if not user_model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # هنا فقط نحذف صف اليوزر، وكل شيء آخر سيُحذف تلقائياً بالـ ON DELETE CASCADE
    db.delete(user_model)
    db.commit()

    return {
        "detail": "تم حذف الحساب وجميع البيانات المرتبطة به بشكل نهائي."
    }



# موافقة على مستخدم
@router.put("/admin/{user_id}/approve", status_code=status.HTTP_204_NO_CONTENT)
async def approve_user(user_id: str,db: db_dependency,current_user: user_dependency,):
    require_role(current_user, "admin", "registrar")

    user_model = db.query(Users).filter(Users.id == user_id).first()
    if not user_model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if user_model.approval_status == "approved":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already approved",
        )

    # تحديث حالة الموافقة
    user_model.approval_status = "approved"
    user_model.is_active = False  # لن يفعَل إلا بعد إكمال التسجيل
    user_model.approved_by = UUID(current_user["id"])
    user_model.approved_at = datetime.utcnow()

    # توليد توكن إكمال التسجيل
    user_model.registration_token = secrets.token_urlsafe(32)
    user_model.registration_token_expires_at = datetime.utcnow() + timedelta(hours=24)

    db.add(user_model)
    db.commit()
    db.refresh(user_model)

    # إرسال الإيميل
    link = f"https://frontend.com/complete-registration?token={user_model.registration_token}"

    html = f"""
    <h2>مرحباً {user_model.fullname}</h2>
    <p>تمت الموافقة على طلب انضمامك. لإكمال إنشاء الحساب، اضغط على الرابط التالي:</p>
    <p><a href="{link}">إكمال التسجيل</a></p>
    """

    message = MessageSchema(
        subject="إكمال تسجيل حسابك",
        recipients=[user_model.email],
        body=html,
        subtype=MessageType.html,
    )

    await fm.send_message(message)

    return {
        "detail": "User approved and registration email sent.",
        "user_id": str(user_model.id),
    }


@router.put("/admin/{user_id}/reject", status_code=status.HTTP_200_OK)
async def reject_user(
    user_id: str,
    db: db_dependency,
    user: user_dependency,
):
    # فقط أدمن أو ريجستر
    require_role(user, "admin", "registrar")

    user_model = db.query(Users).filter(Users.id == user_id).first()
    if not user_model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # ممكن تسمح ترفض فقط لو كان pending
    if user_model.approval_status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only pending users can be rejected",
        )

    #  نغيّر حالة الموافقة
    user_model.approval_status = "rejected"
    user_model.is_active = False  # ميت حسابياً

    #  من اللي رفض ومتى؟
    user_model.approved_by = UUID(user["id"])
    user_model.approved_at = datetime.utcnow()

    db.add(user_model)
    db.commit()
    db.refresh(user_model)

    return user_model



@router.put("/admin/{user_id}/stop", status_code=status.HTTP_200_OK)
async def stop_account(
    user_id: str,
    db: db_dependency,
    user: user_dependency,
):
    # فقط أدمن أو ريجستر (أو نكدر نخليها أدمن فقط)
    require_role(user, "admin", "registrar")

    user_model = db.query(Users).filter(Users.id == user_id).first()
    if not user_model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if not user_model.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Account is already inactive",
        )

    #  إيقاف الحساب
    user_model.is_active = False
    user_model.is_suspended = True

    #  نسجّل من أوقفه ومتى
    user_model.approved_by = UUID(user["id"])
    user_model.approved_at = datetime.utcnow()

    db.add(user_model)
    db.commit()
    db.refresh(user_model)

    return user_model


@router.put("/admin/{user_id}/unsuspend", status_code=status.HTTP_200_OK)
async def unsuspend_account(
    user_id: str,
    db: db_dependency,
    user: user_dependency,
):
    require_role(user, "admin", "registrar")

    user_model = db.query(Users).filter(Users.id == user_id).first()
    if not user_model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if not user_model.is_suspended:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Account is not suspended",
        )

    user_model.is_suspended = False
    user_model.is_active = True

    user_model.approved_by = UUID(user["id"])
    user_model.approved_at = datetime.utcnow()

    db.add(user_model)
    db.commit()
    db.refresh(user_model)

    return user_model






