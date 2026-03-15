from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from models import Users, Permission, RolePermission

def require_authenticated(user: dict | None):
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication Failed"
        )


def require_role(user: dict | None, *allowed_roles: str):
    """
    مثال:
    require_role(user, "admin")
    require_role(user, "admin", "registrar")
    """
    require_authenticated(user)

    role_code = user.get("role_code")
    if role_code not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )


def is_admin(user: dict | None) -> bool:
    return user is not None and user.get("role_code") == "admin"

def require_db_permission(user: dict | None, db: Session, permission_code: str):
    """
     يتحقق من قاعدة البيانات مباشرة إذا كان المستخدم يملك الصلاحية.
    يعطي صلاحية كاملة دائماً للأدمن (admin) لتجنب انقطاع الخدمة عنه.
    """
    require_authenticated(user)
    role_code = user.get("role_code")
    
    # 1. الأدمن لديه كل الصلاحيات دائماً (حسب طلبك: "ابقي ال pending ايضا من صلاحيات ال admin")
    if role_code == "admin":
        return True
        
    # 2. جلب الـ role_id من المستخدم الحالي
    user_model = db.query(Users).filter(Users.id == user.get("id")).first()
    if not user_model:
        raise HTTPException(status_code=401, detail="المستخدم غير موجود")
        
    # 3. التحقق من ربط منصب المستخدم بالصلاحية المطلوبة
    has_perm = (
        db.query(Permission)
        .join(RolePermission, RolePermission.permission_id == Permission.per_id)
        .filter(RolePermission.role_id == user_model.role_id)
        .filter(Permission.code == permission_code)
        .first()
    )
    
    if not has_perm:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing required permission: {permission_code}"
        )

