from typing import Annotated
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException, Path
from starlette import status
from database import get_db
from .auth import get_current_user
from models import Friendship, Users
from datetime import datetime


router = APIRouter()





db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]


# --------------- Schemas -----------------

class FriendshipStatusRequest(BaseModel):
    # friend_status_enum: pending / accepted / rejected / blocked
    status: str = Field(pattern="^(pending|accepted|rejected|blocked)$")


# --------------- Helpers -----------------

def _ensure_auth(user: dict | None):
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")


def _get_friendship_for_user(db: Session, friend_id: str, user_id: str) -> Friendship:
    friendship = (
        db.query(Friendship)
        .filter(Friendship.friend_id == friend_id)
        .filter(
            (Friendship.requester_id == user_id)
            | (Friendship.addressee_id == user_id)
        )
        .first()
    )
    if friendship is None:
        raise HTTPException(status_code=404, detail="Friendship not found")
    return friendship


# --------------- Routes -----------------


# GET /friendships -> كل العلاقات (طلبات + أصدقاء) الخاصة باليوزر
@router.get("/", status_code=status.HTTP_200_OK)
async def list_friendships(user: user_dependency, db: db_dependency):
    _ensure_auth(user)
    user_id = user.get("id")

    friendships = (
        db.query(Friendship)
        .filter(
            (Friendship.requester_id == user_id)
            | (Friendship.addressee_id == user_id)
        )
        .all()
    )
    return friendships


# GET /friendships/{friend_id} -> علاقة واحدة
@router.get("/{friend_id}", status_code=status.HTTP_200_OK)
async def get_friendship(
    user: user_dependency,
    db: db_dependency,
    friend_id: str = Path(...)
):
    _ensure_auth(user)
    user_id = user.get("id")

    friendship = _get_friendship_for_user(db, friend_id, user_id)
    return friendship


# POST /friendships/request/{target_user_id} -> إرسال طلب صداقة
@router.post("/request/{target_user_id}", status_code=status.HTTP_201_CREATED)
async def send_friend_request(
    user: user_dependency,
    db: db_dependency,
    target_user_id: str = Path(...)
):
    _ensure_auth(user)
    user_id = user.get("id")

    if user_id == target_user_id:
        raise HTTPException(status_code=400, detail="Cannot send friend request to yourself")

    # هل المستخدم الهدف موجود؟
    target = db.query(Users).filter(Users.id == target_user_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail="Target user not found")

    # هل توجد علاقة سابقة بينهما (بأي اتجاه)؟
    existing = (
        db.query(Friendship)
        .filter(
            (
                (Friendship.requester_id == user_id)
                & (Friendship.addressee_id == target_user_id)
            )
            | (
                (Friendship.requester_id == target_user_id)
                & (Friendship.addressee_id == user_id)
            )
        )
        .first()
    )

    if existing:
        raise HTTPException(status_code=400, detail="Friendship already exists or pending")

    friendship = Friendship(
        requester_id=user_id,
        addressee_id=target_user_id,
        status="pending",
        created_at=datetime.utcnow(),
        responded_at=None,
    )

    db.add(friendship)
    db.commit()
    db.refresh(friendship)

    return friendship


# PUT /friendships/request/{friend_id} -> قبول / رفض / حظر
@router.put("/request/{friend_id}", status_code=status.HTTP_204_NO_CONTENT)
async def respond_to_request(
    user: user_dependency,
    db: db_dependency,
    data: FriendshipStatusRequest,
    friend_id: str = Path(...)
):
    _ensure_auth(user)
    user_id = user.get("id")

    friendship = db.query(Friendship).filter(Friendship.friend_id == friend_id).first()
    if friendship is None:
        raise HTTPException(status_code=404, detail="Friendship not found")

    # فقط المستقبل (addressee) يقدر يرد على الطلب
    if friendship.addressee_id != user_id:
        raise HTTPException(status_code=403, detail="Not allowed to update this request")

    # تحديث الحالة + وقت الرد
    friendship.status = data.status
    friendship.responded_at = datetime.utcnow()

    db.add(friendship)
    db.commit()


# DELETE /friendships/{friend_id} -> إلغاء/حذف العلاقة (unfriend أو cancel)
@router.delete("/{friend_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_friendship(
    user: user_dependency,
    db: db_dependency,
    friend_id: str = Path(...)
):
    _ensure_auth(user)
    user_id = user.get("id")

    friendship = _get_friendship_for_user(db, friend_id, user_id)

    db.delete(friendship)
    db.commit()
