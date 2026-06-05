"""
handlers/start.py
/start and /help commands
"""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database.mongodb import get_user, upsert_user, new_user_doc
from middleware.subscription_gate import subscription_required

logger = logging.getLogger(__name__)


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    # Register / update user in DB
    existing = await get_user(user.id)
    if not existing:
        doc = new_user_doc(
            user_id=user.id,
            username=user.username,
            full_name=user.full_name,
        )
        from database.mongodb import db
        await db.users.insert_one(doc)
        logger.info(f"New user registered: {user.id} (@{user.username})")
    else:
        await upsert_user(user.id, {
            "username": user.username,
            "full_name": user.full_name,
        })

    # Check subscriptions gate
    from middleware.subscription_gate import get_missing_subscriptions, send_subscription_prompt
    missing = await get_missing_subscriptions(user.id, context)
    if missing:
        await send_subscription_prompt(update, context, missing)
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📦 Archive Setup", callback_data="menu_archive"),
            InlineKeyboardButton("🔍 Duplicates", callback_data="menu_duplicates"),
        ],
        [
            InlineKeyboardButton("👥 Group Tools", callback_data="menu_group"),
            InlineKeyboardButton("⭐ Premium", callback_data="menu_premium"),
        ],
        [
            InlineKeyboardButton("🔑 Login Account", callback_data="menu_login"),
            InlineKeyboardButton("❓ Help", callback_data="menu_help"),
        ],
    ])

    name = user.first_name or "there"
    await update.message.reply_text(
        f"👋 *Welcome, {name}!*\n\n"
        "I'm the *Archiver Bot* — your all-in-one Telegram archive, "
        "duplicate cleaner, and group manager.\n\n"
        "🔹 *What I can do:*\n"
        "• Forward & archive messages from any chat\n"
        "• Remove duplicate files across channels\n"
        "• Accept join requests with custom questions\n"
        "• Full group moderation toolkit\n"
        "• Search your Telegram history\n"
        "• Translate & transcribe audio\n\n"
        "Tap a button below or send /help for all commands.",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


@subscription_required
async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 *Archiver Bot — All Commands*\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "🔑 *Account*\n"
        "/login — Connect your Telegram account\n"
        "/logout — Disconnect your account\n"
        "/mychats — List all your chats\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "📦 *Archiving*\n"
        "/archive — Set up a new archive job\n"
        "/setdest — Set your default destination\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "🔍 *Duplicates*\n"
        "/duplicates — Run duplicate checker\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "👥 *Group Tools*\n"
        "/joinsetup — Set up join Q&A\n"
        "/ban — Ban a user\n"
        "/mute — Mute a user\n"
        "/kick — Kick a user\n"
        "/banlist — Manage auto-ban list\n"
        "/welcome — Toggle welcome messages\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "🤖 *AI Tools*\n"
        "/search — Search your Telegram history\n"
        "/transcribe — Transcribe audio\n"
        "/translate — AI translation\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "⭐ *Premium*\n"
        "/premium — Check your premium status\n\n"

        "_Some features require logging in with your Telegram account._\n"
        "_Premium features: cryptographic hash check, unlimited restricted downloads._"
    )

    await update.message.reply_text(help_text, parse_mode="Markdown")
