from typing import Annotated, Optional
from sqlmodel import Session
from pydantic import BaseModel, Field
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, Query, Request, Response
from starlette import status
from .auth import get_current_user
from models import Users, Post, Comment, Profile, Reaction, Friendship, RefreshToken
from passlib.context import CryptContext
from core.permissions import require_authenticated, require_role, is_admin, require_db_permission
from database import get_db
from datetime import datetime, timedelta,timezone
from uuid import UUID
import secrets
import os
import hashlib
from dotenv import load_dotenv
from fastapi_mail import FastMail, MessageSchema, MessageType
from fastapi_cache.decorator import cache
from core.config import conf
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

load_dotenv()
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


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=6)


class CompleteRegistrationRequest(BaseModel):
    token: str
    username: str
    password: str


class ReactivateRequest(BaseModel):
    username_or_email: str
    password: str


@router.get('/all', status_code=status.HTTP_200_OK)
async def get_user(
    user: user_dependency, 
    db: db_dependency,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100)
):
    require_authenticated(user)

    if user.get("role_code") == "admin":
        return db.query(Users).offset(skip).limit(limit).all()

    return db.query(Users).filter(Users.id == user.get('id')).first()


@router.get("/validate-registration-token")
async def validate_registration_token(
    token: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
):
    """
    يتحقق من صلاحية توكن إكمال التسجيل.
    يُستدعى من الفرونت إند عند فتح صفحة /register.
    """
    user = (
        db.query(Users)
        .filter(Users.registration_token == token)
        .first()
    )

    if not user:
        raise HTTPException(400, "Invalid or expired token")

    if user.registration_completed_at is not None:
        raise HTTPException(400, "Registration already completed")

    if user.approval_status != "approved":
        raise HTTPException(400, "Account is not approved")

    now_utc = datetime.now(timezone.utc)
    if user.registration_token_expires_at and user.registration_token_expires_at < now_utc:
        raise HTTPException(400, "Registration link has expired")

    return {
        "valid": True,
        "fullname": user.fullname,
        "email": user.email,
    }


