from database import SessionLocal
from models import Post, str_uuid, Users, Friendship
from uuid import UUID
from core.access_control import get_friend_ids
from sqlalchemy import or_, and_

db = SessionLocal()
posts = db.query(Post).limit(5).all()

# manually create a set of UUIDs
uids = set([p.author_id for p in posts])
print(uids)

query = db.query(Post).filter(Post.author_id.in_(uids)).all()
print(f"Posts found with SET: {len(query)}")

query2 = db.query(Post).filter(Post.author_id.in_(list(uids))).all()
print(f"Posts found with LIST: {len(query2)}")
