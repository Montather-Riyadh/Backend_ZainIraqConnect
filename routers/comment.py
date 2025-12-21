from typing import Annotated, Optional
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException, Path
from starlette import status
from models import Comment, Post
from database import get_db
from .auth import get_current_user
from datetime import datetime
from core.access_control import can_view_post


router = APIRouter()



db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]



class CommentRequest(BaseModel):
    content: str = Field(min_length=1)
    parent_comment_id: Optional[str] = None




#  جلب كل التعليقات الخاصة بالبوست
@router.get("/post/{post_id}", status_code=status.HTTP_200_OK)
async def get_post_comments(user: user_dependency,db: db_dependency,post_id: str = Path(gt=0)):
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
        .all()
    )

    return comments


#  جلب تعليق واحد
@router.get("/comment/{comment_id}", status_code=status.HTTP_200_OK)
async def read_comment(user: user_dependency,db: db_dependency,comment_id: str = Path(gt=0)):
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
async def create_comment(user: user_dependency,db: db_dependency,
    post_id: str,
    comment_request: CommentRequest
):
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    # check post exists
    post = db.query(Post).filter(Post.post_id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    if not can_view_post(db, user, post):
        raise HTTPException(status_code=403, detail="Not allowed to comment on this post")

    new_comment = Comment(
        post_id=post_id,
        author_id=user.get("id"),
        content=comment_request.content,
        parent_comment_id=comment_request.parent_comment_id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        is_deleted=False
    )

    db.add(new_comment)
    db.commit()
    db.refresh(new_comment)

    return new_comment


#  حذف تعليق (soft delete)
@router.delete("/comment/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    user: user_dependency,
    db: db_dependency,
    comment_id: str = Path(...)
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
    comment.updated_at = datetime.utcnow()

    db.add(comment)
    db.commit()
