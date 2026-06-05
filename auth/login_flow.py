"""
auth/login_flow.py
Handles phone login flow with OTP verification
"""
import logging
import asyncio
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from config.settings import settings
from database.mongodb import db
from database.redis_client import redis
from auth.session_manager import SessionManager

logger = logging.getLogger(__name__)

# Temporary clients during login (stored in Redis with TTL)
LOGIN_TIMEOUT = 300  # 5 minutes


async def start_login(user_id: int, phone_number: str) -> dict:
    """
    Start login flow: create temp client, send OTP.
    Returns: {"status": "otp_sent", "phone_hash": "..."}
    """
    try:
        # Create temporary client
        temp_client = TelegramClient(
            f"temp_session_{user_id}",
            api_id=settings.TELEGRAM_API_ID,
            api_hash=settings.TELEGRAM_API_HASH,
        )
        await temp_client.connect()

        # Request OTP
        result = await temp_client.send_code_request(phone_number)
        phone_code_hash = result.phone_code_hash

        # Store temp client in Redis (serialized)
        await redis.setex(
            f"login_temp:{user_id}",
            LOGIN_TIMEOUT,
            phone_code_hash,  # Just store the hash; client is in memory
        )

        # Also store the client object in a module-level dict (not ideal but works for small scale)
        # In production, use a proper session store
        _temp_clients[user_id] = temp_client

        logger.info(f"✅ OTP sent to {phone_number} for user {user_id}")
        return {
            "status": "otp_sent",
            "phone_hash": phone_code_hash,
            "message": f"OTP sent to {phone_number}. Reply with /verify <code>",
        }
    except Exception as e:
        logger.error(f"Login start failed for user {user_id}: {e}")
        return {"status": "error", "message": str(e)}


async def verify_otp(user_id: int, otp_code: str, password: str = None) -> dict:
    """
    Verify OTP and complete login.
    Returns: {"status": "success"} or {"status": "password_needed"} or {"status": "error"}
    """
    try:
        # Get temp client
        temp_client = _temp_clients.get(user_id)
        if not temp_client:
            return {"status": "error", "message": "Login session expired. Start over with /login"}

        # Sign in with OTP
        try:
            await temp_client.sign_in(phone_number=None, code=otp_code)
        except SessionPasswordNeededError:
            # 2FA enabled
            return {
                "status": "password_needed",
                "message": "2FA enabled. Reply with /verify2fa <password>",
            }

        # Success — save session
        await SessionManager.save_session(user_id, temp_client)

        # Get user info
        me = await temp_client.get_me()
        await db.users.update_one(
            {"_id": user_id},
            {
                "$set": {
                    "telegram_name": me.first_name,
                    "telegram_username": me.username or "",
                    "telegram_phone": me.phone,
                }
            },
        )

        # Clean up
        del _temp_clients[user_id]
        await redis.delete(f"login_temp:{user_id}")

        logger.info(f"✅ User {user_id} logged in successfully")
        return {
            "status": "success",
            "message": f"✅ Logged in as {me.first_name}. Use /mychats to see your chats.",
        }

    except Exception as e:
        logger.error(f"OTP verification failed for user {user_id}: {e}")
        return {"status": "error", "message": str(e)}


async def verify_2fa(user_id: int, password: str) -> dict:
    """Verify 2FA password."""
    try:
        temp_client = _temp_clients.get(user_id)
        if not temp_client:
            return {"status": "error", "message": "Login session expired."}

        await temp_client.sign_in(password=password)

        # Save session
        await SessionManager.save_session(user_id, temp_client)

        me = await temp_client.get_me()
        await db.users.update_one(
            {"_id": user_id},
            {
                "$set": {
                    "telegram_name": me.first_name,
                    "telegram_username": me.username or "",
                    "telegram_phone": me.phone,
                }
            },
        )

        del _temp_clients[user_id]
        await redis.delete(f"login_temp:{user_id}")

        logger.info(f"✅ User {user_id} passed 2FA")
        return {
            "status": "success",
            "message": f"✅ Logged in as {me.first_name}. Use /mychats to see your chats.",
        }

    except Exception as e:
        logger.error(f"2FA verification failed for user {user_id}: {e}")
        return {"status": "error", "message": str(e)}


# Module-level dict to store temp clients during login
# In production, use Redis or a proper session store
_temp_clients = {}

