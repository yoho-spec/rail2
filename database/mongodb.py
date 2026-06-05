"""
database/mongodb.py
MongoDB Atlas connection + schema definitions for all collections.
Collections:
  users         — registered bot users, login state, premium flag
  sessions      — encrypted Telethon sessions per user
  chats         — user's tracked source/destination chats
  jobs          — archive/forward jobs (pending, running, done, failed)
  logs          — action log (forwarded, duplicates, errors)
  premium       — premium user list with expiry
  subscriptions — which users passed the ads gate check
"""
import logging
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import IndexModel, ASCENDING, DESCENDING
from config.settings import settings

logger = logging.getLogger(__name__)

_client: AsyncIOMotorClient = None
db = None  # Accessible as: from database.mongodb import db


async def init_db():
    global _client, db
    _client = AsyncIOMotorClient(settings.MONGODB_URI)
    db = _client[settings.MONGODB_DB_NAME]
    await _create_indexes()
    from database.schemas import create_indexes as create_schema_indexes
    await create_schema_indexes(db)
    logger.info(f"✅ MongoDB connected → {settings.MONGODB_DB_NAME}")


async def close_db():
    if _client:
        _client.close()


async def _create_indexes():
    """Create all necessary indexes."""

    # users
    await db.users.create_indexes([
        IndexModel([("user_id", ASCENDING)], unique=True),
        IndexModel([("username", ASCENDING)]),
        IndexModel([("is_premium", ASCENDING)]),
        IndexModel([("created_at", DESCENDING)]),
    ])

    # sessions
    await db.sessions.create_indexes([
        IndexModel([("user_id", ASCENDING)], unique=True),
        IndexModel([("last_active", DESCENDING)]),
    ])

    # chats
    await db.chats.create_indexes([
        IndexModel([("user_id", ASCENDING)]),
        IndexModel([("chat_id", ASCENDING)]),
        IndexModel([("user_id", ASCENDING), ("chat_id", ASCENDING)], unique=True),
    ])

    # jobs
    await db.jobs.create_indexes([
        IndexModel([("user_id", ASCENDING)]),
        IndexModel([("status", ASCENDING)]),
        IndexModel([("created_at", DESCENDING)]),
        IndexModel([("job_type", ASCENDING)]),
    ])

    # logs
    await db.logs.create_indexes([
        IndexModel([("user_id", ASCENDING)]),
        IndexModel([("action", ASCENDING)]),
        IndexModel([("created_at", DESCENDING)]),
    ])

    # premium
    await db.premium.create_indexes([
        IndexModel([("user_id", ASCENDING)], unique=True),
        IndexModel([("expires_at", ASCENDING)]),
    ])

    logger.info("✅ MongoDB indexes created")


# ── Document factories (create new docs with correct shape) ──

def new_user_doc(user_id: int, username: str = None, full_name: str = None) -> dict:
    return {
        "user_id": user_id,
        "username": username,
        "full_name": full_name,
        "is_premium": False,
        "is_admin": False,
        "is_banned": False,
        "test_mode": None,          # None | "premium" | "free"
        "login_state": "none",      # none | pending_phone | pending_otp | logged_in
        "phone_number": None,
        "subscriptions_verified": False,
        "free_restricted_used": 0,
        "default_destination": None,
        "settings": {
            "live_forward": False,
            "forward_with_timer": False,
            "timer_seconds": 2,
            "file_types": ["all"],
        },
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


def new_session_doc(user_id: int, encrypted_session: str, phone: str) -> dict:
    return {
        "user_id": user_id,
        "encrypted_session": encrypted_session,
        "phone": phone,
        "created_at": datetime.now(timezone.utc),
        "last_active": datetime.now(timezone.utc),
    }


def new_chat_doc(user_id: int, chat_id: int, chat_type: str,
                 title: str, role: str, topic_id: int = None) -> dict:
    """
    role: "source" | "destination" | "both"
    chat_type: "private" | "group" | "supergroup" | "channel"
    """
    return {
        "user_id": user_id,
        "chat_id": chat_id,
        "chat_type": chat_type,
        "title": title,
        "role": role,
        "topic_id": topic_id,
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
    }


def new_job_doc(user_id: int, job_type: str, payload: dict) -> dict:
    """
    job_type: "archive" | "forward" | "duplicate_check" | "history_forward"
    status: "pending" | "running" | "done" | "failed" | "paused"
    """
    return {
        "user_id": user_id,
        "job_type": job_type,
        "status": "pending",
        "payload": payload,
        "progress": 0,
        "error": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


def new_log_doc(user_id: int, action: str, details: dict = None) -> dict:
    """
    action: "forwarded" | "duplicate_found" | "duplicate_moved" |
            "download_restricted" | "login" | "logout" | "error" |
            "ban" | "mute" | "kick" | "admin_action"
    """
    return {
        "user_id": user_id,
        "action": action,
        "details": details or {},
        "created_at": datetime.now(timezone.utc),
    }


def new_premium_doc(user_id: int, granted_by: int, expires_at=None) -> dict:
    return {
        "user_id": user_id,
        "granted_by": granted_by,
        "expires_at": expires_at,   # None = lifetime
        "created_at": datetime.now(timezone.utc),
    }


# ── Convenience queries ──

async def get_user(user_id: int) -> dict | None:
    return await db.users.find_one({"user_id": user_id})


async def upsert_user(user_id: int, update_fields: dict):
    update_fields["updated_at"] = datetime.now(timezone.utc)
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": update_fields},
        upsert=True,
    )


async def is_premium(user_id: int) -> bool:
    user = await get_user(user_id)
    if not user:
        return False
    # Check test_mode override
    if user.get("test_mode") == "premium":
        return True
    if user.get("test_mode") == "free":
        return False
    return user.get("is_premium", False)


async def log_action(user_id: int, action: str, details: dict = None):
    doc = new_log_doc(user_id, action, details)
    await db.logs.insert_one(doc)
