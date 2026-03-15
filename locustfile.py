import os
import uuid
import random
import string
from datetime import datetime, timezone
from locust import HttpUser, task, between, events
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

import sys
# Add current directory to path so we can import models
sys.path.append(os.path.dirname(__file__))
from models import Users, Role, Profile
from passlib.context import CryptContext

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not found in .env")
    sys.exit(1)

# DB setup for injecting users directly (bypassing email flow)
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
bcrypt_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class IraqConnectUser(HttpUser):
    # Simulate a user opening the app, browsing for 1-5 seconds, then doing an action
    wait_time = between(1, 5)
    
    def on_start(self):
        """
        Runs once per simulated user.
        1. Create a user directly in DB (Active, Approved)
        2. Hit login endpoint to get JWT token
        """
        self.username = "testuser_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
        self.email = f"{self.username}@test.locust"
        self.password = "Test@123!"
        self.user_id = uuid.uuid4()
        
        # 1. Insert directly to Database
        with SessionLocal() as db:
            # Find user role
            user_role = db.query(Role).filter(Role.code == "user").first()
            role_id = user_role.role_id if user_role else None
            
            # Create User
            new_user = Users(
                id=self.user_id,
                fullname="Locust Test User",
                email=self.email,
                username=self.username,
                password_hash=bcrypt_context.hash(self.password),
                is_active=True,
                approval_status="approved",
                approved_at=datetime.now(timezone.utc),
                registration_completed_at=datetime.now(timezone.utc),
                role_id=role_id,
            )
            db.add(new_user)
            
            # Create Profile
            new_profile = Profile(
                user_id=self.user_id,
                display_name=f"Locust {self.username}",
                bio="I am a load testing bot.",
            )
            db.add(new_profile)
            
            db.commit()
            
        # 2. Login to get JWT
        response = self.client.post(
            "/auth/token", 
            data={"username": self.username, "password": self.password},
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        
        if response.status_code == 200:
            self.token = response.json().get("access_token")
            # Set authorization header for all future requests
            self.client.headers.update({"Authorization": f"Bearer {self.token}"})
            self.known_post_ids = []
        else:
            print(f"Failed to login user {self.username}: {response.text}")
            self.token = None


    def on_stop(self):
        """
        Runs when the simulated user stops.
        Clean up the user from the database.
        """
        with SessionLocal() as db:
            user = db.query(Users).filter(Users.id == self.user_id).first()
            if user:
                db.delete(user)
                db.commit()


    @task(4)
    def view_feed(self):
        """Scroll the feed and collect post IDs (Weight = 4)"""
        if not self.token: return

        # Request feed
        with self.client.get("/posts/feed?skip=0&limit=20", catch_response=True) as response:
            if response.status_code == 200:
                posts = response.json()
                # Store up to 50 post IDs to react/comment on later
                self.known_post_ids = [p["post_id"] for p in posts][:50]
            elif response.status_code == 404:
                # 404 just means no posts yet
                response.success()


    @task(1)
    def create_post(self):
        """Create a new post (Weight = 1)"""
        if not self.token: return
        
        payload = {
            "content": f"Hello from Locust {self.username}! Random data: {uuid.uuid4()}",
            "visibility": "public"
        }
        self.client.post("/posts/post", json=payload)


    @task(2)
    def react_to_post(self):
        """Like a random post from the feed (Weight = 2)"""
        if not self.token or not self.known_post_ids: return
        
        post_id = random.choice(self.known_post_ids)
        with self.client.post(f"/reactions/post/{post_id}", catch_response=True) as response:
            if response.status_code in [201, 400]: # 400 usually means "Already reacted", which is fine for our load test
                response.success()


    @task(1)
    def comment_on_post(self):
        """Comment on a random post (Weight = 1)"""
        if not self.token or not self.known_post_ids: return
        
        post_id = random.choice(self.known_post_ids)
        payload = {
            "content": f"Great post! Generating load... {random.randint(1, 1000)}"
        }
        # In our FastApi code, CommentRequest is passed as Depends(), meaning it expects query params or form-data,
        # but the BaseModel is normally sent via query params for depends().
        # Let's send as JSON and let FastAPI handle it if configured, or use params.
        # Note: In `routers/comment.py` -> create_comment has `comment_request: CommentRequest = Depends()`.
        # Sending as query parameters is required if it's Depends() without form.
        self.client.post(f"/comments/post/{post_id}", params=payload)
