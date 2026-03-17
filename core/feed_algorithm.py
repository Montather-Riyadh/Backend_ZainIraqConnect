






"""
Weighted Score Feed Algorithm
=============================
Ranks posts by: engagement × relationship_bonus × time_decay

Score = (reaction_count * 2 + comment_count * 3 + 1) * relationship_bonus * time_decay

- relationship_bonus: 1.5 (friend), 1.2 (own post), 1.0 (other)
- time_decay: 1 / (1 + hours_old / 24) ^ 1.5
"""

from typing import Set
from uuid import UUID
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from sqlalchemy import func, case, literal, or_, and_
from sqlalchemy.sql import expression

from models import Post, Comment, Reaction


def build_ranked_feed_query(
    db: Session,
    user_id: UUID,
    friend_ids: Set[UUID],
    blocked_ids: Set[UUID],
    skip: int = 0,
    limit: int = 50,
):
    """
    Build a query that returns posts ranked by the weighted score algorithm.
    Respects visibility rules, friendship, and block lists.
    """

    now = datetime.now(timezone.utc)

    # ── Subqueries for counts ──────────────────────────────────────────
    reaction_sub = (
        db.query(
            Reaction.post_id,
            func.count(Reaction.reaction_id).label("reaction_count"),
        )
        .filter(Reaction.post_id.isnot(None))
        .group_by(Reaction.post_id)
        .subquery("reaction_counts")
    )

    comment_sub = (
        db.query(
            Comment.post_id,
            func.count(Comment.comment_id).label("comment_count"),
        )
        .filter(Comment.is_deleted == False)
        .group_by(Comment.post_id)
        .subquery("comment_counts")
    )

    # ── Engagement score ───────────────────────────────────────────────
    r_count = func.coalesce(reaction_sub.c.reaction_count, 0)
    c_count = func.coalesce(comment_sub.c.comment_count, 0)
    engagement = (r_count * 2 + c_count * 3 + 1).label("engagement")

    # ── Relationship bonus ─────────────────────────────────────────────
    if friend_ids:
        relationship_bonus = case(
            (Post.author_id == user_id, 1.2),
            (Post.author_id.in_(list(friend_ids)), 1.5),
            else_=1.0,
        )
    else:
        relationship_bonus = case(
            (Post.author_id == user_id, 1.2),
            else_=1.0,
        )

    # ── Time decay ─────────────────────────────────────────────────────
    # hours_old = extract(epoch from (now - created_at)) / 3600
    hours_old = func.extract("epoch", literal(now) - Post.created_at) / 3600.0
    time_decay = 1.0 / func.power(1.0 + hours_old / 24.0, 1.5)

    # ── Final score ────────────────────────────────────────────────────
    score = (
        (r_count * 2 + c_count * 3 + 1)
        * relationship_bonus
        * time_decay
    ).label("feed_score")

    # ── Visibility conditions ──────────────────────────────────────────
    visibility_conditions = [
        Post.author_id == user_id,       # بوستاتي
        Post.visibility == "public",     # بوستات عامة
    ]

    if friend_ids:
        visibility_conditions.append(
            and_(
                Post.visibility == "friends",
                Post.author_id.in_(list(friend_ids)),
            )
        )

    # ── Build the query ────────────────────────────────────────────────
    query = (
        db.query(Post, score)
        .outerjoin(reaction_sub, reaction_sub.c.post_id == Post.post_id)
        .outerjoin(comment_sub, comment_sub.c.post_id == Post.post_id)
        .filter(Post.is_deleted == False)
        .filter(or_(*visibility_conditions))
    )

    # استبعاد المحظورين
    if blocked_ids:
        query = query.filter(~Post.author_id.in_(blocked_ids))

    query = (
        query
        .order_by(score.desc())
        .offset(skip)
        .limit(limit)
    )

    return query
