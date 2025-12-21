from fastapi import HTTPException, status

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

