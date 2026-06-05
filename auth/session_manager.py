"""
auth/session_manager.py
Manages Telethon user sessions (login/logout, encryption, multi-user support)
"""
import logging
import os
from telethon import TelegramClient
from telethon.sessions import StringSession
from cryptography.fernet import Fernet
from config.settings import settings
from database.mongodb import db

logger = logging.getLogger(__name__)

# Encryption key for storing sessions in DB
CIPHER_SUITE = Fernet(settings.SESSION_ENCRYPTION_KEY.encode().ljust(32)[:32].ljust(44, b'=').decode())


class SessionManager:
    """Manages Telethon sessions per user."""

    @staticmethod
    async def get_client(user_id: int) -> TelegramClient | None:
        """
        Get an active Telethon client for a user.
        Returns None if user is not logged in.
        """
        user_doc = await db.users.find_one({"_id": user_id})
        if not user_doc or not user_doc.get("telethon_session"):
            return None

        try:
            # Decrypt session string
            encrypted_session = user_doc["telethon_session"]
            decrypted = Fernet(settings.SESSION_ENCRYPTION_KEY.encode().ljust(32)[:32].ljust(44, b'=').decode()).decrypt(encrypted_session.encode())
            session_string = decrypted.decode()

            # Create client from session
            client = TelegramClient(
                StringSession(session_string),
                api_id=settings.TELEGRAM_API_ID,
                api_hash=settings.TELEGRAM_API_HASH,
            )
            await client.connect()
            return client
        except Exception as e:
            logger.error(f"Failed to restore session for user {user_id}: {e}")
            return None

    @staticmethod
    async def save_session(user_id: int, client: TelegramClient) -> None:
        """Save encrypted Telethon session to MongoDB."""
        try:
            session_string = StringSession.save(client.session)
            encrypted = Fernet(settings.SESSION_ENCRYPTION_KEY.encode().ljust(32)[:32].ljust(44, b'=').decode()).encrypt(session_string.encode()).decode()

            await db.users.update_one(
                {"_id": user_id},
                {
                    "$set": {
                        "telethon_session": encrypted,
                        "logged_in": True,
                        "logged_in_at": __import__("datetime").datetime.utcnow(),
                    }
                },
                upsert=True,
            )
            logger.info(f"✅ Session saved for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to save session for user {user_id}: {e}")
            raise

    @staticmethod
    async def delete_session(user_id: int) -> None:
        """Delete user's Telethon session (logout)."""
        try:
            await db.users.update_one(
                {"_id": user_id},
                {
                    "$set": {
                        "telethon_session": None,
                        "logged_in": False,
                        "logged_out_at": __import__("datetime").datetime.utcnow(),
                    }
                },
            )
            logger.info(f"✅ Session deleted for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to delete session for user {user_id}: {e}")
            raise

    @staticmethod
    async def is_logged_in(user_id: int) -> bool:
        """Check if user has an active session."""
        user_doc = await db.users.find_one({"_id": user_id})
        return bool(user_doc and user_doc.get("logged_in") and user_doc.get("telethon_session"))

