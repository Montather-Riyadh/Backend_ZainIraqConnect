from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
import models
from database import engine
from routers import auth, comment, users, profile, post, postmedia, Blocks, Friendships, report, reaction, upload

from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend

app = FastAPI()

@app.on_event("startup")
async def startup():
    FastAPICache.init(InMemoryBackend(), prefix="fastapi-cache")

# CORS — allow frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

models.SQLModel.metadata.create_all(bind=engine)

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

