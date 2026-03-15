from typing import Annotated
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from starlette import status
from database import get_db
from .auth import get_current_user
from models import Friendship, Users, Block, Profile
from datetime import datetime, timezone
from uuid import UUID


router = APIRouter()



db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]


# --------------- Schemas -----------------

class FriendshipStatusRequest(BaseModel):
    # friend_status_enum: pending / accepted / declined 
    status: str = Field(pattern="^(pending|accepted|declined)$")


# --------------- Helpers -----------------

def _ensure_auth(user: dict | None):
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")


def _get_friendship_for_user(db: Session, friend_id: UUID, user_id: UUID) -> Friendship:
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

def _serialize_friendship(friendship: Friendship, current_user_id: UUID, db: Session, other_user=None, other_profile=None) -> dict:
    """Convert a Friendship ORM object to a dict with joined friend info."""
    data = {
        "friend_id": str(friendship.friend_id),
        "requester_id": str(friendship.requester_id),
        "addressee_id": str(friendship.addressee_id),
        "status": friendship.status,
        "created_at": str(friendship.created_at),
        "responded_at": str(friendship.responded_at) if friendship.responded_at else None,
    }
    
    # Identify the 'other' user
    other_user_id = friendship.addressee_id if str(friendship.requester_id) == str(current_user_id) else friendship.requester_id
    
    # Fetch other user details if not provided
    if other_user is None:
        other_user = db.query(Users).filter(Users.id == other_user_id).first()
    if other_profile is None:
        other_profile = db.query(Profile).filter(
            Profile.user_id == other_user_id,
            Profile.is_deleted == False
        ).first()
    
    data["friend_username"] = other_user.username if other_user else None
    data["friend_display_name"] = other_profile.display_name if other_profile else None
    data["friend_avatar"] = other_profile.avatar_url if other_profile else None
    
    return data


# --------------- Routes -----------------


# GET /friendships -> كل العلاقات (طلبات + أصدقاء) الخاصة باليوزر
@router.get("/", status_code=status.HTTP_200_OK)
async def list_friendships(
    user: user_dependency, 
    db: db_dependency,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100)
):
    _ensure_auth(user)
    user_id = user.get("id")

    friendships = (
        db.query(Friendship)
        .filter(
            (Friendship.requester_id == user_id)
            | (Friendship.addressee_id == user_id)
        )
        .offset(skip)
        .limit(limit)
        .all()
    )

    if not friendships:
        return []

    # Bulk fetch to avoid N+1 queries
    other_user_ids = [
        f.addressee_id if str(f.requester_id) == str(user_id) else f.requester_id 
        for f in friendships
    ]

    other_users = db.query(Users).filter(Users.id.in_(other_user_ids)).all()
    other_profiles = db.query(Profile).filter(Profile.user_id.in_(other_user_ids), Profile.is_deleted == False).all()

    user_dict = {u.id: u for u in other_users}
    profile_dict = {p.user_id: p for p in other_profiles}

    results = []
    for f in friendships:
        o_id = f.addressee_id if str(f.requester_id) == str(user_id) else f.requester_id
        results.append(_serialize_friendship(
            f, 
            user_id, 
            db, 
            other_user=user_dict.get(o_id), 
            other_profile=profile_dict.get(o_id)
        ))

    return results


# GET /friendships/{friend_id} -> علاقة واحدة
@router.get("/{friend_id}", status_code=status.HTTP_200_OK)
async def get_friendship(
    user: user_dependency,
    db: db_dependency,
    friend_id: UUID = Path(...)
):
    _ensure_auth(user)
    user_id = user.get("id")

    friendship = _get_friendship_for_user(db, friend_id, user_id)
    return _serialize_friendship(friendship, user_id, db)


# POST /friendships/request/{target_user_id} -> إرسال طلب صداقة
@router.post("/request/{target_user_id}", status_code=status.HTTP_201_CREATED)
async def send_friend_request(
    user: user_dependency,
    db: db_dependency,
    target_user_id: UUID = Path(...)
):
    _ensure_auth(user)
    user_id = user.get("id")

    if str(user_id) == str(target_user_id):
        raise HTTPException(status_code=400, detail="Cannot send friend request to yourself")

    # هل المستخدم الهدف موجود؟
    target = db.query(Users).filter(Users.id == target_user_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail="Target user not found")

    # هل يوجد حظر بين المستخدمين؟
    block_exists = (
        db.query(Block)
        .filter(
            (
                (Block.blocker_id == user_id)
                & (Block.blocked_id == target_user_id)
            )
            | (
                (Block.blocker_id == target_user_id)
                & (Block.blocked_id == user_id)
            )
        )
        .first()
    )
    if block_exists:
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
        created_at=datetime.now(timezone.utc),
        responded_at=None,
    )

    db.add(friendship)
    db.commit()
    db.refresh(friendship)

    return _serialize_friendship(friendship, user_id, db)


# PUT /friendships/request/{friend_id} -> قبول / رفض / حظر
@router.put("/request/{friend_id}", status_code=status.HTTP_204_NO_CONTENT)
async def respond_to_request(
    user: user_dependency,
    db: db_dependency,
    data: FriendshipStatusRequest,
    friend_id: UUID = Path(...)
):
    _ensure_auth(user)
    user_id = user.get("id")

    friendship = db.query(Friendship).filter(Friendship.friend_id == friend_id).first()
    if friendship is None:
        raise HTTPException(status_code=404, detail="Friendship not found")

    # فقط المستقبل (addressee) يقدر يرد على الطلب
    if str(friendship.addressee_id) != str(user_id):
        raise HTTPException(status_code=403, detail="Not allowed to update this request")

    # تحديث الحالة + وقت الرد
    friendship.status = data.status
    friendship.responded_at = datetime.now(timezone.utc)

    db.add(friendship)
    db.commit()


# DELETE /friendships/{friend_id} -> إلغاء/حذف العلاقة (unfriend أو cancel)
@router.delete("/{friend_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_friendship(
    user: user_dependency,
    db: db_dependency,
    friend_id: UUID = Path(...)
):
    _ensure_auth(user)
    user_id = user.get("id")

    friendship = _get_friendship_for_user(db, friend_id, user_id)

    db.delete(friendship)
    db.commit()

