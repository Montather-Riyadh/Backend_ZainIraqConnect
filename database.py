from sqlmodel import SQLModel, Session, create_engine
import os
from dotenv import load_dotenv
# تحميل المتغيرات من .env
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(
    DATABASE_URL,
    pool_size=10,          # Maintain 10 persistent connections
    max_overflow=20,       # Allow up to 20 extra under high load
    pool_pre_ping=True,    # Detect stale connections before use
    pool_recycle=1800,     # Recycle connections every 30 minutes
    echo=False,
)

def get_db():
    db = Session(engine)
    try:
        yield db
    finally:
        db.close()