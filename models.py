
from sqlalchemy import Column, Boolean, Enum,ARRAY, CheckConstraint, ForeignKey
from sqlmodel import Field ,SQLModel, Relationship
from sqlalchemy.dialects.postgresql import UUID, CITEXT, JSON
from core.enums import ApprovalStatusEnum, GenderEnum, PrivacyLevelEnum, FriendStatusEnum, MediaTypeEnum
from sqlalchemy.types import Text, Date
import uuid
from datetime import datetime, timezone
from typing import Optional, List,Dict


class Users(SQLModel, table=True):
    __tablename__ = "users"
    id: uuid.UUID = Field(default_factory=uuid.uuid4,primary_key=True)
    fullname: str = Field(sa_column=Column(Text, nullable=False))
    email: str = Field(sa_column=Column(CITEXT, unique=True, nullable=False))
    username: Optional[str] = Field(default=None,sa_column=Column(CITEXT, unique=True, nullable=True))
    password_hash: Optional[str] = Field(default=None,sa_column=Column(Text, nullable=True))
    is_active: bool = Field(default=False,sa_column=Column(Boolean, server_default="False", nullable=False))
    approval_status: ApprovalStatusEnum = Field(
        default=ApprovalStatusEnum.pending,sa_column=Column(
            Enum(ApprovalStatusEnum, name="approval_status_enum"),
            nullable=False,
            server_default="pending"
        )
    )
    approved_by: Optional[uuid.UUID] = Field(default=None,foreign_key="users.id")
    approved_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    role_id: Optional[uuid.UUID] = Field(default=None,foreign_key="roles.role_id")
    registration_token: Optional[str] = Field(default=None,
        sa_column=Column(Text, unique=True, nullable=True))
    registration_token_expires_at: Optional[datetime] = Field(default=None)
    registration_completed_at: Optional[datetime] = Field(default=None)
    is_suspended: bool = Field(default=False,
        sa_column=Column(Boolean, server_default="false", nullable=False)
    )

    # Relationships
    profile: Optional["Profile"] = Relationship(back_populates="user")
    posts: list["Post"] = Relationship(back_populates="author")
    comments: list["Comment"] = Relationship(back_populates="author")
    reactions: list["reaction"] = Relationship(back_populates="user")
    friendships_sent: list["Friendship"] = Relationship(
        back_populates="requester",
        sa_relationship_kwargs={"foreign_keys": "[Friendship.requester_id]"})
    friendships_received: list["Friendship"] = Relationship(
        back_populates="addressee",
        sa_relationship_kwargs={"foreign_keys": "[Friendship.addressee_id]"})
    
    blocks_sent: List["Block"] = Relationship(
        back_populates="blocker",
        sa_relationship_kwargs={"foreign_keys": "[Block.blocker_id]"})

    blocks_received: List["Block"] = Relationship(
        back_populates="blocked",
        sa_relationship_kwargs={"foreign_keys": "[Block.blocked_id]"})
    
    role: Optional["Role"] = Relationship(back_populates="users")
    sent_reports: List["Report"] = Relationship(back_populates="reporter",
        sa_relationship_kwargs={"foreign_keys": "[Report.reported_by]"},)

    received_reports: List["Report"] = Relationship(back_populates="reported_user",
        sa_relationship_kwargs={"foreign_keys": "[Report.reported_user_id]"},)






class Profile(SQLModel, table=True):
    __tablename__ = "profiles"

    user_id: uuid.UUID = Field(
        sa_column=Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True))
    display_name: Optional[str] = Field(default=None)
    gender: Optional[str] = Field(default=None,sa_column=Column(
            Enum(GenderEnum,name="gender_enum"),nullable=True))
    birthday: Optional[datetime] = Field(default=None,
        sa_column=Column(Date, nullable=True))
    bio: Optional[str] = Field(default=None)
    website: Optional[str] = Field(default=None)
    phone: Optional[str] = Field(default=None)
    language: Optional[str] = Field(default=None)
    location: Optional[str] = Field(default=None)
    avatar_url: Optional[str] = Field(default=None)
    cover_url: Optional[str] = Field(default=None)
    is_deleted: bool = Field(default=False, nullable=False)
   
    # Relations
    user: Optional["Users"] = Relationship(back_populates="profile")


