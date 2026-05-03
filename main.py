# main.py — FastAPI Backend for Portfolio Contact Form
# Deployed on: Render
# DB: Supabase (PostgreSQL via psycopg2)
# Email: Gmail SMTP via SSL port 465 (reliable on Render)

import os
import logging
import threading
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── App Setup ────────────────────────────────────────────────────────────────
app = FastAPI(title="Portfolio Contact API", version="2.0.0")

# ─── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://adityaportfolio-lemon.vercel.app/",  # ← Replace with your Vercel URL
        "http://localhost:5173",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Environment Variables ────────────────────────────────────────────────────
SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL")
SMTP_USER       = os.getenv("SMTP_USER")       # your Gmail: aditya021201@gmail.com
SMTP_PASSWORD   = os.getenv("SMTP_PASSWORD")   # 16-char App Password (no spaces)
NOTIFY_TO_EMAIL = os.getenv("NOTIFY_TO_EMAIL") # same Gmail or any destination


# ─── Pydantic Schemas ─────────────────────────────────────────────────────────
class ContactRequest(BaseModel):
    name: str
    email: str
    message: str

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name must not be empty")
        if len(v) > 100:
            raise ValueError("Name must be under 100 characters")
        return v

    @field_validator("email")
    @classmethod
    def email_basic_check(cls, v: str) -> str:
        v = v.strip()
        if not v or "@" not in v:
            raise ValueError("Invalid email address")
        return v

    @field_validator("message")
    @classmethod
    def message_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Message must not be empty")
        if len(v) > 5000:
            raise ValueError("Message must be under 5000 characters")
        return v


class ContactResponse(BaseModel):
    success: bool
    message: str


# ─── Database ─────────────────────────────────────────────────────────────────
def get_db_connection():
    if not SUPABASE_DB_URL:
        raise RuntimeError("SUPABASE_DB_URL is not set.")
    return psycopg2.connect(
        SUPABASE_DB_URL + "?sslmode=require",
        cursor_factory=RealDictCursor
    )


def save_contact_to_db(name: str, email: str, message: str) -> None:
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO contacts (name, email, message, created_at) VALUES (%s, %s, %s, %s)",
                (name, email, message, datetime.utcnow()),
            )
        conn.commit()
        logger.info(f"[DB] Saved contact from {email}")
    except Exception as e:
        logger.error(f"[DB] Failed to save contact: {e}")
        raise
    finally:
        if conn:
            conn.close()


# ─── Email via Gmail SSL port 465 ─────────────────────────────────────────────
def send_notification_email(name: str, email: str, message: str) -> None:
    if not SMTP_USER or not SMTP_PASSWORD or not NOTIFY_TO_EMAIL:
        logger.warning("[Email] SMTP_USER / SMTP_PASSWORD / NOTIFY_TO_EMAIL not set — skipping.")
        return

    subject = f"New Portfolio Contact from {name}"
    body = f"""
New message from your portfolio contact form.

Name:    {name}
Email:   {email}
Time:    {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC

Message:
{message}

---
Reply directly to: {email}
"""

    msg = MIMEMultipart("alternative")
    msg["Subject"]  = subject
    msg["From"]     = SMTP_USER
    msg["To"]       = NOTIFY_TO_EMAIL
    msg["Reply-To"] = email
    msg.attach(MIMEText(body, "plain"))

    try:
        # Port 465 with SSL — works on Render, no STARTTLS needed
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context, timeout=15) as server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, NOTIFY_TO_EMAIL, msg.as_string())
        logger.info(f"[Email] Sent successfully to {NOTIFY_TO_EMAIL}")
    except smtplib.SMTPAuthenticationError:
        logger.error("[Email] Auth failed — check SMTP_USER and SMTP_PASSWORD (App Password, no spaces)")
    except Exception as e:
        logger.error(f"[Email] Failed: {e}")


def send_notification_email_async(name: str, email: str, message: str) -> None:
    thread = threading.Thread(
        target=send_notification_email,
        args=(name, email, message),
        daemon=True,
    )
    thread.start()


# ─── Routes ───────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"status": "ok", "service": "Portfolio Contact API v2"}


@app.get("/health")
def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@app.post("/contact", response_model=ContactResponse)
async def submit_contact(payload: ContactRequest):
    try:
        save_contact_to_db(
            name=payload.name,
            email=payload.email,
            message=payload.message,
        )
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Failed to save your message. Please try again.",
        )

    send_notification_email_async(
        name=payload.name,
        email=payload.email,
        message=payload.message,
    )

    return ContactResponse(
        success=True,
        message="Message received! I'll get back to you soon.",
    )