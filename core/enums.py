from enum import Enum

class GenderEnum(str, Enum):
    male = "male"
    female = "female"
    prefer_not_to_say = "prefer_not_to_say"

class FriendStatusEnum(str, Enum):
    pending = "pending"
    accepted = "accepted"
    declined = "declined"

class PrivacyLevelEnum(str, Enum):
    public = "public"
    friends = "friends"

class ApprovalStatusEnum(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"

class MediaTypeEnum(str, Enum):
    image = "image"
    video = "video"
    audio = "audio"
    file  = "file"