class Post(SQLModel, table=True):
    __tablename__ = "posts"

    post_id: uuid.UUID = Field(default_factory=uuid.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True)
    )
    author_id: uuid.UUID = Field(
        sa_column=Column(UUID(as_uuid=True),ForeignKey("users.id", ondelete="CASCADE"),nullable=False)
    )
    title: Optional[str] = Field(default=None,
        sa_column=Column(Text, nullable=True)
    )
    content: Optional[str] = Field(default=None,
        sa_column=Column(Text, nullable=True)
    )
    tags: Optional[List[str]] = Field(
        default=None,
        sa_column=Column(ARRAY(Text), nullable=True)
    )
    visibility: str = Field(sa_column=Column(
            Enum(PrivacyLevelEnum,name="privacy_level"),
            nullable=False,
            server_default="public"
        ),
        default="public"
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    is_deleted: bool = Field(default=False,
        sa_column=Column(Boolean, server_default="false", nullable=False))

    #Relations
    author: Optional["Users"] = Relationship(back_populates="posts")
    reactions: list["reaction"] = Relationship(back_populates="post")
    media: list["PostMedia"] = Relationship(back_populates="post")
    comments: list["Comment"] = Relationship(back_populates="post")
    reports: List["Report"] = Relationship(back_populates="post")




class PostMedia(SQLModel, table=True):
    __tablename__ = "post_media"

    post_media_id: uuid.UUID = Field(default_factory=uuid.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True))
    post_id: uuid.UUID = Field(
        sa_column=Column(UUID(as_uuid=True), ForeignKey("posts.post_id", ondelete="CASCADE"), nullable=False))
    file_url: str = Field(
        sa_column=Column(Text, nullable=False))
    media_type: str = Field(sa_column=Column(
            Enum(MediaTypeEnum,name="media_type_enum"),nullable=False))
    meta_data: Optional[Dict] = Field(default=None,
        sa_column=Column("metadata",JSON, nullable=True))
    uploaded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


    post: Optional["Post"] = Relationship(back_populates="media")



class Comment(SQLModel, table=True):
    __tablename__ = "comments"

    comment_id: uuid.UUID = Field(default_factory=uuid.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True))
    post_id: uuid.UUID = Field(
        sa_column=Column(UUID(as_uuid=True), ForeignKey("posts.post_id", ondelete="CASCADE"),nullable=False))
    author_id: uuid.UUID = Field(
        sa_column=Column(UUID(as_uuid=True),  ForeignKey("users.id", ondelete="CASCADE"),nullable=False))
    parent_comment_id: Optional[uuid.UUID] = Field(default=None,
        sa_column=Column(UUID(as_uuid=True), ForeignKey("comments.comment_id", ondelete="CASCADE"), nullable=True))
    content: str = Field(sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    is_deleted: bool = Field(default=False,
        sa_column=Column(Boolean, server_default="false", nullable=False))

    author: Optional["Users"] = Relationship(back_populates="comments")
    post: Optional["Post"] = Relationship(back_populates="comments")
    reactions: list["reaction"] = Relationship(back_populates="comment")

    # nested replies
    replies: List["Comment"] = Relationship(
        back_populates="parent_comment"
        )
    # parent comment relation
    parent_comment: Optional["Comment"] = Relationship(
        back_populates="replies",
        sa_relationship_kwargs={"remote_side": "Comment.comment_id"}
    )
   



class reaction(SQLModel, table=True):
    __tablename__ = "reactions"

    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN post_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN comment_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="chk_like_target"
        ),
    )
    reaction_id: uuid.UUID = Field(default_factory=uuid.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True))

    user_id: uuid.UUID = Field(
        sa_column=Column(UUID(as_uuid=True),ForeignKey("users.id", ondelete="CASCADE"), nullable=False))

    post_id: Optional[uuid.UUID] = Field(default=None,
        sa_column=Column(UUID(as_uuid=True),ForeignKey("posts.post_id", ondelete="CASCADE"), nullable=True))

    comment_id: Optional[uuid.UUID] = Field(default=None,
        sa_column=Column(UUID(as_uuid=True), ForeignKey("comments.comment_id", ondelete="CASCADE"),nullable=True))
    
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Relations
    user: Optional["Users"] = Relationship(back_populates="reactions")
    post: Optional["Post"] = Relationship(back_populates="reactions")
    comment: Optional["Comment"] = Relationship(back_populates="reactions")



