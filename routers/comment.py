from typing import Annotated, Optional
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from starlette import status
from models import Comment, Post, Users, Profile
from database import get_db
from .auth import get_current_user
from datetime import datetime, timezone
from core.access_control import can_view_post
from uuid import UUID


router = APIRouter()



db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]


def _serialize_comment(comment: Comment, db: Session, author: Users = None, profile: Profile = None) -> dict:
    """Convert a Comment ORM object to a dict with joined author info."""
    data = {
        "comment_id": str(comment.comment_id),
        "post_id": str(comment.post_id),
        "author_id": str(comment.author_id),
        "content": comment.content,
        "parent_comment_id": str(comment.parent_comment_id) if comment.parent_comment_id else None,
        "created_at": str(comment.created_at),
        "updated_at": str(comment.updated_at),
        "is_deleted": comment.is_deleted,
    }
    
    if author is None:
        author = db.query(Users).filter(Users.id == comment.author_id).first()
    if profile is None:
        profile = db.query(Profile).filter(
            Profile.user_id == comment.author_id,
            Profile.is_deleted == False,
        ).first()
        
    data["author_username"] = author.username if author else None
    data["author_display_name"] = profile.display_name if profile else None
    data["author_avatar"] = profile.avatar_url if profile else None
    return data



class CommentRequest(BaseModel):
    content: str = Field(min_length=1)
    parent_comment_id: Optional[str] = None




#  جلب كل التعليقات الخاصة بالبوست
@router.get("/post/{post_id}", status_code=status.HTTP_200_OK)
async def get_post_comments(
    user: user_dependency, 
    db: db_dependency, 
    post_id: UUID = Path(...),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100)
):
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    # First check if post exists and user can view it
    post = db.query(Post).filter(Post.post_id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    if not can_view_post(db, user, post):
        raise HTTPException(status_code=403, detail="Not allowed to view this post")

    comments = (
        db.query(Comment)
        .filter(Comment.post_id == post_id)
        .filter(Comment.is_deleted == False)
        .offset(skip)
        .limit(limit)
        .all()
    )

    if not comments:
        return []

    # Bulk fetch authors
    author_ids = [c.author_id for c in comments]
    authors = db.query(Users).filter(Users.id.in_(author_ids)).all()
    profiles = db.query(Profile).filter(Profile.user_id.in_(author_ids), Profile.is_deleted == False).all()

    author_dict = {u.id: u for u in authors}
    profile_dict = {p.user_id: p for p in profiles}

    return [
        _serialize_comment(
            c, 
            db, 
            author=author_dict.get(c.author_id), 
            profile=profile_dict.get(c.author_id)
        ) for c in comments
    ]


#  جلب تعليق واحد
@router.get("/comment/{comment_id}", status_code=status.HTTP_200_OK)
async def read_comment(user: user_dependency, db: db_dependency, comment_id: UUID = Path(...)):
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    comment = (
    db.query(Comment)
    .filter(Comment.comment_id == comment_id)
    .filter(Comment.is_deleted == False)
    .first()
)


    if comment:
        return comment

    raise HTTPException(status_code=404, detail="Comment not found")


#  إنشاء تعليق على بوست أو رد على تعليق
@router.post("/post/{post_id}", status_code=status.HTTP_201_CREATED)
async def create_comment(user: user_dependency, db: db_dependency,
    post_id: UUID = Path(...),
    comment_request: CommentRequest = Depends()
):
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    # check post exists
    post = db.query(Post).filter(Post.post_id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    # check post is not deleted
    if post.is_deleted:
        raise HTTPException(status_code=404, detail="Post has been deleted")

    if not can_view_post(db, user, post):
        raise HTTPException(status_code=403, detail="Not allowed to comment on this post")

    new_comment = Comment(
        post_id=post_id,
        author_id=user.get("id"),
        content=comment_request.content,
        parent_comment_id=comment_request.parent_comment_id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        is_deleted=False
    )

    db.add(new_comment)
    db.commit()
    db.refresh(new_comment)

    return _serialize_comment(new_comment, db)


#  حذف تعليق (soft delete)
@router.delete("/comment/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    user: user_dependency,
    db: db_dependency,
    comment_id: UUID = Path(...)
):
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    comment = (
        db.query(Comment)
        .filter(Comment.comment_id == comment_id)
        .filter(Comment.author_id == user.get("id"))
        .first()
    )

    if comment is None:
        raise HTTPException(status_code=404, detail="Comment not found")

    # soft delete
    comment.is_deleted = True
    comment.updated_at = datetime.now(timezone.utc)

    db.add(comment)
    db.commit()

