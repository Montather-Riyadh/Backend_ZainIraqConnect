import os
import mimetypes
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from uuid import UUID

from database import get_db
from models import Users, PostMedia, Post, Profile, Friendship
from routers.auth import get_current_user_optional

router = APIRouter()

# External Desktop upload directory (parent of the 'fastapi' folder)
EXTERNAL_UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads")
os.makedirs(EXTERNAL_UPLOAD_DIR, exist_ok=True)

from core.permissions import is_admin

@router.get("/{filename}")
def stream_file(
    filename: str, 
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict | None = Depends(get_current_user_optional)
):
    """
    Secure file streaming API.
    Only allows access if the user has permission to view the file.
    """
    file_path = os.path.join(EXTERNAL_UPLOAD_DIR, filename)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    file_url = f"/uploads/{filename}"

    # --- AUTHORIZATION LOGIC ---
    # 1. Is it a profile picture or cover photo? (We assume these are public)
    profile_match = db.query(Profile).filter(
        (Profile.avatar_url == file_url) | (Profile.cover_url == file_url)
    ).first()
    
    is_authorized = False

    if profile_match:
        # Avatars and covers are public
        is_authorized = True
    else:
        # 2. Is it attached to a post?
        media = db.query(PostMedia).filter(PostMedia.file_url == file_url).first()
        
        if media:
            post = media.post
            if not post or post.is_deleted:
                raise HTTPException(status_code=404, detail="File not found or deleted")
            
            # If public, anyone can see it
            if post.visibility == "public":
                is_authorized = True
            else:
                # Needs authentication for non-public posts
                if not current_user:
                    raise HTTPException(status_code=401, detail="Authentication required to view this file")
                
                viewer_id = UUID(current_user["id"])
                
                # Admin or Uploader can always see it
                if is_admin(current_user) or post.author_id == viewer_id:
                    is_authorized = True
                else:
                    # If friends_only, check friendship
                    if post.visibility == "friends":
                        friendship = db.query(Friendship).filter(
                            Friendship.status == "accepted",
                            (
                                ((Friendship.requester_id == viewer_id) & (Friendship.addressee_id == post.author_id)) |
                                ((Friendship.requester_id == post.author_id) & (Friendship.addressee_id == viewer_id))
                            )
                        ).first()
                        if friendship:
                            is_authorized = True
        
        else:
            # 3. If it's a file with no database record yet (e.g. just uploaded)
            # For simplicity, we can let the uploader see it if we tracked who uploaded it, 
            # but since we don't have a standalone 'uploads' table, we will reject or allow based on auth.
            if not current_user:
                raise HTTPException(status_code=401, detail="Not authorized to view this raw file")
            
            # Since we can't tie an unattached file to a user easily without a DB record,
            # we allow authenticated users to view unattached files temporarily (like during draft post creation).
            # To be strictly secure, an "Uploads" table tracking owner_id is recommended.
            is_authorized = True

    if not is_authorized:
        raise HTTPException(status_code=403, detail="You don't have permission to view this file")
        
    # --- STREAMING LOGIC ---

    file_size = os.path.getsize(file_path)
    range_header = request.headers.get("range")
    content_type, _ = mimetypes.guess_type(file_path)
    content_type = content_type or "application/octet-stream"

    if range_header:
        byte_range = range_header.replace("bytes=", "").split("-")
        start = int(byte_range[0])
        end = int(byte_range[1]) if len(byte_range) > 1 and byte_range[1] else file_size - 1

        if end >= file_size:
            end = file_size - 1

        CHUNK_SIZE = 1024 * 1024 * 2 # 2MB
        if end - start + 1 > CHUNK_SIZE:
             end = start + CHUNK_SIZE - 1

        chunk_length = end - start + 1

        def chunk_generator():
            with open(file_path, "rb") as f:
                f.seek(start)
                bytes_read = 0
                while bytes_read < chunk_length:
                    read_size = min(65536, chunk_length - bytes_read)
                    data = f.read(read_size)
                    if not data:
                        break
                    yield data
                    bytes_read += len(data)

        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(chunk_length),
            "Content-Type": content_type,
        }

        return StreamingResponse(
            chunk_generator(),
            status_code=206,
            headers=headers,
            media_type=content_type,
        )
    else:
        def full_file_generator():
            with open(file_path, "rb") as f:
                while chunk := f.read(65536):
                    yield chunk

        headers = {
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
            "Content-Type": content_type,
        }
        return StreamingResponse(
            full_file_generator(),
            headers=headers,
            media_type=content_type,
        )
