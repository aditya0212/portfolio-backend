# main.py — FastAPI Backend for Portfolio Contact Form
# Deployed on: Render
# DB: Supabase (PostgreSQL via psycopg2)
# Email: Resend API (reliable, free, 100 emails/day)

import os
import logging
import threading
import urllib.request
import json
from datetime import datetime

import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, field_validator

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
RESEND_API_KEY  = os.getenv("RESEND_API_KEY")
NOTIFY_TO_EMAIL = os.getenv("NOTIFY_TO_EMAIL")
FROM_EMAIL      = os.getenv("FROM_EMAIL", "onboarding@resend.dev")


# ─── Pydantic Schemas ─────────────────────────────────────────────────────────
class ContactRequest(BaseModel):
    name: str
    email: EmailStr
    message: str

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Name must not be empty")
        if len(v.strip()) > 100:
            raise ValueError("Name must be under 100 characters")
        return v.strip()

    @field_validator("message")
    @classmethod
    def message_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Message must not be empty")
        if len(v.strip()) > 5000:
            raise ValueError("Message must be under 5000 characters")
        return v.strip()


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


# ─── Email via Resend ─────────────────────────────────────────────────────────
def send_notification_email(name: str, email: str, message: str) -> None:
    if not RESEND_API_KEY or not NOTIFY_TO_EMAIL:
        logger.warning("[Email] RESEND_API_KEY or NOTIFY_TO_EMAIL not set — skipping.")
        return

    html_body = f"""
    <div style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:24px;">
      <h2 style="color:#7c3aed;">New Portfolio Contact</h2>
      <table style="width:100%;border-collapse:collapse;">
        <tr>
          <td style="padding:8px;color:#666;width:80px;">Name</td>
          <td style="padding:8px;font-weight:600;">{name}</td>
        </tr>
        <tr style="background:#f9f9f9;">
          <td style="padding:8px;color:#666;">Email</td>
          <td style="padding:8px;font-weight:600;">
            <a href="mailto:{email}">{email}</a>
          </td>
        </tr>
        <tr>
          <td style="padding:8px;color:#666;">Time</td>
          <td style="padding:8px;">{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC</td>
        </tr>
      </table>
      <div style="margin-top:20px;padding:16px;background:#f3f0ff;border-radius:8px;">
        <p style="margin:0;color:#333;white-space:pre-wrap;">{message}</p>
      </div>
      <p style="margin-top:20px;color:#888;font-size:13px;">
        Reply directly to <a href="mailto:{email}">{email}</a>
      </p>
    </div>
    """

    payload = json.dumps({
        "from": FROM_EMAIL,
        "to": [NOTIFY_TO_EMAIL],
        "reply_to": email,
        "subject": f"New Portfolio Contact from {name}",
        "html": html_body,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            logger.info(f"[Email] Sent via Resend. ID: {result.get('id')}")
    except Exception as e:
        logger.error(f"[Email] Resend failed: {e}")


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