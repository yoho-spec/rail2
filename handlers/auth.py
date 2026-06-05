"""
handlers/auth.py
Login, logout, and /mychats handlers (Part 2)
"""
import logging
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters
from middleware.subscription_gate import subscription_required
from auth.session_manager import SessionManager
from auth.login_flow import start_login, verify_otp, verify_2fa
from database.mongodb import db

logger = logging.getLogger(__name__)

# Conversation states
PHONE_NUMBER, OTP_CODE, PASSWORD_2FA = range(3)


@subscription_required
async def login_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start login flow — ask for phone number."""
    user_id = update.effective_user.id

    # Check if already logged in
    if await SessionManager.is_logged_in(user_id):
        await update.message.reply_text(
            "✅ You're already logged in. Use /logout to disconnect."
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "📱 Enter your Telegram phone number (with country code, e.g., +1234567890):"
    )
    return PHONE_NUMBER


async def phone_number_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive phone number and send OTP."""
    user_id = update.effective_user.id
    phone_number = update.message.text.strip()

    if not phone_number.startswith("+"):
        await update.message.reply_text("❌ Phone must start with +. Try again:")
        return PHONE_NUMBER

    # Start login
    result = await start_login(user_id, phone_number)

    if result["status"] == "error":
        await update.message.reply_text(f"❌ {result['message']}")
        return ConversationHandler.END

    await update.message.reply_text(result["message"])
    return OTP_CODE


async def otp_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive OTP code."""
    user_id = update.effective_user.id
    otp_code = update.message.text.strip()

    result = await verify_otp(user_id, otp_code)

    if result["status"] == "password_needed":
        await update.message.reply_text(result["message"])
        return PASSWORD_2FA
    elif result["status"] == "error":
        await update.message.reply_text(f"❌ {result['message']}")
        return ConversationHandler.END
    else:  # success
        await update.message.reply_text(result["message"])
        return ConversationHandler.END


async def password_2fa_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive 2FA password."""
    user_id = update.effective_user.id
    password = update.message.text.strip()

    result = await verify_2fa(user_id, password)

    if result["status"] == "error":
        await update.message.reply_text(f"❌ {result['message']}")
        return ConversationHandler.END
    else:
        await update.message.reply_text(result["message"])
        return ConversationHandler.END


async def cancel_login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel login flow."""
    await update.message.reply_text("❌ Login cancelled.")
    return ConversationHandler.END


@subscription_required
async def logout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Logout — delete session."""
    user_id = update.effective_user.id

    if not await SessionManager.is_logged_in(user_id):
        await update.message.reply_text("❌ You're not logged in.")
        return

    await SessionManager.delete_session(user_id)
    await update.message.reply_text("✅ Logged out successfully.")


@subscription_required
async def mychats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List user's chats with multi-select UI."""
    user_id = update.effective_user.id

    if not await SessionManager.is_logged_in(user_id):
        await update.message.reply_text(
            "❌ You must be logged in. Use /login first."
        )
        return

    try:
        # Get user's client
        client = await SessionManager.get_client(user_id)
        if not client:
            await update.message.reply_text("❌ Session error. Try /login again.")
            return

        # Fetch dialogs (chats)
        dialogs = await client.get_dialogs()

        if not dialogs:
            await update.message.reply_text("❌ No chats found.")
            return

        # Store chats in DB for later reference
        chat_list = []
        for dialog in dialogs[:50]:  # Limit to 50 for now
            chat_id = dialog.id
            chat_name = dialog.name or "Unnamed"
            chat_type = "Channel" if dialog.is_channel else "Group" if dialog.is_group else "Private"

            chat_list.append({
                "id": chat_id,
                "name": chat_name,
                "type": chat_type,
                "is_channel": dialog.is_channel,
                "is_group": dialog.is_group,
            })

        # Save to DB
        await db.users.update_one(
            {"_id": user_id},
            {"$set": {"chats": chat_list}},
        )

        # Format message
        message = "📋 **Your Chats:**\n\n"
        for i, chat in enumerate(chat_list, 1):
            message += f"{i}. {chat['name']} ({chat['type']}) - ID: `{chat['id']}`\n"

        message += "\n💡 Use /setdest to select destination chats for archiving."

        await update.message.reply_text(message, parse_mode="Markdown")

        await client.disconnect()

    except Exception as e:
        logger.error(f"Error fetching chats for user {user_id}: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")


# Conversation handler for login flow
login_conversation = ConversationHandler(
    entry_points=[CommandHandler("login", login_handler)],
    states={
        PHONE_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, phone_number_handler)],
        OTP_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, otp_handler)],
        PASSWORD_2FA: [MessageHandler(filters.TEXT & ~filters.COMMAND, password_2fa_handler)],
    },
    fallbacks=[CommandHandler("cancel", cancel_login)],
)

