from typing import Annotated, List
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from starlette import status
from database import get_db
from .auth import get_current_user
from models import Block, Users, Profile
from datetime import datetime, timezone
from uuid import UUID


router = APIRouter()



db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]


# --------------- Helpers -----------------

def _ensure_auth(user: dict | None):
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

def _serialize_block(block: Block, db: Session, blocked_user=None, blocked_profile=None) -> dict:
    data = {
        "block_id": str(block.block_id),
        "blocker_id": str(block.blocker_id),
        "blocked_id": str(block.blocked_id),
        "created_at": str(block.created_at),
    }
    
    if blocked_user is None:
        blocked_user = db.query(Users).filter(Users.id == block.blocked_id).first()
    if blocked_profile is None:
        blocked_profile = db.query(Profile).filter(
            Profile.user_id == block.blocked_id,
            Profile.is_deleted == False
        ).first()
    
    data["blocked_username"] = blocked_user.username if blocked_user else None
    data["blocked_display_name"] = blocked_profile.display_name if blocked_profile else None
    data["blocked_avatar"] = blocked_profile.avatar_url if blocked_profile else None
    
    return data


# --------------- Routes -----------------


# GET /blocks -> المستخدمين اللي هذا اليوزر حاجبهم
@router.get("/", status_code=status.HTTP_200_OK)
async def list_blocks(
    user: user_dependency, 
    db: db_dependency,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100)
):
    _ensure_auth(user)
    user_id = user.get("id")

    blocks: List[Block] = (
        db.query(Block)
        .filter(Block.blocker_id == user_id)
        .offset(skip)
        .limit(limit)
        .all()
    )

    if not blocks:
        return []

    blocked_user_ids = [b.blocked_id for b in blocks]

    blocked_users = db.query(Users).filter(Users.id.in_(blocked_user_ids)).all()
    blocked_profiles = db.query(Profile).filter(Profile.user_id.in_(blocked_user_ids), Profile.is_deleted == False).all()

    user_dict = {u.id: u for u in blocked_users}
    profile_dict = {p.user_id: p for p in blocked_profiles}

    return [
        _serialize_block(
            b, 
            db, 
            blocked_user=user_dict.get(b.blocked_id), 
            blocked_profile=profile_dict.get(b.blocked_id)
        ) for b in blocks
    ]


# POST /blocks/{target_user_id} -> حظر مستخدم
@router.post("/{target_user_id}", status_code=status.HTTP_201_CREATED)
async def block_user(
    user: user_dependency,
    db: db_dependency,
    target_user_id: UUID = Path(...)
):
    _ensure_auth(user)
    user_id = user.get("id")

    if str(user_id) == str(target_user_id):
        raise HTTPException(status_code=400, detail="You cannot block yourself")

    # هل المستخدم الهدف موجود؟
    target = db.query(Users).filter(Users.id == target_user_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail="Target user not found")

    # هل هذا البلوك موجود مسبقاً؟
    existing = (
        db.query(Block)
        .filter(Block.blocker_id == user_id)
        .filter(Block.blocked_id == target_user_id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="User already blocked")

    # Delete any existing friendship or friend request in either direction
    from models import Friendship
    existing_friendship = db.query(Friendship).filter(
        (
            (Friendship.requester_id == user_id)
            & (Friendship.addressee_id == target_user_id)
        )
        | (
            (Friendship.requester_id == target_user_id)
            & (Friendship.addressee_id == user_id)
        )
    ).first()
    
    if existing_friendship:
        db.delete(existing_friendship)

    block = Block(
        blocker_id=user_id,
        blocked_id=target_user_id,
        created_at=datetime.now(timezone.utc),
    )

    db.add(block)
    db.commit()
    db.refresh(block)

    return _serialize_block(block, db)


# DELETE /blocks/{target_user_id} -> إلغاء الحظر
@router.delete("/{target_user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unblock_user(
    user: user_dependency,
    db: db_dependency,
    target_user_id: UUID = Path(...)
):
    _ensure_auth(user)
    user_id = user.get("id")

    block = (
        db.query(Block)
        .filter(Block.blocker_id == user_id)
        .filter(Block.blocked_id == target_user_id)
        .first()
    )

    if block is None:
        raise HTTPException(status_code=404, detail="Block not found")

    db.delete(block)
    db.commit()
