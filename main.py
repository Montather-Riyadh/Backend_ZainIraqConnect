from fastapi import FastAPI
import models
from database import engine
from routers import auth, comment, users, profile,post,postmedia,Blocks,Friendships,report,reaction,test

app = FastAPI()

models.SQLModel.metadata.create_all(bind=engine)


app.include_router(auth.router)
app.include_router(users.router)
app.include_router(profile.router)
app.include_router(comment.router)
app.include_router(post.router)
app.include_router(postmedia.router)
app.include_router(reaction.router)
app.include_router(Blocks.router)
app.include_router(Friendships.router)
app.include_router(report.router)
app.include_router(test.router)