from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
import os
import models
from database import engine
from routers import auth, comment, users, profile, post, postmedia, Blocks, Friendships, report, reaction, upload
from dotenv import load_dotenv

from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

load_dotenv()

# ── Rate Limiter ──
limiter = Limiter(key_func=get_remote_address)

app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.on_event("startup")
async def startup():
    FastAPICache.init(InMemoryBackend(), prefix="fastapi-cache")

# CORS — configurable via env
cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in cors_origins],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

models.SQLModel.metadata.create_all(bind=engine)

# ── Cleanup stale refresh tokens (runs once on startup, then periodically) ──
import asyncio
import logging
from datetime import datetime, timezone
from database import get_db
from models import RefreshToken

logger = logging.getLogger("cleanup")


def _cleanup_tokens_sync():
    """Synchronous DB cleanup — runs in a thread to avoid blocking the event loop."""
    db = next(get_db())
    try:
        now = datetime.now(timezone.utc)
        deleted = (
            db.query(RefreshToken)
            .filter(
                (RefreshToken.is_revoked == True) | (RefreshToken.expires_at < now)
            )
            .delete(synchronize_session=False)
        )
        db.commit()
        return deleted
    finally:
        db.close()


async def cleanup_stale_refresh_tokens():
    """Delete revoked and expired refresh tokens every 24 hours."""
    while True:
        try:
            # ✅ BQ-07: Run synchronous DB work in a thread pool
            deleted = await asyncio.to_thread(_cleanup_tokens_sync)
            logger.info(f"Cleaned up {deleted} stale refresh tokens")
        except Exception as e:
            logger.exception("Failed to cleanup refresh tokens")
        await asyncio.sleep(86400)  # every 24 hours

@app.on_event("startup")
async def startup_cleanup():
    asyncio.create_task(cleanup_stale_refresh_tokens())

# Stream files from external directory
from routers import stream
app.include_router(stream.router, prefix="/uploads", tags=["Uploads"])

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(profile.router, prefix="/profile", tags=["Profile"])
app.include_router(comment.router, prefix="/comments", tags=["Comments"])
app.include_router(post.router, prefix="/posts", tags=["Posts"])
app.include_router(postmedia.router, prefix="/postmedia", tags=["PostMedia"])
app.include_router(reaction.router, prefix="/reactions", tags=["Reactions"])
app.include_router(Blocks.router, prefix="/blocks", tags=["Blocks"])
app.include_router(Friendships.router, prefix="/friendships", tags=["Friendships"])
app.include_router(report.router)
app.include_router(upload.router, prefix="/upload", tags=["Upload"])

