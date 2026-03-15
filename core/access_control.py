from uuid import UUID
from typing import Set
from sqlalchemy.orm import Session
from sqlalchemy import or_
from models import Post, Friendship, Block
from core.permissions import is_admin


def get_friend_ids(db: Session, user_id: UUID) -> Set[UUID]:
    """
    يرجّع مجموعة IDs للأصدقاء (status = accepted) لهذا اليوزر.
    """
    friendships = (
        db.query(Friendship)
        .filter(Friendship.status == "accepted")
        .filter(
            or_(
                Friendship.requester_id == user_id,
                Friendship.addressee_id == user_id,
            )
        )
        .all()
    )

    friend_ids: Set[UUID] = set()
    for fr in friendships:
        if fr.requester_id == user_id:
            friend_ids.add(fr.addressee_id)
        else:
            friend_ids.add(fr.requester_id)

    return friend_ids


def get_blocked_user_ids(db: Session, user_id: UUID) -> Set[UUID]:
    """
    يرجّع مجموعة IDs للمستخدمين المحظورين (بأي اتجاه):
      - اللي هذا اليوزر حاجبهم
      - واللي حاجبين هذا اليوزر
    """
    blocks = (
        db.query(Block)
        .filter(
            or_(
                Block.blocker_id == user_id,
                Block.blocked_id == user_id,
            )
        )
        .all()
    )

    blocked_ids: Set[UUID] = set()
    for b in blocks:
        if b.blocker_id == user_id:
            blocked_ids.add(b.blocked_id)
        else:
            blocked_ids.add(b.blocker_id)

    return blocked_ids


def can_view_post(db: Session, user: dict, post: Post) -> bool:
    """
    يحدد إذا كان هذا اليوزر مسموح له يشوف هذا البوست.
    القواعد:
      - admin يشوف الكل (ما عدا المحذوفين لو فلترناهم خارجاً).
      - صاحب البوست يشوفه دائماً.
      - لو البوست من مستخدم محظور -> لا نسمح.
      - إن كان البوست public -> كل المستخدمين المسجلين.
      - إن كان private/friends -> فقط الأصدقاء (friendship.status = accepted).
    """
    user_id = UUID(str(user["id"]))

    # صاحب البوست أو أدمن -> مسموح دائماً
    if is_admin(user) or post.author_id == user_id:
        return True

    # لو البوست محذوف، والبشري مو أدمن ولا صاحب البوست -> لا!
    if getattr(post, "is_deleted", False):
        return False

    # لو صاحب البوست محظور -> لا نسمح
    blocked_ids = get_blocked_user_ids(db, user_id)
    if post.author_id in blocked_ids:
        return False

    visibility = (post.visibility or "public").lower()

    if visibility == "public":
        return True

    if visibility in ("private", "friends"):
        friend_ids = get_friend_ids(db, user_id)
        return post.author_id in friend_ids

    # أي قيمة غريبة للـ visibility نعتبرها غير مسموحة
    return False
