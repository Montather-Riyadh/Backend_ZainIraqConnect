from fastapi_mail import ConnectionConfig
import os
from dotenv import load_dotenv

# تحميل المتغيرات من .env
load_dotenv()

conf = ConnectionConfig(
    MAIL_USERNAME=os.getenv("MAIL_USERNAME"),
    MAIL_PASSWORD=os.getenv("MAIL_PASSWORD"),
    MAIL_FROM=os.getenv("MAIL_FROM"),
    MAIL_FROM_NAME=os.getenv("MAIL_FROM_NAME"),
    MAIL_PORT=int(os.getenv("MAIL_PORT")),
    MAIL_SERVER=os.getenv("MAIL_SERVER"),
    MAIL_STARTTLS=True,  
    MAIL_SSL_TLS=False,   
    USE_CREDENTIALS=True,
    VALIDATE_CERTS=True,
)