@router.post("/complete-registration")
@limiter.limit("5/minute")
async def complete_registration(
    request: Request,
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

    # حماية: هل أكمل التسجيل مسبقاً؟
    if user.registration_completed_at is not None:
        raise HTTPException(400, "Registration already completed")

    if user.approval_status != "approved":
        raise HTTPException(400, "Account is not approved")

    now_utc = datetime.now(timezone.utc)
    if user.registration_token_expires_at and user.registration_token_expires_at < now_utc:
        raise HTTPException(status_code=400, detail="Registration link has expired")

    # التحقق من طول كلمة المرور وقوتها
    import re
    password_regex = r"^(?=.*[A-Z])(?=.*[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]).{6,}$"
    if not re.match(password_regex, data.password):
        raise HTTPException(400, "Password must be at least 6 characters, contain 1 uppercase letter, and 1 special character.")

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
    user.registration_completed_at = datetime.now(timezone.utc)

    db.add(user)
    db.commit()
    db.refresh(user)

    return {"detail": "تم إكمال التسجيل، يمكنك الآن تسجيل الدخول."}

class ResendRegistrationRequest(BaseModel):
    email: str

@router.post("/resend-registration", status_code=status.HTTP_200_OK)
@limiter.limit("3/minute")
async def resend_registration(
    request: Request,
    data: ResendRegistrationRequest,
    db: db_dependency,
    background_tasks: BackgroundTasks,
):
    """
    إعادة إرسال رابط إكمال التسجيل للمستخدمين الذين تمت الموافقة عليهم ولم يكملوا التسجيل.
    """
    user = db.query(Users).filter(Users.email == data.email).first()

    if not user:
        return {"detail": "If your account is approved and pending registration, a new link will be sent."}

    if user.approval_status != "approved":
        return {"detail": "If your account is approved and pending registration, a new link will be sent."}

    if user.registration_completed_at is not None:
        raise HTTPException(status_code=400, detail="Registration already completed")

    # Generate new token
    user.registration_token = secrets.token_urlsafe(32)
    user.registration_token_expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

    db.add(user)
    db.commit()
    db.refresh(user)

    # Send Email
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
    link = f"{frontend_url}/register?token={user.registration_token}"

    html = f"""
    <!DOCTYPE html>
    <html dir="rtl" lang="ar">
    <head><meta charset="UTF-8"></head>
    <body style="margin:0;padding:0;background-color:#f4f7fa;font-family:Arial,sans-serif;">
      <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f7fa;padding:40px 0;">
        <tr><td align="center">
          <table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">
            <tr>
              <td style="background:linear-gradient(135deg,#0d9488,#115e59);padding:32px 40px;text-align:center;">
                <h1 style="margin:0;color:#ffffff;font-size:24px;">IraqConnect</h1>
              </td>
            </tr>
            <tr>
              <td style="padding:40px;">
                <h2 style="margin:0 0 16px;color:#1e293b;font-size:20px;">مرحباً {user.fullname} 👋</h2>
                <p style="color:#475569;font-size:15px;line-height:1.8;margin:0 0 24px;">
                  لقد طلبت إعادة إرسال رابط إكمال التسجيل الخاص بك.
                  لإكمال إنشاء حسابك، يرجى الضغط على الزر أدناه لاختيار اسم المستخدم وكلمة المرور.
                </p>
                <table cellpadding="0" cellspacing="0" width="100%">
                  <tr><td align="center" style="padding:8px 0 24px;">
                    <a href="{link}" style="display:inline-block;background:linear-gradient(135deg,#0d9488,#14b8a6);color:#ffffff;text-decoration:none;padding:14px 40px;border-radius:8px;font-size:16px;font-weight:bold;box-shadow:0 4px 14px rgba(13,148,136,0.3);">
                      إكمال التسجيل
                    </a>
                  </td></tr>
                </table>
                <p style="color:#94a3b8;font-size:13px;line-height:1.6;margin:0;border-top:1px solid #e2e8f0;padding-top:20px;">
                  ⏳ هذا الرابط صالح لمدة <strong>24 ساعة</strong> فقط.<br>
                  إذا لم تقم بطلب هذا الرابط، يمكنك تجاهل هذه الرسالة.
                </p>
              </td>
            </tr>
            <tr>
              <td style="background:#f8fafc;padding:20px 40px;text-align:center;border-top:1px solid #e2e8f0;">
                <p style="margin:0;color:#94a3b8;font-size:12px;">© 2026 ZainIraqConnect. جميع الحقوق محفوظة.</p>
              </td>
            </tr>
          </table>
        </td></tr>
      </table>
    </body>
    </html>
    """

    message = MessageSchema(
        subject="🔄 رابط جديد - أكمل تسجيل حسابك",
        recipients=[user.email],
        body=html,
        subtype=MessageType.html,
    )

    background_tasks.add_task(fm.send_message, message)

    return {"detail": "If your account is approved and pending registration, a new link will be sent."}



@router.post("/forgot-password", status_code=status.HTTP_200_OK)
@limiter.limit("3/minute")
async def forgot_password(
    request: Request,
    data: ForgotPasswordRequest,
    db: db_dependency,
    background_tasks: BackgroundTasks,
):
    user = db.query(Users).filter(Users.email == data.email).first()

    if not user:
        # Don't reveal if email exists or not for security, just return success
        return {"detail": "If your email is registered, you will receive a password reset link."}

    # Only process if active and approved
    if not user.is_active or user.approval_status != "approved":
        raise HTTPException(status_code=400, detail="Account is not active or pending approval")

    if getattr(user, "is_suspended", False):
        raise HTTPException(status_code=400, detail="Account is suspended. You cannot reset your password.")

    # Generate reset token (reusing registration_token fields)
    user.registration_token = secrets.token_urlsafe(32)
    user.registration_token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

    db.add(user)
    db.commit()

    # Send Email
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
    link = f"{frontend_url}/login/reset-password?token={user.registration_token}"

    html = f"""
    <!DOCTYPE html>
    <html dir="rtl" lang="ar">
    <head><meta charset="UTF-8"></head>
    <body style="margin:0;padding:0;background-color:#f4f7fa;font-family:Arial,sans-serif;">
      <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f7fa;padding:40px 0;">
        <tr><td align="center">
          <table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">
            <tr>
              <td style="background:linear-gradient(135deg,#0d9488,#115e59);padding:32px 40px;text-align:center;">
                <h1 style="margin:0;color:#ffffff;font-size:24px;">IraqConnect</h1>
              </td>
            </tr>
            <tr>
              <td style="padding:40px;">
                <h2 style="margin:0 0 16px;color:#1e293b;font-size:20px;">مرحباً {user.fullname} 👋</h2>
                <p style="color:#475569;font-size:15px;line-height:1.8;margin:0 0 24px;">
                  لقد تلقينا طلباً لإعادة تعيين كلمة المرور الخاصة بحسابك.
                  إذا قمت بهذا الطلب، يرجى الضغط على الزر أدناه لاختيار كلمة مرور جديدة.
                </p>
                <table cellpadding="0" cellspacing="0" width="100%">
                  <tr><td align="center" style="padding:8px 0 24px;">
                    <a href="{link}" style="display:inline-block;background:linear-gradient(135deg,#0d9488,#14b8a6);color:#ffffff;text-decoration:none;padding:14px 40px;border-radius:8px;font-size:16px;font-weight:bold;box-shadow:0 4px 14px rgba(13,148,136,0.3);">
                      إعادة تعيين كلمة المرور
                    </a>
                  </td></tr>
                </table>
                <p style="color:#94a3b8;font-size:13px;line-height:1.6;margin:0;border-top:1px solid #e2e8f0;padding-top:20px;">
                  ⏳ هذا الرابط صالح لمدة <strong>ساعة واحدة</strong> فقط.<br>
                  إذا لم تقم بهذا الطلب، يمكنك تجاهل هذه الرسالة ولن يتم تغيير كلمة المرور الخاصة بك.
                </p>
              </td>
            </tr>
            <tr>
              <td style="background:#f8fafc;padding:20px 40px;text-align:center;border-top:1px solid #e2e8f0;">
                <p style="margin:0;color:#94a3b8;font-size:12px;">© 2026 ZainIraqConnect. جميع الحقوق محفوظة.</p>
              </td>
            </tr>
          </table>
        </td></tr>
      </table>
    </body>
    </html>
    """

    message = MessageSchema(
        subject="🔒 إعادة تعيين كلمة المرور - IraqConnect",
        recipients=[user.email],
        body=html,
        subtype=MessageType.html,
    )

    background_tasks.add_task(fm.send_message, message)

    return {"detail": "If your email is registered, you will receive a password reset link."}


@router.post("/reset-password", status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")
async def reset_password(
    request: Request,
    data: ResetPasswordRequest,
    db: db_dependency,
):
    user = (
        db.query(Users)
        .filter(Users.registration_token == data.token)
        .first()
    )

    if not user:
        raise HTTPException(400, "Invalid or expired reset token")

    if not user.is_active or user.approval_status != "approved" or user.is_suspended:
        raise HTTPException(400, "Account is not active, pending approval, or suspended")

    now_utc = datetime.now(timezone.utc)
    if user.registration_token_expires_at and user.registration_token_expires_at < now_utc:
        raise HTTPException(400, "Reset link has expired")

    # Enforce strong password rules matching frontend
    import re
    password_regex = r"^(?=.*[A-Z])(?=.*[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]).{6,}$"
    if not re.match(password_regex, data.new_password):
        raise HTTPException(400, "Password must be at least 6 characters, contain 1 uppercase letter, and 1 special character.")

    # Update password and clear token
    user.password_hash = bcrypt_context.hash(data.new_password)
    user.registration_token = None
    user.registration_token_expires_at = None

    db.add(user)
    db.commit()

    return {"detail": "Password has been successfully reset. You can now login."}


@router.put("/me/change-password", status_code=status.HTTP_200_OK)
async def change_password(user: user_dependency, db: db_dependency, user_verification: UserVerification):
    require_authenticated(user)
    
    user_model = db.query(Users).filter(Users.id == user.get('id')).first()

    if not bcrypt_context.verify(user_verification.password, user_model.password_hash):
        raise HTTPException(status_code=401, detail='Error on password change')

    # Enforce strong password
    import re
    password_regex = r"^(?=.*[A-Z])(?=.*[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]).{6,}$"
    if not re.match(password_regex, user_verification.new_password):
        raise HTTPException(400, "Password must be at least 6 characters, contain 1 uppercase letter, and 1 special character.")

    user_model.password_hash = bcrypt_context.hash(user_verification.new_password)
    db.add(user_model)
    db.commit()

    return {"detail": "Password changed successfully"}



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
@limiter.limit("5/minute")
def reactivate_my_account(
    request: Request,
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
async def approve_user(user_id: UUID, db: db_dependency, current_user: user_dependency, background_tasks: BackgroundTasks):
    require_db_permission(current_user, db, "MANAGE_REGISTRATION")

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
    user_model.approved_at = datetime.now(timezone.utc)

    # توليد توكن إكمال التسجيل
    user_model.registration_token = secrets.token_urlsafe(32)
    user_model.registration_token_expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

    db.add(user_model)
    db.commit()
    db.refresh(user_model)

    # إرسال الإيميل
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
    link = f"{frontend_url}/register?token={user_model.registration_token}"

    html = f"""
    <!DOCTYPE html>
    <html dir="rtl" lang="ar">
    <head><meta charset="UTF-8"></head>
    <body style="margin:0;padding:0;background-color:#f4f7fa;font-family:Arial,sans-serif;">
      <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f7fa;padding:40px 0;">
        <tr><td align="center">
          <table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">
            <!-- Header -->
            <tr>
              <td style="background:linear-gradient(135deg,#0d9488,#115e59);padding:32px 40px;text-align:center;">
                <h1 style="margin:0;color:#ffffff;font-size:24px;">IraqConnect</h1>
              </td>
            </tr>
            <!-- Body -->
            <tr>
              <td style="padding:40px;">
                <h2 style="margin:0 0 16px;color:#1e293b;font-size:20px;">مرحباً {user_model.fullname} 👋</h2>
                <p style="color:#475569;font-size:15px;line-height:1.8;margin:0 0 24px;">
                  يسعدنا إبلاغك بأنه تمت <strong style="color:#0d9488;">الموافقة</strong> على طلب انضمامك!
                  لإكمال إنشاء حسابك، يرجى الضغط على الزر أدناه لاختيار اسم المستخدم وكلمة المرور.
                </p>
                <table cellpadding="0" cellspacing="0" width="100%">
                  <tr><td align="center" style="padding:8px 0 24px;">
                    <a href="{link}" style="display:inline-block;background:linear-gradient(135deg,#0d9488,#14b8a6);color:#ffffff;text-decoration:none;padding:14px 40px;border-radius:8px;font-size:16px;font-weight:bold;box-shadow:0 4px 14px rgba(13,148,136,0.3);">
                      إكمال التسجيل
                    </a>
                  </td></tr>
                </table>
                <p style="color:#94a3b8;font-size:13px;line-height:1.6;margin:0;border-top:1px solid #e2e8f0;padding-top:20px;">
                  ⏳ هذا الرابط صالح لمدة <strong>24 ساعة</strong> فقط.<br>
                  إذا لم تقم بطلب الانضمام، يمكنك تجاهل هذه الرسالة.
                </p>
              </td>
            </tr>
            <!-- Footer -->
            <tr>
              <td style="background:#f8fafc;padding:20px 40px;text-align:center;border-top:1px solid #e2e8f0;">
                <p style="margin:0;color:#94a3b8;font-size:12px;">© 2026 ZainIraqConnect. جميع الحقوق محفوظة.</p>
              </td>
            </tr>
          </table>
        </td></tr>
      </table>
    </body>
    </html>
    """

    message = MessageSchema(
        subject="✅ تمت الموافقة — أكمل تسجيل حسابك",
        recipients=[user_model.email],
        body=html,
        subtype=MessageType.html,
    )

    background_tasks.add_task(fm.send_message, message)

    return {
        "detail": "User approved and registration email sent.",
        "user_id": str(user_model.id),
    }


@router.put("/admin/{user_id}/reject", status_code=status.HTTP_200_OK)
async def reject_user(
    user_id: UUID,
    db: db_dependency,
    user: user_dependency,
):
    require_db_permission(user, db, "MANAGE_REGISTRATION")

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
    user_model.approved_at = datetime.now(timezone.utc)

    db.add(user_model)
    db.commit()
    db.refresh(user_model)

    return user_model



@router.put("/admin/{user_id}/stop", status_code=status.HTTP_200_OK)
async def stop_account(
    user_id: UUID,
    db: db_dependency,
    user: user_dependency,
):
    # فقط أدمن أو ريجستر (أو نكدر نخليها أدمن فقط)
    require_db_permission(user, db, "STOP_ACCOUNT")

    # ✅ AUTH-04: Prevent admin from suspending their own account
    if str(user_id) == str(user["id"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot suspend your own account",
        )

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

    #  إبطال جميع Refresh Tokens النشطة
    db.query(RefreshToken).filter(
        RefreshToken.user_id == user_id,
        RefreshToken.is_revoked == False
    ).update({"is_revoked": True}, synchronize_session=False)

    #  نسجّل من أوقفه ومتى
    user_model.approved_by = UUID(user["id"])
    user_model.approved_at = datetime.now(timezone.utc)

    db.add(user_model)
    db.commit()
    db.refresh(user_model)

    return user_model


@router.put("/admin/{user_id}/unsuspend", status_code=status.HTTP_200_OK)
async def unsuspend_account(
    user_id: UUID,
    db: db_dependency,
    user: user_dependency,
):
    require_db_permission(user, db, "STOP_ACCOUNT")

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
    user_model.approved_at = datetime.now(timezone.utc)

    db.add(user_model)
    db.commit()
    db.refresh(user_model)

    return user_model


# ----------------------------------------
# Search & Public Profile Endpoints
# ----------------------------------------


# GET /user/search?q=...
# --- Cache Key Builder ---
def viewer_aware_key_builder(
    func,
    namespace: str = "",
    request: Request = None,
    response: Response = None,
    *args,
    **kwargs,
):
    """
    Builds a cache key that explicitly factors in the unique identity of the viewer
    (the current user making the request) to ensure that private relational data
    like Friendship Status and Blocks do not leak across users.
    """
    # Try to extract the user from kwargs (dependency injection in FastAPI)
    current_user = kwargs.get("current_user", {})
    viewer_id = current_user.get("id", "anonymous")
    
    # Extract query params & path params
    path_str = request.url.path if request else ""
    query_str = getattr(request.url, "query", "") if request else ""
    
    raw_key = f"{namespace}:{func.__module__}:{func.__name__}:{path_str}:{query_str}:viewer={viewer_id}"
    return hashlib.md5(raw_key.encode()).hexdigest()


@router.get("/search", status_code=status.HTTP_200_OK)
@cache(expire=120, key_builder=viewer_aware_key_builder)
async def search_users(
    db: db_dependency,
    current_user: user_dependency,
    q: str = Query("", min_length=1, max_length=100),
):
    require_authenticated(current_user)
    current_uid = UUID(current_user["id"])

    # Get IDs of users blocked by current user or blocking current user
    from models import Block
    blocked_by_me = db.query(Block.blocked_id).filter(Block.blocker_id == current_uid)
    blocked_me = db.query(Block.blocker_id).filter(Block.blocked_id == current_uid)
    blocked_user_ids = [row[0] for row in blocked_by_me.all()] + [row[0] for row in blocked_me.all()]

    # Escape SQL wildcard characters
    safe_q = q.replace('%', '\\%').replace('_', '\\_')

    results = (
        db.query(Users, Profile)
        .outerjoin(Profile, Users.id == Profile.user_id)
        .filter(
            Users.is_active == True,
            Users.approval_status == "approved",
            Users.id.notin_(blocked_user_ids), # Exclude blocked users
            Users.id != current_uid, # Exclude self from search
        )
        .filter(
            (Users.username.ilike(f"%{safe_q}%", escape='\\'))
            | (Users.email.ilike(f"%{safe_q}%", escape='\\'))
            | (Profile.display_name.ilike(f"%{safe_q}%", escape='\\'))
        )
        .limit(20)
        .all()
    )

    return [
        {
            "id": str(user.id),
            "username": user.username,
            "display_name": profile.display_name if profile else None,
            "avatar_url": profile.avatar_url if profile else None,
            "bio": profile.bio if profile else None,
        }
        for user, profile in results
    ]

# GET /user/{user_id_or_username}/public
@router.get("/{user_id_or_username}/public", status_code=status.HTTP_200_OK)
@cache(expire=60, key_builder=viewer_aware_key_builder)
async def get_user_public_profile(
    user_id_or_username: str = Path(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    require_authenticated(current_user)

    # Try to parse as UUID
    try:
        user_uuid = UUID(user_id_or_username)
        user = db.query(Users).filter(Users.id == user_uuid).first()
    except ValueError:
        # Not a UUID, try username
        user = db.query(Users).filter(Users.username == user_id_or_username).first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    resolved_user_id = user.id
    current_uid = UUID(current_user["id"])

    # --- Block Check ---
    from models import Block
    block_exists = db.query(Block).filter(
        (
            (Block.blocker_id == current_uid) & (Block.blocked_id == resolved_user_id)
        ) | (
            (Block.blocker_id == resolved_user_id) & (Block.blocked_id == current_uid)
        )
    ).first()

    is_blocked_by_me = False
    if block_exists:
        if block_exists.blocker_id == current_uid:
            is_blocked_by_me = True
        else:
            raise HTTPException(status_code=404, detail="User not found")
            
    # If blocked by me, we still show a basic profile so I can "Unblock", but hide details
    if is_blocked_by_me:
        profile = db.query(Profile).filter(
            Profile.user_id == resolved_user_id,
            Profile.is_deleted == False,
        ).first()
        return {
            "id": str(user.id),
            "username": user.username,
            "email": user.email,
            "created_at": str(user.created_at),
            "profile": {
                "display_name": profile.display_name if profile else None,
                "avatar_url": getattr(profile, 'avatar_url', None) if profile else None,
            },
            "posts_count": 0,
            "friends_count": 0,
            "friendship_status": None,
            "friendship_id": None,
            "is_request_sender": None,
            "is_blocked_by_me": True,
        }

    profile = db.query(Profile).filter(
        Profile.user_id == resolved_user_id,
        Profile.is_deleted == False,
    ).first()

    # Count posts
    posts_count = db.query(Post).filter(
        Post.author_id == resolved_user_id,
        Post.is_deleted == False,
    ).count()

    # Count friends (accepted)
    friends_count = db.query(Friendship).filter(
        Friendship.status == "accepted",
        (
            (Friendship.requester_id == resolved_user_id)
            | (Friendship.addressee_id == resolved_user_id)
        ),
    ).count()

    # Check friendship with current user
    current_uid = UUID(current_user["id"])
    friendship = db.query(Friendship).filter(
        (
            (Friendship.requester_id == current_uid)
            & (Friendship.addressee_id == resolved_user_id)
        )
        | (
            (Friendship.requester_id == resolved_user_id)
            & (Friendship.addressee_id == current_uid)
        )
    ).first()

    friendship_status = None
    friendship_id = None
    is_request_sender = None
    if friendship:
        friendship_status = friendship.status
        friendship_id = str(friendship.friend_id)
        is_request_sender = str(friendship.requester_id) == str(current_uid)

    return {
        "id": str(user.id),
        "username": user.username,
        "email": user.email,
        "created_at": str(user.created_at),
        "profile": {
            "display_name": profile.display_name if profile else None,
            "bio": profile.bio if profile else None,
            "avatar_url": profile.avatar_url if profile else None,
            "cover_url": profile.cover_url if profile else None,
            "location": profile.location if profile else None,
            "website": profile.website if profile else None,
            "gender": profile.gender if profile else None,
            "birthday": str(profile.birthday) if profile and profile.birthday else None,
            "phone": profile.phone if profile else None,
            "language": profile.language if profile else None,
        } if profile else None,
        "posts_count": posts_count,
        "friends_count": friends_count,
        "friendship_status": friendship_status,
        "friendship_id": friendship_id,
        "is_request_sender": is_request_sender,
    }


# GET /user/admin/list
@router.get("/admin/list", status_code=status.HTTP_200_OK)
async def admin_list_users(
    db: db_dependency,
    current_user: user_dependency,
    approval_status: str = Query(None),
    q: str = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100)
):
    require_role(current_user, "admin", "registrar")

    query = db.query(Users, Profile).outerjoin(Profile, Users.id == Profile.user_id)

    if approval_status:
        query = query.filter(Users.approval_status == approval_status)

    if q:
        safe_q = q.replace('%', '\\%').replace('_', '\\_')
        query = query.filter(
            (Users.username.ilike(f"%{safe_q}%", escape='\\'))
            | (Users.email.ilike(f"%{safe_q}%", escape='\\'))
            | (Profile.display_name.ilike(f"%{safe_q}%", escape='\\'))
        )

    users_profiles = query.order_by(Users.created_at.desc()).offset(skip).limit(limit).all()

    results = []
    for u, profile in users_profiles:
        results.append({
            "id": str(u.id),
            "username": u.username,
            "email": u.email,
            "is_active": u.is_active,
            "is_suspended": u.is_suspended,
            "approval_status": u.approval_status,
            "created_at": str(u.created_at),
            "display_name": profile.display_name if profile else None,
            "avatar_url": profile.avatar_url if profile else None,
        })

    return results
