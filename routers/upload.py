import os
import uuid
import magic
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from starlette import status
from .auth import get_current_user

router = APIRouter()

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Map extensions → media_type (matches MediaTypeEnum)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".ico"}
VIDEO_EXTS = {".mp4", ".webm", ".mov", ".avi", ".mkv", ".flv", ".wmv"}
AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".aac", ".flac", ".m4a", ".wma"}


def _detect_media_type(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    return "file"


ALLOWED_EXTS = IMAGE_EXTS | VIDEO_EXTS | AUDIO_EXTS | {".pdf", ".doc", ".docx", ".txt"}

MAX_FILE_SIZE = 200 * 1024 * 1024  # 200 MB
CHUNK_SIZE = 1024 * 1024  # 1 MB chunks for streaming

# Allowed MIME types for magic-byte validation
ALLOWED_MIMES = {
    # Images
    "image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp",
    "image/x-icon", "image/vnd.microsoft.icon",
    # Videos
    "video/mp4", "video/webm", "video/quicktime", "video/x-msvideo",
    "video/x-matroska", "video/x-flv", "video/x-ms-wmv",
    # Audio
    "audio/mpeg", "audio/wav", "audio/ogg", "audio/aac", "audio/flac",
    "audio/x-m4a", "audio/x-ms-wma",
    # Documents
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
}


@router.post("/", status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    # Validate file extension
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{ext}' is not allowed. Allowed: {', '.join(sorted(ALLOWED_EXTS))}"
        )

    # Generate unique filename
    unique_name = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(UPLOAD_DIR, unique_name)

    #  Stream file to disk in chunks instead of loading entirely into memory
    total_size = 0
    first_chunk = None
    try:
        with open(file_path, "wb") as f:
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > MAX_FILE_SIZE:
                    # Clean up partial file and abort
                    f.close()
                    os.remove(file_path)
                    raise HTTPException(status_code=413, detail="File too large (max 200MB)")
                # Save the first chunk for MIME validation
                if first_chunk is None:
                    first_chunk = chunk
                f.write(chunk)
    except HTTPException:
        raise
    except Exception:
        # Clean up on unexpected error
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=500, detail="Failed to save file")

    if total_size == 0:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=400, detail="Empty file")

    #  Validate MIME type using magic bytes (actual file content)
    mime = magic.from_buffer(first_chunk[:2048], mime=True)
    if mime not in ALLOWED_MIMES:
        os.remove(file_path)
        raise HTTPException(
            status_code=400,
            detail=f"File content type '{mime}' is not allowed."
        )

    media_type = _detect_media_type(file.filename)

    return {
        "file_url": f"/uploads/{unique_name}",
        "media_type": media_type,
        "original_name": file.filename,
    }
