import os
os.environ["DATABASE_URL"] = "postgresql://myuser:mypassword@localhost:5432/iraqconnect"

from database import engine
from sqlmodel import Session
from models import Post, Users
from routers.post import get_feed

with Session(engine) as db:
    users = db.query(Users).all()
    # find exactly the user who is fetching the feed, and the user who wrote the post
    print("Users:")
    for u in users:
        print(f" - {u.email} ({u.id})")
        
    posts = db.query(Post).all()
    print("\nPosts:")
    for p in posts:
        print(f" - {p.post_id} by {p.author_id} visibility: {p.visibility} content: {p.content[:20]}")