class Friendship(SQLModel, table=True):
    __tablename__ = "friendships"

    friend_id: uuid.UUID = Field(default_factory=uuid.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True))

    requester_id: uuid.UUID = Field(
        sa_column=Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),nullable=False))

    addressee_id: uuid.UUID = Field(
        sa_column=Column(UUID(as_uuid=True),ForeignKey("users.id", ondelete="CASCADE"), nullable=False))

    status: str = Field(default="pending",sa_column=Column(
            Enum(
                FriendStatusEnum,
                name="friend_status_enum"
            ),
            nullable=False,
            server_default="pending"
        )
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    responded_at: Optional[datetime] = Field(default=None)

    # relations
    requester: Optional["Users"] = Relationship(
        back_populates="friendships_sent",
        sa_relationship_kwargs={"foreign_keys": "[Friendship.requester_id]"}
    )
    addressee: Optional["Users"] = Relationship(
        back_populates="friendships_received",
        sa_relationship_kwargs={"foreign_keys": "[Friendship.addressee_id]"}
    )




class Block(SQLModel, table=True):
    __tablename__ = "blocks"

    block_id: uuid.UUID = Field(default_factory=uuid.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True))
    blocker_id: uuid.UUID = Field(
        sa_column=Column(UUID(as_uuid=True),ForeignKey("users.id", ondelete="CASCADE"), nullable=False))

    blocked_id: uuid.UUID = Field(
        sa_column=Column(UUID(as_uuid=True),ForeignKey("users.id", ondelete="CASCADE"), nullable=False))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # relations 
    blocker: Optional["Users"] = Relationship(
        back_populates="blocks_sent",
        sa_relationship_kwargs={"foreign_keys": "[Block.blocker_id]"}
    )

    blocked: Optional["Users"] = Relationship(
        back_populates="blocks_received",
        sa_relationship_kwargs={"foreign_keys": "[Block.blocked_id]"}
    )



class RolePermission(SQLModel, table=True):
    __tablename__ = "role_permissions"

    role_id: uuid.UUID = Field(
        sa_column=Column(UUID(as_uuid=True),ForeignKey("roles.role_id"), primary_key=True))
    permission_id: uuid.UUID = Field(
        sa_column=Column(UUID(as_uuid=True),ForeignKey("permissions.per_id"), primary_key=True))




class Permission(SQLModel, table=True):
    __tablename__ = "permissions"

    per_id: uuid.UUID = Field(default_factory=uuid.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True))
    code: str = Field(sa_column=Column(Text, nullable=False))
    description: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # Relations
    roles: List["Role"] = Relationship(back_populates="permissions",link_model=RolePermission)


class Role(SQLModel, table=True):
    __tablename__ = "roles"

    role_id: uuid.UUID = Field(default_factory=uuid.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True))
    code: str = Field(sa_column=Column(Text, nullable=False))
    name: str = Field(sa_column=Column(Text, nullable=False))
    description: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # Relations
    permissions: List["Permission"] = Relationship(back_populates="roles",link_model=RolePermission)
    users: List["Users"] = Relationship(back_populates="role")



class Report(SQLModel, table=True):
    __tablename__ = "reports"

    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN post_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN reported_user_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="chk_report_target"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True)
    )

    post_id: Optional[uuid.UUID] = Field(default=None,
        sa_column=Column(UUID(as_uuid=True),ForeignKey("posts.post_id", ondelete="CASCADE"),
            nullable=True,
            ),
    )

    reported_user_id: Optional[uuid.UUID] = Field(default=None,
        sa_column=Column(UUID(as_uuid=True),ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )

    reported_by: uuid.UUID = Field(
        sa_column=Column(UUID(as_uuid=True),ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Relations
    post: Optional["Post"] = Relationship(back_populates="reports",
        sa_relationship_kwargs={"foreign_keys": "[Report.post_id]"},
    )

    reported_user: Optional["Users"] = Relationship(back_populates="received_reports",
        sa_relationship_kwargs={"foreign_keys": "[Report.reported_user_id]"},
    )

    reporter: Optional["Users"] = Relationship(back_populates="sent_reports",
        sa_relationship_kwargs={"foreign_keys": "[Report.reported_by]"},
    )
