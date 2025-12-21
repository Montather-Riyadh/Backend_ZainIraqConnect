from sqlmodel import SQLModel, Session, create_engine
import os
from dotenv import load_dotenv
# تحميل المتغيرات من .env
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL)

def get_db():
    db = Session(engine)
    try:
        yield db
    finally:
        db.close()