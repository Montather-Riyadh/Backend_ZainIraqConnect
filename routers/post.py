from typing import Annotated, Optional, List, Set
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from fastapi import APIRouter, Depends, HTTPException, Path
from starlette import status
from models import Post, Friendship
from database import get_db
from .auth import get_current_user
from datetime import datetime
from core.permissions import require_authenticated, is_admin
from uuid import UUID

router = APIRouter()

db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]


class PostRequest(BaseModel):
    title: Optional[str] = Field(default=None)
    content: Optional[str] = Field(default=None)
    tags: Optional[List[str]] = Field(default=None)
    visibility: Optional[str] = Field(default="public") 



from core.access_control import get_friend_ids, can_view_post




# 1) بوستات المستخدم أو كل البوستات لِلأدمن 
@router.get("/", status_code=status.HTTP_200_OK)
async def read_all_posts(user: user_dependency, db: db_dependency):
    require_authenticated(user)

    if is_admin(user):
        return (
            db.query(Post)
            .filter(Post.is_deleted == False)
            .order_by(Post.created_at.desc())
            .all()
        )

    return (
        db.query(Post)
        .filter(Post.author_id == user.get("id"))
        .filter(Post.is_deleted == False)
        .order_by(Post.created_at.desc())
        .all()
    )


#  قراءة بوست واحد مع احترام visibility + friends
@router.get("/post/{post_id}", status_code=status.HTTP_200_OK)
async def read_post(
    user: user_dependency,
    db: db_dependency,
    post_id: UUID = Path(...),
):
    require_authenticated(user)

    # أولاً نجيب البوست (غير المحذوف)
    post = (
        db.query(Post)
        .filter(Post.post_id == post_id)
        .filter(Post.is_deleted == False)
        .first()
    )

    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")

    # نتحقق من السماح بالمشاهدة
    if not can_view_post(db, user, post):
        raise HTTPException(
            status_code=403,
            detail="Not allowed to view this post",
        )

    return post


#  إنشاء بوست
@router.post("/post", status_code=status.HTTP_201_CREATED)
async def create_post(
    user: user_dependency,
    db: db_dependency,
    post_request: PostRequest,
):
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    post = Post(
        author_id=user.get("id"),
        title=post_request.title,
        content=post_request.content,
        tags=post_request.tags,
        visibility=post_request.visibility,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        is_deleted=False,
    )

    db.add(post)
    db.commit()
    db.refresh(post)

    return post


#  تعديل بوست (صاحب البوست)
@router.put("/post/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def update_post(
    user: user_dependency,
    db: db_dependency,
    post_request: PostRequest,
    post_id: UUID = Path(...),
):
    require_authenticated(user)

    query = db.query(Post).filter(Post.post_id == post_id)

    if not is_admin(user):
        query = query.filter(Post.author_id == user.get("id"))

    post = query.first()
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")

    update_data = post_request.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(post, key, value)

    post.updated_at = datetime.utcnow()

    db.add(post)
    db.commit()


# 5) حذف (soft delete) بوست
@router.delete("/post/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post(
    user: user_dependency,
    db: db_dependency,
    post_id: UUID = Path(...),
):
    require_authenticated(user)

    query = db.query(Post).filter(Post.post_id == post_id)
    if not is_admin(user):
        query = query.filter(Post.author_id == user.get("id"))

    post = query.first()
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")

    post.is_deleted = True
    post.updated_at = datetime.utcnow()
    db.add(post)
    db.commit()


# 6) الـ FEED – الـ Timeline حسب visibility + friends
@router.get("/feed", status_code=status.HTTP_200_OK)
async def get_feed(
    user: user_dependency,
    db: db_dependency,
):
    """
    يرجّع البوستات التي يحق للمستخدم الحالي أن يراها:
      - بوستاته هو نفسه
      - البوستات العامة (public) لأي مستخدم
      - البوستات الخاصة (private) للأصدقاء فقط
      - الـ admin يشوف كل شيء (غير محذوف).
    """
    require_authenticated(user)

    # الأدمن: يشوف كل البوستات (غير المحذوفة)
    if is_admin(user):
        posts = (
            db.query(Post)
            .filter(Post.is_deleted == False)
            .order_by(Post.created_at.desc())
            .all()
        )
        return posts

    user_id = UUID(str(user["id"]))

    # IDs للأصدقاء
    friend_ids = get_friend_ids(db, user_id)

    # بوستات يحق للمستخدم رؤيتها
    posts = (
        db.query(Post)
        .filter(Post.is_deleted == False)
        .filter(
            or_(
                # بوستات المستخدم نفسه
                Post.author_id == user_id,
                # بوستات public
                Post.visibility == "public",
                # بوستات private للأصدقاء فقط
                and_(
                    Post.visibility == "private",
                    Post.author_id.in_(friend_ids) if friend_ids else False,
                ),
            )
        )
        .order_by(Post.created_at.desc())
        .all()
    )

    return posts
