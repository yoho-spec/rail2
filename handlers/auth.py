"""
handlers/auth.py

Conversation-based login flow + logout + /mychats.

States:
  PHONE_NUMBER  — waiting for the user to send their phone number
  OTP_CODE      — waiting for the OTP sent by Telegram
  PASSWORD_2FA  — waiting for the 2FA cloud password (if enabled)

Entry point: /login
Cancel:       /cancel  (works in any state)
"""
import logging
import re
from datetime import datetime, timezone

from telegram import Update, ReplyKeyboardRemove, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from auth.login_flow import start_login, verify_otp, verify_2fa
from auth.session_manager import SessionManager
from database.mongodb import upsert_user, log_action, db
from middleware.subscription_gate import subscription_required

logger = logging.getLogger(__name__)

# ── Conversation states ───────────────────────────────────────────────────────
PHONE_NUMBER = 0
OTP_CODE = 1
PASSWORD_2FA = 2

# ── Helpers ───────────────────────────────────────────────────────────────────

_PHONE_RE = re.compile(r"^\+?[1-9]\d{6,14}$")


def _fmt_dialog(index: int, dialog) -> str:
    """Format a single Telethon dialog for display."""
    name = getattr(dialog, "name", None) or "Unnamed"
    entity = dialog.entity
    entity_type = type(entity).__name__

    type_icon = {
        "User": "👤",
        "Chat": "👥",
        "Channel": "📢",
    }.get(entity_type, "💬")

    chat_id = getattr(entity, "id", "?")
    unread = dialog.unread_count
    unread_str = f"  •  {unread} unread" if unread else ""

    return f"{index}. {type_icon} *{name}*  (`{chat_id}`){unread_str}"


# ── /login — entry point ──────────────────────────────────────────────────────

async def login_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the login conversation."""
    user = update.effective_user

    if await SessionManager.is_logged_in(user.id):
        await update.message.reply_text(
            "✅ You are already logged in.\n\n"
            "Use /mychats to list your chats or /logout to disconnect."
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "🔑 *Account Login*\n\n"
        "Send your phone number in international format:\n"
        "`+1 650 555 0100`\n\n"
        "Your number is only used to authenticate with Telegram's servers "
        "and is stored encrypted. Send /cancel to abort.",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return PHONE_NUMBER


# ── State: PHONE_NUMBER ───────────────────────────────────────────────────────

async def phone_number_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Validate phone number and send OTP."""
    phone = update.message.text.strip().replace(" ", "").replace("-", "")

    if not _PHONE_RE.match(phone):
        await update.message.reply_text(
            "❌ That doesn't look like a valid phone number.\n\n"
            "Please send it in international format, e.g. `+16505550100`\n"
            "or /cancel to abort.",
            parse_mode="Markdown",
        )
        return PHONE_NUMBER

    # Normalise — ensure leading +
    if not phone.startswith("+"):
        phone = "+" + phone

    await update.message.reply_text(
        f"📱 Sending OTP to `{phone}`…",
        parse_mode="Markdown",
    )

    result = await start_login(update.effective_user.id, phone)

    if not result["ok"]:
        error = result.get("error", "unknown")
        if error == "invalid_phone":
            msg = "❌ That phone number is not valid on Telegram. Please check and try again."
        elif error == "phone_banned":
            msg = "❌ This phone number has been banned from Telegram."
        elif error == "flood_wait":
            secs = result.get("seconds", 60)
            msg = f"⏳ Too many attempts. Please wait {secs} seconds and try again."
        else:
            msg = f"❌ Something went wrong (`{error}`). Please try again later."

        await update.message.reply_text(msg, parse_mode="Markdown")
        return ConversationHandler.END

    await update.message.reply_text(
        "✅ OTP sent!\n\n"
        "Check your Telegram app (or SMS) for the code and send it here.\n"
        "Send /cancel to abort.",
    )
    return OTP_CODE


