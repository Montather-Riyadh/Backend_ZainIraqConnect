from typing import Annotated, Optional, List, Set
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from starlette import status
from models import Post, Friendship, Users, Profile
from database import get_db
from .auth import get_current_user
from datetime import datetime, timezone
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



from core.access_control import get_friend_ids, can_view_post, get_blocked_user_ids
from models import Reaction, Comment as CommentModel, PostMedia


def _serialize_post(post: Post, db: Session, author: Users = None, profile: Profile = None, current_user_id: Optional[UUID] = None) -> dict:
    """Convert a Post ORM object to a dict with joined author info, counts, and media."""
    data = {
        "post_id": str(post.post_id),
        "author_id": str(post.author_id),
        "title": post.title,
        "content": post.content,
        "tags": post.tags,
        "visibility": post.visibility,
        "created_at": str(post.created_at),
        "updated_at": str(post.updated_at),
        "is_deleted": post.is_deleted,
    }
    
    if author is None:
        author = db.query(Users).filter(Users.id == post.author_id).first()
    if profile is None:
        profile = db.query(Profile).filter(
            Profile.user_id == post.author_id,
            Profile.is_deleted == False,
        ).first()
        
    data["author_username"] = author.username if author else None
    data["author_display_name"] = profile.display_name if profile else None
    data["author_avatar"] = profile.avatar_url if profile else None

    # ✅ FE-01: Include counts and media inline to avoid N+1 API calls
    data["reaction_count"] = (
        db.query(Reaction)
        .filter(Reaction.post_id == post.post_id)
        .count()
    )
    data["comment_count"] = (
        db.query(CommentModel)
        .filter(CommentModel.post_id == post.post_id, CommentModel.is_deleted == False)
        .count()
    )

    # Check if current user has liked this post
    data["user_has_liked"] = False
    if current_user_id:
        data["user_has_liked"] = (
            db.query(Reaction)
            .filter(Reaction.post_id == post.post_id, Reaction.user_id == current_user_id)
            .first() is not None
        )

    # Include media items
    media_items = db.query(PostMedia).filter(PostMedia.post_id == post.post_id).all()
    data["media"] = [
        {
            "media_id": str(m.post_media_id),
            "file_url": m.file_url,
            "media_type": m.media_type,
        }
        for m in media_items
    ]

    return data




# 1) بوستات المستخدم أو كل البوستات لِلأدمن 
@router.get("/", status_code=status.HTTP_200_OK)
async def read_all_posts(
    user: user_dependency, 
    db: db_dependency,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100)
):
    require_authenticated(user)

    if is_admin(user):
        posts = (
            db.query(Post)
            .filter(Post.is_deleted == False)
            .order_by(Post.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
    else:
        posts = (
            db.query(Post)
            .filter(Post.author_id == user.get("id"))
            .filter(Post.is_deleted == False)
            .order_by(Post.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    if not posts:
        return []

    # Bulk fetch authors and profiles
    author_ids = [p.author_id for p in posts]
    authors = db.query(Users).filter(Users.id.in_(author_ids)).all()
    profiles = db.query(Profile).filter(Profile.user_id.in_(author_ids), Profile.is_deleted == False).all()

    author_dict = {u.id: u for u in authors}
    profile_dict = {p.user_id: p for p in profiles}

    current_uid = UUID(str(user.get("id")))

    return [
        _serialize_post(
            p, 
            db, 
            author=author_dict.get(p.author_id), 
            profile=profile_dict.get(p.author_id),
            current_user_id=current_uid,
        ) for p in posts
    ]


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

    return _serialize_post(post, db, current_user_id=UUID(str(user.get("id"))))


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
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        is_deleted=False,
    )

    db.add(post)
    db.commit()
    db.refresh(post)

    return _serialize_post(post, db, current_user_id=UUID(str(user.get("id"))))


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

    post.updated_at = datetime.now(timezone.utc)

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
    post.updated_at = datetime.now(timezone.utc)
    db.add(post)
    db.commit()


# 6) الـ FEED – الـ Timeline حسب Weighted Score Algorithm
@router.get("/feed", status_code=status.HTTP_200_OK)
async def get_feed(
    user: user_dependency,
    db: db_dependency,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100)
):
    """
    يرجّع البوستات مرتبة حسب خوارزمية Weighted Score:
      Score = (reactions×2 + comments×3 + 1) × relationship_bonus × time_decay
      - relationship_bonus: 1.5 أصدقاء | 1.2 بوستاتي | 1.0 غيرهم
      - time_decay: البوستات الأحدث لها أولوية
      - الـ admin يشوف كل شيء بالترتيب الزمني.
    """
    require_authenticated(user)

    # الأدمن: يشوف كل البوستات (غير المحذوفة) بالترتيب الزمني
    if is_admin(user):
        posts = (
            db.query(Post)
            .filter(Post.is_deleted == False)
            .order_by(Post.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
    else:
        user_id_str = user.get("id")
        if not user_id_str:
            raise HTTPException(status_code=401, detail="Authentication Failed")
        user_id = UUID(str(user_id_str))

        # IDs للأصدقاء والمحظورين
        friend_ids = get_friend_ids(db, user_id)
        blocked_ids = get_blocked_user_ids(db, user_id)

        # استخدام خوارزمية الترتيب الذكي
        from core.feed_algorithm import build_ranked_feed_query

        ranked_query = build_ranked_feed_query(
            db=db,
            user_id=user_id,
            friend_ids=friend_ids,
            blocked_ids=blocked_ids,
            skip=skip,
            limit=limit,
        )

        # النتيجة هي (Post, score) — نأخذ فقط الـ Post
        results = ranked_query.all()
        posts = [row[0] for row in results]

    if not posts:
        return []

    # Bulk fetch authors and profiles
    author_ids = [p.author_id for p in posts]
    authors = db.query(Users).filter(Users.id.in_(author_ids)).all()
    profiles = db.query(Profile).filter(Profile.user_id.in_(author_ids), Profile.is_deleted == False).all()

    author_dict = {u.id: u for u in authors}
    profile_dict = {p.user_id: p for p in profiles}

    current_uid = UUID(str(user.get("id")))

    return [
        _serialize_post(
            p, 
            db, 
            author=author_dict.get(p.author_id), 
            profile=profile_dict.get(p.author_id),
            current_user_id=current_uid,
        ) for p in posts
    ]
