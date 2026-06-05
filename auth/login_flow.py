"""
auth/login_flow.py

Manages the multi-step Telethon login flow:
  1. start_login()   — send OTP to phone number
  2. verify_otp()    — submit OTP code (may trigger 2FA)
  3. verify_2fa()    — submit 2FA password

Temporary TelegramClient instances are kept in _pending_clients while the
user is mid-flow.  They are cleaned up on success, failure, or timeout.

The ConversationHandler in handlers/auth.py drives the state machine;
these functions contain only the Telethon / business logic.
"""
import asyncio
import logging
from typing import Optional

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    PasswordHashInvalidError,
    FloodWaitError,
    PhoneNumberInvalidError,
    PhoneNumberBannedError,
)

from config.settings import settings
from auth.session_manager import SessionManager
from database.mongodb import upsert_user

logger = logging.getLogger(__name__)

# ── In-memory store for clients that are mid-login ────────────────────────────
# { user_id: {"client": TelegramClient, "phone": str, "phone_code_hash": str} }
_pending_clients: dict[int, dict] = {}

# How long (seconds) to keep a pending client alive before auto-cleanup
_PENDING_TTL = 600  # 10 minutes


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _cleanup_pending(user_id: int) -> None:
    """Disconnect and remove a pending client."""
    entry = _pending_clients.pop(user_id, None)
    if entry:
        try:
            await entry["client"].disconnect()
        except Exception:
            pass
        logger.debug(f"Cleaned up pending client for user {user_id}")


async def _schedule_cleanup(user_id: int) -> None:
    """Auto-cleanup after TTL so we don't leak connections."""
    await asyncio.sleep(_PENDING_TTL)
    if user_id in _pending_clients:
        logger.info(f"Pending client TTL expired for user {user_id}, cleaning up")
        await _cleanup_pending(user_id)


# ── Public API ────────────────────────────────────────────────────────────────

async def start_login(user_id: int, phone_number: str) -> dict:
    """
    Create a temporary TelegramClient and send an OTP to phone_number.

    Returns:
        {"ok": True}                          on success
        {"ok": False, "error": "<message>"}   on failure
    """
    # Clean up any previous pending session for this user
    if user_id in _pending_clients:
        await _cleanup_pending(user_id)

    client = TelegramClient(
        StringSession(),
        settings.TELEGRAM_API_ID,
        settings.TELEGRAM_API_HASH,
    )

    try:
        await client.connect()
        result = await client.send_code_request(phone_number)
    except PhoneNumberInvalidError:
        await client.disconnect()
        return {"ok": False, "error": "invalid_phone"}
    except PhoneNumberBannedError:
        await client.disconnect()
        return {"ok": False, "error": "phone_banned"}
    except FloodWaitError as e:
        await client.disconnect()
        return {"ok": False, "error": "flood_wait", "seconds": e.seconds}
    except Exception as e:
        await client.disconnect()
        logger.error(f"start_login error for user {user_id}: {e}")
        return {"ok": False, "error": "unknown", "detail": str(e)}

    _pending_clients[user_id] = {
        "client": client,
        "phone": phone_number,
        "phone_code_hash": result.phone_code_hash,
    }

    # Schedule auto-cleanup
    asyncio.create_task(_schedule_cleanup(user_id))

    await upsert_user(user_id, {"login_state": "pending_otp", "phone_number": phone_number})
    logger.info(f"OTP sent to {phone_number} for user {user_id}")
    return {"ok": True}


async def verify_otp(user_id: int, otp_code: str) -> dict:
    """
    Submit the OTP code received via SMS / Telegram.

    Returns:
        {"ok": True, "needs_2fa": False}   — logged in successfully
        {"ok": True, "needs_2fa": True}    — 2FA password required next
        {"ok": False, "error": "<key>"}    — failure
    """
    entry = _pending_clients.get(user_id)
    if not entry:
        return {"ok": False, "error": "no_pending_session"}

    client: TelegramClient = entry["client"]
    phone: str = entry["phone"]
    phone_code_hash: str = entry["phone_code_hash"]

    try:
        await client.sign_in(
            phone=phone,
            code=otp_code,
            phone_code_hash=phone_code_hash,
        )
    except SessionPasswordNeededError:
        # 2FA is enabled — keep the client alive for the next step
        logger.info(f"2FA required for user {user_id}")
        return {"ok": True, "needs_2fa": True}
    except PhoneCodeInvalidError:
        return {"ok": False, "error": "invalid_code"}
    except PhoneCodeExpiredError:
        await _cleanup_pending(user_id)
        return {"ok": False, "error": "code_expired"}
    except FloodWaitError as e:
        return {"ok": False, "error": "flood_wait", "seconds": e.seconds}
    except Exception as e:
        await _cleanup_pending(user_id)
        logger.error(f"verify_otp error for user {user_id}: {e}")
        return {"ok": False, "error": "unknown", "detail": str(e)}

    # Success — persist session
    await SessionManager.save_session(user_id, client, phone=phone)
    await upsert_user(user_id, {"login_state": "logged_in"})
    await _cleanup_pending(user_id)
    logger.info(f"User {user_id} logged in successfully (no 2FA)")
    return {"ok": True, "needs_2fa": False}


async def verify_2fa(user_id: int, password: str) -> dict:
    """
    Complete 2FA verification with the user's cloud password.

    Returns:
        {"ok": True}                        — logged in successfully
        {"ok": False, "error": "<key>"}     — failure
    """
    entry = _pending_clients.get(user_id)
    if not entry:
        return {"ok": False, "error": "no_pending_session"}

    client: TelegramClient = entry["client"]
    phone: str = entry["phone"]

    try:
        await client.sign_in(password=password)
    except PasswordHashInvalidError:
        return {"ok": False, "error": "wrong_password"}
    except FloodWaitError as e:
        return {"ok": False, "error": "flood_wait", "seconds": e.seconds}
    except Exception as e:
        await _cleanup_pending(user_id)
        logger.error(f"verify_2fa error for user {user_id}: {e}")
        return {"ok": False, "error": "unknown", "detail": str(e)}

    # Success — persist session
    await SessionManager.save_session(user_id, client, phone=phone)
    await upsert_user(user_id, {"login_state": "logged_in"})
    await _cleanup_pending(user_id)
    logger.info(f"User {user_id} logged in successfully (2FA)")
    return {"ok": True}
