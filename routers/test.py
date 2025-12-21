from fastapi import APIRouter, BackgroundTasks
from fastapi_mail import FastMail, MessageSchema, MessageType
from core.config import conf

fm = FastMail(conf)

router = APIRouter(prefix="/user", tags=["Users"])



from pydantic import BaseModel, EmailStr

class TestEmailRequest(BaseModel):
    email: EmailStr

@router.post("/test-email")
async def send_test_email(data: TestEmailRequest, background_tasks: BackgroundTasks):
    message = MessageSchema(
        subject="Test Email from FastAPI",
        recipients=[data.email],
        body="<h2>Test OK ✅</h2><p>If you see this, FastAPI-Mail is working!</p>",
        subtype=MessageType.html,
    )

    # نرسل في الخلفية حتى ما يتأخر الرد
    background_tasks.add_task(fm.send_message, message)

    return {"detail": "Test email scheduled to be sent"}
