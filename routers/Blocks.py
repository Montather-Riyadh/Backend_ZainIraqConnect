from typing import Annotated, List
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException, Path
from starlette import status
from database import get_db
from .auth import get_current_user
from models import Block, Users
from datetime import datetime


router = APIRouter()



db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]


# --------------- Helpers -----------------

def _ensure_auth(user: dict | None):
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")


# --------------- Routes -----------------


# GET /blocks -> المستخدمين اللي هذا اليوزر حاجبهم
@router.get("/", status_code=status.HTTP_200_OK)
async def list_blocks(user: user_dependency, db: db_dependency):
    _ensure_auth(user)
    user_id = user.get("id")

    blocks: List[Block] = (
        db.query(Block)
        .filter(Block.blocker_id == user_id)
        .all()
    )

    return blocks


# POST /blocks/{target_user_id} -> حظر مستخدم
@router.post("/{target_user_id}", status_code=status.HTTP_201_CREATED)
async def block_user(
    user: user_dependency,
    db: db_dependency,
    target_user_id: str = Path(...)
):
    _ensure_auth(user)
    user_id = user.get("id")

    if user_id == target_user_id:
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

    block = Block(
        blocker_id=user_id,
        blocked_id=target_user_id,
        created_at=datetime.utcnow(),
    )

    db.add(block)
    db.commit()
    db.refresh(block)

    return block


# DELETE /blocks/{target_user_id} -> إلغاء الحظر
@router.delete("/{target_user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unblock_user(
    user: user_dependency,
    db: db_dependency,
    target_user_id: str = Path(...)
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
