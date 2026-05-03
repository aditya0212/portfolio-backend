# main.py — FastAPI Backend for Portfolio Contact Form
# Deployed on: Render
# DB: Supabase (PostgreSQL via psycopg2)
# Email: Gmail SMTP (via smtplib)

import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
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
        "https://your-portfolio.vercel.app",   # ← Replace with your Vercel URL
        "http://localhost:5173",               # Vite dev server
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Environment Variables ─────────────────────────────────────────────────────
# Set these in Render Dashboard → Environment
SUPABASE_DB_URL   = os.getenv("SUPABASE_DB_URL")       # postgres://user:pass@host:5432/postgres
SMTP_HOST         = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT         = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER         = os.getenv("SMTP_USER")             # your Gmail address
SMTP_PASSWORD     = os.getenv("SMTP_PASSWORD")         # Gmail App Password (16 chars)
NOTIFY_TO_EMAIL   = os.getenv("NOTIFY_TO_EMAIL")       # where you want to receive alerts


# ─── Pydantic Schema ───────────────────────────────────────────────────────────
class ContactRequest(BaseModel):
    name: str
    email: EmailStr
    message: str

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Name must not be empty")
        if len(v.strip()) > 100:
            raise ValueError("Name must be under 100 characters")
        return v.strip()

    @field_validator("message")
    @classmethod
    def message_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Message must not be empty")
        if len(v.strip()) > 5000:
            raise ValueError("Message must be under 5000 characters")
        return v.strip()


class ContactResponse(BaseModel):
    success: bool
    message: str


# ─── Database Helpers ──────────────────────────────────────────────────────────
def get_db_connection():
    """Returns a psycopg2 connection to Supabase PostgreSQL."""
    if not SUPABASE_DB_URL:
        raise RuntimeError("SUPABASE_DB_URL environment variable is not set.")
    conn = psycopg2.connect(SUPABASE_DB_URL, cursor_factory=RealDictCursor)
    return conn


def save_contact_to_db(name: str, email: str, message: str) -> None:
    """Inserts a contact form submission into Supabase PostgreSQL."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO contacts (name, email, message, created_at)
                VALUES (%s, %s, %s, %s)
                """,
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


# ─── Email Helpers ─────────────────────────────────────────────────────────────
def send_notification_email(name: str, email: str, message: str) -> None:
    """Sends an email notification to NOTIFY_TO_EMAIL via Gmail SMTP."""
    if not all([SMTP_USER, SMTP_PASSWORD, NOTIFY_TO_EMAIL]):
        logger.warning("[Email] SMTP credentials not set — skipping email.")
        return

    subject = f"📬 New Portfolio Contact from {name}"
    body = f"""
You received a new message from your portfolio contact form.

━━━━━━━━━━━━━━━━━━━━━━━━━━
👤 Name:    {name}
📧 Email:   {email}
🕐 Time:    {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC
━━━━━━━━━━━━━━━━━━━━━━━━━━

💬 Message:
{message}

━━━━━━━━━━━━━━━━━━━━━━━━━━
Reply directly to: {email}
"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SMTP_USER
    msg["To"]      = NOTIFY_TO_EMAIL
    msg["Reply-To"] = email
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, NOTIFY_TO_EMAIL, msg.as_string())
        logger.info(f"[Email] Notification sent for contact from {email}")
    except smtplib.SMTPAuthenticationError:
        logger.error("[Email] SMTP authentication failed — check SMTP_USER and SMTP_PASSWORD")
    except Exception as e:
        logger.error(f"[Email] Failed to send notification: {e}")


# ─── Routes ───────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"status": "ok", "service": "Portfolio Contact API v2"}


@app.get("/health")
def health_check():
    """Used by Render health checks to keep the service alive."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@app.post("/contact", response_model=ContactResponse)
async def submit_contact(payload: ContactRequest):
    """
    Receives contact form submission.
    1. Validates input via Pydantic.
    2. Saves to Supabase PostgreSQL.
    3. Sends email notification to owner.
    """
    try:
        # Step 1: Save to database
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

    # Step 2: Send email notification (non-blocking — failure won't reject the request)
    try:
        send_notification_email(
            name=payload.name,
            email=payload.email,
            message=payload.message,
        )
    except Exception as e:
        logger.warning(f"[Email] Non-fatal: {e}")

    return ContactResponse(
        success=True,
        message="Message received! I'll get back to you soon.",
    )