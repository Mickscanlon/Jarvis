"""
email_windows.py - IMAP email integration (Gmail, Outlook, any provider)
"""
import os
import imaplib
import email
import logging
from email.header import decode_header
from typing import Optional
from dotenv import load_dotenv
from llm import chat

load_dotenv(dotenv_path="C:/Users/micha/jarvis/.env")
logger = logging.getLogger(__name__)

IMAP_SERVER = os.getenv("EMAIL_IMAP_SERVER", "imap.gmail.com")
EMAIL_ADDR = os.getenv("EMAIL_ADDRESS", "")
EMAIL_PASS = os.getenv("EMAIL_PASSWORD", "")


def _decode_header_value(val) -> str:
    if not val:
        return ""
    decoded_parts = decode_header(val)
    parts = []
    for data, charset in decoded_parts:
        if isinstance(data, bytes):
            parts.append(data.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(str(data))
    return " ".join(parts)


def _connect() -> Optional[imaplib.IMAP4_SSL]:
    if not EMAIL_ADDR or not EMAIL_PASS:
        return None
    try:
        conn = imaplib.IMAP4_SSL(IMAP_SERVER)
        conn.login(EMAIL_ADDR, EMAIL_PASS)
        return conn
    except Exception as e:
        logger.error(f"[Email] Connection failed: {e}")
        return None


def get_unread_count() -> str:
    conn = _connect()
    if not conn:
        return "Email not configured."
    try:
        conn.select("INBOX")
        _, data = conn.search(None, "UNSEEN")
        count = len(data[0].split()) if data[0] else 0
        conn.logout()
        return f"You have {count} unread {'message' if count == 1 else 'messages'}, sir."
    except Exception as e:
        return f"Email error: {e}"


def get_recent_emails(limit: int = 5) -> list[dict]:
    conn = _connect()
    if not conn:
        return []
    try:
        conn.select("INBOX")
        _, data = conn.search(None, "UNSEEN")
        ids = data[0].split() if data[0] else []
        ids = ids[-limit:]  # most recent

        messages = []
        for uid in reversed(ids):
            _, msg_data = conn.fetch(uid, "(RFC822)")
            for response in msg_data:
                if isinstance(response, tuple):
                    msg = email.message_from_bytes(response[1])
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                body = part.get_payload(decode=True).decode("utf-8", errors="replace")
                                break
                    else:
                        body = msg.get_payload(decode=True).decode("utf-8", errors="replace")

                    messages.append({
                        "uid": uid.decode(),
                        "from": _decode_header_value(msg.get("From")),
                        "subject": _decode_header_value(msg.get("Subject")),
                        "date": msg.get("Date", ""),
                        "body": body[:3000],
                    })
        conn.logout()
        return messages
    except Exception as e:
        logger.error(f"[Email] Fetch error: {e}")
        return []


def summarise_inbox() -> str:
    """Voice-friendly inbox summary."""
    messages = get_recent_emails(5)
    if not messages:
        return get_unread_count()

    items = "\n".join(
        f"From {m['from'].split('<')[0].strip()}: {m['subject']}"
        for m in messages
    )
    result = chat([
        {"role": "user", "content":
         f"Summarise these emails for voice delivery. "
         f"2-3 sentences max. Mention sender name and topic only.\n\n{items}"}
    ], tier=1)
    return result["content"]


def read_email(uid: str) -> str:
    """Read full email content (truncated to 3000 chars)."""
    conn = _connect()
    if not conn:
        return "Email not configured."
    try:
        conn.select("INBOX")
        _, data = conn.fetch(uid.encode(), "(RFC822)")
        for response in data:
            if isinstance(response, tuple):
                msg = email.message_from_bytes(response[1])
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            body = part.get_payload(decode=True).decode("utf-8", errors="replace")
                            break
                else:
                    body = msg.get_payload(decode=True).decode("utf-8", errors="replace")
                conn.logout()
                return body[:3000]
        conn.logout()
        return "Email not found."
    except Exception as e:
        return f"Email read error: {e}"


def draft_reply(uid: str, instruction: str) -> str:
    """Draft a reply to an email (never sends without explicit confirmation)."""
    original = read_email(uid)
    result = chat([
        {"role": "user", "content":
         f"Draft a reply to this email. Instruction: {instruction}\n\n"
         f"Original email:\n{original[:2000]}\n\n"
         f"Draft a professional reply. Do not include a subject line."}
    ], tier=2)
    return f"DRAFT (not sent):\n\n{result['content']}"
