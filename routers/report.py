from uuid import UUID
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
from models import Report, Post, Users
from .auth import get_current_user
from core.permissions import require_role  



db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]

router = APIRouter(
    prefix="/reports",
    tags=["Reports"],
)


#  تأكد أن البوست موجود
def _get_post_or_404(db: Session, post_id: UUID) -> Post:
    post = db.query(Post).filter(Post.post_id == post_id).first()
    if post is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found",
        )
    return post


#  تأكد أن اليوزر موجود
def _get_user_or_404(db: Session, user_id: UUID) -> Users:
    user = db.query(Users).filter(Users.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return user


# POST /reports/post/{post_id}
# - تبليغ عن بوست
# - نفس اليوزر يحق له مرّة وحدة فقط يبليغ على نفس البوست
@router.post("/post/{post_id}", status_code=status.HTTP_201_CREATED)
def report_post(post_id: UUID,db: db_dependency,current_user: user_dependency,):
    # تأكد البوست موجود
    _get_post_or_404(db, post_id)

    reporter_id = current_user["id"]
    # هل هذا اليوزر سبق وبلغ على هذا البوست؟
    existing_report = (
        db.query(Report)
        .filter(
            Report.post_id == post_id,
            Report.reported_user_id == None,  # نضمن أنه report على بوست مو على يوزر
            Report.reported_by == reporter_id,
        )
        .first()
    )

    if existing_report is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You have already reported this post",
        )

    # إنشاء report جديد
    new_report = Report(
        post_id=post_id,
        reported_user_id=None,
        reported_by=reporter_id,
    )

    db.add(new_report)
    db.commit()
    db.refresh(new_report)

    return {
        "message": "Post reported successfully",
        "report_id": str(new_report.id),
    }


# POST /reports/user/{user_id}
# - تبليغ عن يوزر
# - نفس اليوزر يحق له مرّة وحدة فقط يبليغ على نفس اليوزر
@router.post("/user/{user_id}", status_code=status.HTTP_201_CREATED)
def report_user(user_id: UUID,db: db_dependency,current_user: user_dependency,):
    # لا تسمح لليوزر يبلغ على نفسه
    if user_id == current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot report yourself",
        )

    # تأكد اليوزر الهدف موجود
    _get_user_or_404(db, user_id)

    reporter_id = current_user["id"]
    # هل هذا اليوزر سبق وبلغ على هذا اليوزر؟
    existing_report = (
        db.query(Report)
        .filter(
            Report.post_id == None,  # نضمن أنه report على يوزر مو على بوست
            Report.reported_user_id == user_id,
            Report.reported_by == reporter_id,
        )
        .first()
    )

    if existing_report is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You have already reported this user",
        )

    # إنشاء report جديد
    new_report = Report(
        post_id=None,
        reported_user_id=user_id,
        reported_by=reporter_id,
    )

    db.add(new_report)
    db.commit()
    db.refresh(new_report)

    return {
        "message": "User reported successfully",
        "report_id": str(new_report.id),
    }


# GET /reports/post/{post_id}/count
# - عدد البلاغات على بوست معيّن (للـ admin + registrar فقط)
@router.get("/post/{post_id}/count")
def get_post_reports_count(
    post_id: UUID,
    db: db_dependency,
    current_user: user_dependency,
):
    #  صلاحيات: فقط admin و registrar
    require_role(current_user, "admin", "registrar")

    _get_post_or_404(db, post_id)

    count = (
        db.query(Report)
        .filter(
            Report.post_id == post_id,
            Report.reported_user_id == None,
        )
        .count()
    )

    return {"post_id": str(post_id), "reports_count": count}


# GET /reports/user/{user_id}/count
# - عدد البلاغات على يوزر معيّن (للـ admin + registrar فقط)
@router.get("/user/{user_id}/count")
def get_user_reports_count(
    user_id: UUID,
    db: db_dependency,
    current_user: user_dependency,
):
    #  صلاحيات: فقط admin و registrar
    require_role(current_user, "admin", "registrar")

    _get_user_or_404(db, user_id)

    count = (
        db.query(Report)
        .filter(
            Report.post_id == None,
            Report.reported_user_id == user_id,
        )
        .count()
    )

    return {"user_id": str(user_id), "reports_count": count}
