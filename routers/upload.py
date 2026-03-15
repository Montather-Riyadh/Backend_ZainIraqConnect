import os
import uuid
from fastapi import APIRouter, UploadFile, File, HTTPException
from starlette import status

router = APIRouter()

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Map extensions → media_type (matches MediaTypeEnum)
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".ico"}
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


MAX_FILE_SIZE = 200 * 1024 * 1024  # 200 MB


@router.post("/", status_code=status.HTTP_201_CREATED)
async def upload_file(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    # Read file content
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 200MB)")

    # Generate unique filename
    ext = os.path.splitext(file.filename)[1].lower()
    unique_name = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(UPLOAD_DIR, unique_name)

    # Save file
    with open(file_path, "wb") as f:
        f.write(content)

    media_type = _detect_media_type(file.filename)

    return {
        "file_url": f"/uploads/{unique_name}",
        "media_type": media_type,
        "original_name": file.filename,
    }