# ── State: OTP_CODE ───────────────────────────────────────────────────────────

async def otp_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive OTP, verify it, handle 2FA redirect."""
    otp = update.message.text.strip().replace(" ", "").replace("-", "")
    user_id = update.effective_user.id

    result = await verify_otp(user_id, otp)

    if not result["ok"]:
        error = result.get("error", "unknown")
        if error == "invalid_code":
            await update.message.reply_text(
                "❌ That code is incorrect. Please try again or /cancel."
            )
            return OTP_CODE
        elif error == "code_expired":
            await update.message.reply_text(
                "⏰ The code has expired. Please use /login to start over."
            )
            return ConversationHandler.END
        elif error == "flood_wait":
            secs = result.get("seconds", 60)
            await update.message.reply_text(
                f"⏳ Too many attempts. Please wait {secs} seconds, then /login again."
            )
            return ConversationHandler.END
        elif error == "no_pending_session":
            await update.message.reply_text(
                "⚠️ Session expired. Please use /login to start over."
            )
            return ConversationHandler.END
        else:
            await update.message.reply_text(
                f"❌ Verification failed (`{error}`). Please use /login to try again.",
                parse_mode="Markdown",
            )
            return ConversationHandler.END

    if result.get("needs_2fa"):
        await update.message.reply_text(
            "🔐 *Two-Factor Authentication*\n\n"
            "Your account has 2FA enabled. Please send your cloud password.\n"
            "Send /cancel to abort.",
            parse_mode="Markdown",
        )
        return PASSWORD_2FA

    # Fully logged in
    await log_action(user_id, "login", {"method": "otp"})
    await update.message.reply_text(
        "✅ *Logged in successfully!*\n\n"
        "You can now use /mychats to see your chats.",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


# ── State: PASSWORD_2FA ───────────────────────────────────────────────────────

async def password_2fa_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive 2FA password and complete login."""
    password = update.message.text.strip()
    user_id = update.effective_user.id

    result = await verify_2fa(user_id, password)

    if not result["ok"]:
        error = result.get("error", "unknown")
        if error == "wrong_password":
            await update.message.reply_text(
                "❌ Incorrect password. Please try again or /cancel."
            )
            return PASSWORD_2FA
        elif error == "flood_wait":
            secs = result.get("seconds", 60)
            await update.message.reply_text(
                f"⏳ Too many attempts. Please wait {secs} seconds, then /login again."
            )
            return ConversationHandler.END
        elif error == "no_pending_session":
            await update.message.reply_text(
                "⚠️ Session expired. Please use /login to start over."
            )
            return ConversationHandler.END
        else:
            await update.message.reply_text(
                f"❌ 2FA failed (`{error}`). Please use /login to try again.",
                parse_mode="Markdown",
            )
            return ConversationHandler.END

    await log_action(user_id, "login", {"method": "2fa"})
    await update.message.reply_text(
        "✅ *Logged in successfully!*\n\n"
        "You can now use /mychats to see your chats.",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


# ── /cancel ───────────────────────────────────────────────────────────────────

async def cancel_login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the login conversation at any state."""
    user_id = update.effective_user.id

    # Clean up any pending Telethon client
    from auth.login_flow import _cleanup_pending
    await _cleanup_pending(user_id)

    await update.message.reply_text(
        "❌ Login cancelled.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


# ── /logout ───────────────────────────────────────────────────────────────────

async def logout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Disconnect the user's Telethon session."""
    user_id = update.effective_user.id

    if not await SessionManager.is_logged_in(user_id):
        await update.message.reply_text("ℹ️ You are not currently logged in.")
        return

    # Attempt a clean Telethon logout (revokes the session server-side)
    client = await SessionManager.get_client(user_id)
    if client:
        try:
            await client.log_out()
        except Exception as e:
            logger.warning(f"Telethon log_out failed for user {user_id}: {e}")
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

    await SessionManager.delete_session(user_id)
    await upsert_user(user_id, {"login_state": "none", "phone_number": None})
    await log_action(user_id, "logout")

    await update.message.reply_text(
        "✅ *Logged out successfully.*\n\n"
        "Your session has been removed. Use /login to connect again.",
        parse_mode="Markdown",
    )


# ── /mychats ──────────────────────────────────────────────────────────────────

@subscription_required
async def mychats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Fetch the user's Telegram dialogs via their Telethon session,
    save them to the DB, and display a formatted list.
    """
    user_id = update.effective_user.id

    if not await SessionManager.is_logged_in(user_id):
        await update.message.reply_text(
            "🔑 You need to log in first.\n\nUse /login to connect your Telegram account."
        )
        return

    await update.message.reply_text("⏳ Fetching your chats…")

    client = await SessionManager.get_client(user_id)
    if not client:
        await update.message.reply_text(
            "⚠️ Could not restore your session. Please /login again."
        )
        return

    try:
        dialogs = await client.get_dialogs(limit=50)
    except Exception as e:
        logger.error(f"get_dialogs failed for user {user_id}: {e}")
        await update.message.reply_text(
            "❌ Failed to fetch chats. Please try again or /login again."
        )
        await client.disconnect()
        return

    if not dialogs:
        await update.message.reply_text("📭 No chats found.")
        await client.disconnect()
        return

    # Persist dialogs to the chats collection
    from database.mongodb import new_chat_doc
    from telethon.tl.types import User, Chat, Channel

    saved_count = 0
    for dialog in dialogs:
        entity = dialog.entity
        if isinstance(entity, User):
            chat_type = "private"
            title = dialog.name or f"User {entity.id}"
        elif isinstance(entity, Chat):
            chat_type = "group"
            title = getattr(entity, "title", dialog.name) or f"Group {entity.id}"
        elif isinstance(entity, Channel):
            chat_type = "channel" if getattr(entity, "broadcast", False) else "supergroup"
            title = getattr(entity, "title", dialog.name) or f"Channel {entity.id}"
        else:
            continue

        chat_doc = new_chat_doc(
            user_id=user_id,
            chat_id=entity.id,
            chat_type=chat_type,
            title=title,
            role="source",
        )
        try:
            await db.chats.update_one(
                {"user_id": user_id, "chat_id": entity.id},
                {"$set": chat_doc},
                upsert=True,
            )
            saved_count += 1
        except Exception as e:
            logger.warning(f"Could not upsert chat {entity.id} for user {user_id}: {e}")

    await client.disconnect()

    # Build display — split into chunks to stay under Telegram's 4096-char limit
    lines = [f"💬 *Your Chats* ({len(dialogs)} shown, {saved_count} saved)\n"]
    for i, dialog in enumerate(dialogs, start=1):
        lines.append(_fmt_dialog(i, dialog))

    # Send in chunks of 30 dialogs
    chunk_size = 30
    chunks = [lines[:1] + lines[1 + i: 1 + i + chunk_size]
              for i in range(0, len(lines) - 1, chunk_size)]

    for chunk in chunks:
        text = "\n".join(chunk)
        # Telegram message limit guard
        if len(text) > 4000:
            text = text[:3990] + "\n…"
        await update.message.reply_text(text, parse_mode="Markdown")


# ── ConversationHandler ───────────────────────────────────────────────────────

login_conversation = ConversationHandler(
    entry_points=[CommandHandler("login", login_handler)],
    states={
        PHONE_NUMBER: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, phone_number_handler),
        ],
        OTP_CODE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, otp_handler),
        ],
        PASSWORD_2FA: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, password_2fa_handler),
        ],
    },
    fallbacks=[CommandHandler("cancel", cancel_login)],
    # Allow the conversation to persist across bot restarts (no persistence configured yet)
    allow_reentry=True,
)
