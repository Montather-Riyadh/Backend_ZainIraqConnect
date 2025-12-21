from typing import Annotated, Optional
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException, Path
from starlette import status
from models import Profile
from database import get_db
from .auth import get_current_user

router = APIRouter()


db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]


# ---------------- Request Schema ------------------

class ProfileRequest(BaseModel):
    display_name: Optional[str] = None
    gender: Optional[str] = None
    birthday: Optional[str] = None
    bio: Optional[str] = None
    website: Optional[str] = None
    phone: Optional[str] = None
    language: Optional[str] = None
    location: Optional[str] = None
    avatar_url: Optional[str] = None
    cover_url: Optional[str] = None


# ---------------- Routes ------------------

@router.get("/", status_code=status.HTTP_200_OK)
async def read_profile(user: user_dependency, db: db_dependency):
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    profile = db.query(Profile).filter(
        Profile.user_id == user.get("id"),
        Profile.is_deleted == False
        ).first()


    if profile:
        return profile

    raise HTTPException(status_code=404, detail="Profile not found")


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_profile(
    user: user_dependency,
    db: db_dependency,
    profile_request: ProfileRequest
):
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    # check if this user already has a profile
    existing = db.query(Profile).filter(Profile.user_id == user.get("id")).first()
    if existing:
        raise HTTPException(status_code=400, detail="Profile already exists")

    new_profile = Profile(
        user_id=user.get("id"),
        **profile_request.model_dump()
    )

    db.add(new_profile)
    db.commit()
    db.refresh(new_profile)

    return new_profile


@router.put("/", status_code=status.HTTP_204_NO_CONTENT)
async def update_profile(
    user: user_dependency,
    db: db_dependency,
    profile_request: ProfileRequest
):
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    profile = db.query(Profile).filter(Profile.user_id == user.get("id")).first()

    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")

    # update fields
    update_data = profile_request.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(profile, key, value)

    db.add(profile)
    db.commit()


@router.delete("/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile(user: user_dependency, db: db_dependency):
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    profile = db.query(Profile).filter(Profile.user_id == user.get("id")).first()

    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")

    db.delete(profile)
    db.commit()
