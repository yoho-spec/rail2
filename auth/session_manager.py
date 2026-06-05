"""
auth/session_manager.py

Manages encrypted Telethon sessions stored in MongoDB.

Sessions are encrypted with Fernet (symmetric AES-128-CBC + HMAC-SHA256)
using SESSION_ENCRYPTION_KEY from settings. The key must be a valid
Fernet key (32 url-safe base64-encoded bytes).

Usage:
    from auth.session_manager import SessionManager
    client = await SessionManager.get_client(user_id)
"""
import logging
import base64
from datetime import datetime, timezone
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from telethon import TelegramClient
from telethon.sessions import StringSession

from config.settings import settings
from database.mongodb import db

logger = logging.getLogger(__name__)


def _get_fernet() -> Fernet:
    """
    Build a Fernet instance from SESSION_ENCRYPTION_KEY.

    The env var may be supplied as:
      - A raw 32-byte hex string  (64 hex chars)  → we base64url-encode it
      - A valid Fernet key already in base64url format (44 chars ending with '=')
    """
    key_raw = settings.SESSION_ENCRYPTION_KEY.strip()

    # If it looks like a hex string, convert to Fernet-compatible base64url key
    if len(key_raw) == 64 and all(c in "0123456789abcdefABCDEF" for c in key_raw):
        key_bytes = bytes.fromhex(key_raw)
        key = base64.urlsafe_b64encode(key_bytes)
    else:
        key = key_raw.encode()

    return Fernet(key)


class SessionManager:
    """Static helper class for Telethon session lifecycle."""

    # ── Retrieve ──────────────────────────────────────────────────────────

    @staticmethod
    async def get_client(user_id: int) -> Optional[TelegramClient]:
        """
        Load the encrypted session from MongoDB, decrypt it, and return
        a connected TelegramClient.  Returns None if no session exists.
        """
        doc = await db.sessions.find_one({"user_id": user_id})
        if not doc:
            return None

        try:
            fernet = _get_fernet()
            decrypted = fernet.decrypt(doc["encrypted_session"].encode())
            session_string = decrypted.decode()
        except (InvalidToken, Exception) as e:
            logger.error(f"Failed to decrypt session for user {user_id}: {e}")
            return None

        client = TelegramClient(
            StringSession(session_string),
            settings.TELEGRAM_API_ID,
            settings.TELEGRAM_API_HASH,
        )

        try:
            await client.connect()
            if not await client.is_user_authorized():
                logger.warning(f"Session for user {user_id} is no longer authorized")
                await client.disconnect()
                return None
        except Exception as e:
            logger.error(f"Could not connect Telethon client for user {user_id}: {e}")
            try:
                await client.disconnect()
            except Exception:
                pass
            return None

        # Refresh last_active timestamp
        await db.sessions.update_one(
            {"user_id": user_id},
            {"$set": {"last_active": datetime.now(timezone.utc)}},
        )

        return client

    # ── Persist ───────────────────────────────────────────────────────────

    @staticmethod
    async def save_session(user_id: int, client: TelegramClient, phone: str = "") -> None:
        """
        Serialize the Telethon session string, encrypt it with Fernet,
        and upsert into MongoDB.
        """
        session_string = client.session.save()

        fernet = _get_fernet()
        encrypted = fernet.encrypt(session_string.encode()).decode()

        now = datetime.now(timezone.utc)
        await db.sessions.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "user_id": user_id,
                    "encrypted_session": encrypted,
                    "phone": phone,
                    "last_active": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
        logger.info(f"Session saved for user {user_id}")

    # ── Remove ────────────────────────────────────────────────────────────

    @staticmethod
    async def delete_session(user_id: int) -> None:
        """Delete the stored session (logout)."""
        result = await db.sessions.delete_one({"user_id": user_id})
        if result.deleted_count:
            logger.info(f"Session deleted for user {user_id}")
        else:
            logger.debug(f"No session found to delete for user {user_id}")

    # ── Check ─────────────────────────────────────────────────────────────

    @staticmethod
    async def is_logged_in(user_id: int) -> bool:
        """
        Quick check — returns True if a session document exists in MongoDB.
        Does NOT verify the session is still valid with Telegram.
        """
        doc = await db.sessions.find_one({"user_id": user_id}, {"_id": 1})
        return doc is not None
