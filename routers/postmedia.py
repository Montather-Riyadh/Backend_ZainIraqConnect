from typing import Annotated, Optional, Dict
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException, Path
from starlette import status
from models import Post, PostMedia, Friendship
from database import get_db
from .auth import get_current_user
from datetime import datetime, timezone
from core.permissions import is_admin 
from uuid import UUID

router = APIRouter()



db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]



class MediaRequest(BaseModel):
    file_url: str = Field(min_length=5)
    media_type: str = Field(pattern="^(image|video|audio|file)$")
    metadata: Optional[Dict] = None



def _can_view_post_media(db: Session, user: dict, post: Post) -> bool:
    """
    يحدد إذا كان هذا اليوزر مسموح له يشوف ميديا هذا البوست
    حسب:
      - كونه أدمن
      - أو صاحب البوست
      - أو visibility (public / private + أصدقاء)
    """

    user_id = user.get("id")

    if is_admin(user):
        return True

    #  صاحب البوست يشوف دائمًا
    if str(post.author_id) == str(user_id):
        return True

    #  بوست محذوف؟ لا نسمح
    if getattr(post, "is_deleted", False):
        return False

    visibility = getattr(post, "visibility", "public")

    #  بوست عام -> كل المستخدمين المسجلين
    if visibility == "public":
        return True

    #  بوست خاص -> فقط الأصدقاء (status = accepted)
    if visibility in ("private", "friends"):
        friendship = (
            db.query(Friendship)
            .filter(Friendship.status == "accepted")
            .filter(
                (
                    (Friendship.requester_id == user_id)
                    & (Friendship.addressee_id == post.author_id)
                )
                | (
                    (Friendship.requester_id == post.author_id)
                    & (Friendship.addressee_id == user_id)
                )
            )
            .first()
        )
        if friendship:
            return True

    # أي حالة أخرى -> غير مسموح
    return False


# 1) Get all media for a post
@router.get("/mediapost/{post_id}", status_code=status.HTTP_200_OK)
async def get_post_media(
    user: user_dependency,
    db: db_dependency,
    post_id: UUID = Path(...)
):
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    # التأكد أن البوست يعود لهذا المستخدم
    post = (
        db.query(Post)
        .filter(Post.post_id == post_id)
        .filter(Post.is_deleted == False)
        .first()
    )

    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    # نتحقق من السماح
    if not _can_view_post_media(db, user, post):
        raise HTTPException(status_code=403, detail="Not allowed to view media for this post")

    media = db.query(PostMedia).filter(PostMedia.post_id == post_id).all()
    return media


# 2) Get single media
@router.get("/mediapost/{media_id}", status_code=status.HTTP_200_OK)
async def get_media(
    user: user_dependency,
    db: db_dependency,
    media_id: UUID = Path(...)
):
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    media = db.query(PostMedia).filter(PostMedia.post_media_id == media_id).first()
    if media is None:
        raise HTTPException(status_code=404, detail="Media not found")

    # نجيب البوست المرتبط بهذه الميديا
    post = db.query(Post).filter(Post.post_id == media.post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found for this media")

    # نتحقق من السماح
    if not _can_view_post_media(db, user, post):
        raise HTTPException(status_code=403, detail="Not allowed to view this media")

    return media


# 3) Create media for a post
@router.post("/mediapost/{post_id}", status_code=status.HTTP_201_CREATED)
async def create_post_media(
    user: user_dependency,
    db: db_dependency,
    media_request: MediaRequest,
    post_id: UUID = Path(...),
):
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    # Ensure the post exists and belongs to the user
    post = (
        db.query(Post)
        .filter(Post.post_id == post_id)
        .filter(Post.author_id == user.get("id"))
        .first()
    )

    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    media = PostMedia(
        post_id=post_id,
        file_url=media_request.file_url,
        media_type=media_request.media_type,
        meta_data=media_request.metadata,
        uploaded_at=datetime.now(timezone.utc)
    )

    db.add(media)
    db.commit()
    db.refresh(media)

    return media


# 4) Update media
@router.put("/mediapost/{media_id}", status_code=status.HTTP_204_NO_CONTENT)
async def update_media(
    user: user_dependency,
    db: db_dependency,
    media_request: MediaRequest,
    media_id: UUID = Path(...)
):
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    media = db.query(PostMedia).filter(PostMedia.post_media_id == media_id).first()

    if media is None:
        raise HTTPException(status_code=404, detail="Media not found")

    # Check ownership
    post = (
        db.query(Post)
        .filter(Post.post_id == media.post_id)
        .filter(Post.author_id == user.get("id"))
        .first()
    )

    if not post:
        raise HTTPException(status_code=403, detail="Not allowed")

    update_data = media_request.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(media, key, value)

    db.add(media)
    db.commit()


# 5) Delete media
@router.delete("/mediapost/{media_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_media(
    user: user_dependency,
    db: db_dependency,
    media_id: UUID = Path(...)
):
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    media = db.query(PostMedia).filter(PostMedia.post_media_id == media_id).first()

    if media is None:
        raise HTTPException(status_code=404, detail="Media not found")

    post = (
        db.query(Post)
        .filter(Post.post_id == media.post_id)
        .filter(Post.author_id == user.get("id"))
        .first()
    )

    if not post:
        raise HTTPException(status_code=403, detail="Not allowed")

    db.delete(media)
    db.commit()
