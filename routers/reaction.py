from typing import Annotated
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from starlette import status
from database import get_db
from .auth import get_current_user
from models import reaction as Reaction, Post, Comment
from datetime import datetime, timezone
from core.access_control import can_view_post
from uuid import UUID


router = APIRouter()


db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]


# ---------------- Helpers -----------------


def _ensure_auth(user: dict | None):
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")




@router.get("/", status_code=status.HTTP_200_OK)
async def read_all_Reaction(user: user_dependency, db: db_dependency):
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    return (
        db.query(Reaction)
        .filter(Reaction.user_id == UUID(str(user.get("id"))))
        .all()
    )


# ---------------- Routes: Likes on Posts -----------------


@router.get("/post/{post_id}", status_code=status.HTTP_200_OK)
async def get_post_Reaction(
    user: user_dependency, 
    db: db_dependency, 
    post_id: UUID = Path(...),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100)
):
    _ensure_auth(user)

    # نتأكد أن البوست موجود
    post = db.query(Post).filter(Post.post_id == post_id).first()
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")

    if not can_view_post(db, user, post):
        raise HTTPException(status_code=403, detail="Not allowed to view this post")

    reactions = db.query(Reaction).filter(Reaction.post_id == post_id).offset(skip).limit(limit).all()
    return reactions

@router.post("/post/{post_id}", status_code=status.HTTP_201_CREATED)
async def Reaction_post(user: user_dependency, db: db_dependency, post_id: UUID = Path(...)):
    _ensure_auth(user)
    user_id = UUID(str(user.get("id")))

    # نتأكد أن البوست موجود
    post = db.query(Post).filter(Post.post_id == post_id).first()
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")

    # Check if post is deleted
    if post.is_deleted:
        raise HTTPException(status_code=404, detail="Post has been deleted")

    if not can_view_post(db, user, post):
        raise HTTPException(status_code=403, detail="Not allowed to react to this post")

    # هل هذا المستخدم عامل لايك مسبقاً؟
    existing = (
        db.query(Reaction)
        .filter(Reaction.user_id == user_id)
        .filter(Reaction.post_id == post_id)
        .filter(Reaction.comment_id == None)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Already reactioned")

    try:
        reaction = Reaction(
            user_id=user_id,
            post_id=post_id,
            comment_id=None,
            created_at=datetime.now(timezone.utc),
        )

        db.add(reaction)
        db.commit()
        db.refresh(reaction)

        return reaction
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.delete("/post/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unlike_post(user: user_dependency, db: db_dependency, post_id: UUID = Path(...)):
    _ensure_auth(user)
    user_id = UUID(str(user.get("id")))

    reaction = (
        db.query(Reaction)
        .filter(Reaction.user_id == user_id)
        .filter(Reaction.post_id == post_id)
        .filter(Reaction.comment_id == None)
        .first()
    )

    if reaction is None:
        raise HTTPException(status_code=404, detail="reaction not found")

    db.delete(reaction)
    db.commit()


# ---------------- Routes: Likes on Comments -----------------


@router.get("/comment/{comment_id}", status_code=status.HTTP_200_OK)
async def get_comment_Reactions(
    user: user_dependency,
    db: db_dependency,
    comment_id: UUID = Path(...)
):
    _ensure_auth(user)

    # نتأكد أن الكومنت موجود
    comment = (
        db.query(Comment)
        .filter(Comment.comment_id == comment_id)
        .first()
    )
    if comment is None:
        raise HTTPException(status_code=404, detail="Comment not found")

    reactions = db.query(Reaction).filter(Reaction.comment_id == comment_id).all()
    return reactions


@router.post("/comment/{comment_id}", status_code=status.HTTP_201_CREATED)
async def like_comment(user: user_dependency, db: db_dependency, comment_id: UUID = Path(...)):
    _ensure_auth(user)
    user_id = UUID(str(user.get("id")))

    # نتأكد أن الكومنت موجود
    comment = (
        db.query(Comment)
        .filter(Comment.comment_id == comment_id)
        .first()
    )
    if comment is None:
        raise HTTPException(status_code=404, detail="Comment not found")

    # Check if comment is deleted
    if comment.is_deleted:
        raise HTTPException(status_code=404, detail="Comment has been deleted")

    # Check post visibility
    post = db.query(Post).filter(Post.post_id == comment.post_id).first()
    if post and not can_view_post(db, user, post):
         raise HTTPException(status_code=403, detail="Not allowed to view the post of this comment")

    existing = (
        db.query(Reaction)
        .filter(Reaction.user_id == user_id)
        .filter(Reaction.comment_id == comment_id)
        .filter(Reaction.post_id == None)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Already reactioned")

    try:
        reaction = Reaction(
            user_id=user_id,
            post_id=None,
            comment_id=comment_id,
            created_at=datetime.now(timezone.utc),
        )

        db.add(reaction)
        db.commit()
        db.refresh(reaction)

        return reaction
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.delete("/comment/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unReaction_comment(
    user: user_dependency,
    db: db_dependency,
    comment_id: UUID = Path(...)
):
    _ensure_auth(user)
    user_id = UUID(str(user.get("id")))

    reaction = (
        db.query(Reaction)
        .filter(Reaction.user_id == user_id)
        .filter(Reaction.comment_id == comment_id)
        .filter(Reaction.post_id == None)
        .first()
    )

    if reaction is None:
        raise HTTPException(status_code=404, detail="reaction not found")

    db.delete(reaction)
    db.commit()

