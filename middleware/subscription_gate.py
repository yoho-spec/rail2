"""
middleware/subscription_gate.py

MANDATORY gate: before any command works, user must:
1. Be subscribed to all REQUIRED_CHANNELS (ads channels)
2. Have started the BACKUP_BOT

This wraps every non-admin handler.
"""
import logging
from functools import wraps
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import TelegramError
from config.settings import settings
from database.redis_client import cache_subscription_status, get_cached_subscription
from database.mongodb import get_user, upsert_user

logger = logging.getLogger(__name__)


def subscription_required(func):
    """
    Decorator — wrap any command handler with this to enforce
    the mandatory channel subscription gate.
    Admin users bypass this gate.
    """
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not user:
            return

        # Admins bypass everything
        if user.id in settings.ADMIN_USER_IDS:
            return await func(update, context)

        # Check subscriptions
        missing = await get_missing_subscriptions(user.id, context)
        if missing:
            await send_subscription_prompt(update, context, missing)
            return

        # Mark verified in DB
        await upsert_user(user.id, {"subscriptions_verified": True})
        return await func(update, context)

    return wrapper


async def get_missing_subscriptions(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> list[str]:
    """
    Returns list of channels the user has NOT joined yet.
    Uses Redis cache to avoid hammering Telegram API.
    """
    missing = []

    for channel in settings.REQUIRED_CHANNELS:
        if not channel:
            continue

        # Check cache first
        cached = await get_cached_subscription(user_id, channel)
        if cached is True:
            continue
        if cached is False:
            missing.append(channel)
            continue

        # Not in cache — ask Telegram
        try:
            member = await context.bot.get_chat_member(channel, user_id)
            is_member = member.status not in ("left", "kicked", "banned")
            await cache_subscription_status(user_id, channel, is_member)
            if not is_member:
                missing.append(channel)
        except TelegramError as e:
            logger.warning(f"Could not check membership for {channel}: {e}")
            # Fail open — don't block user if we can't check
            continue

    return missing


async def send_subscription_prompt(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    missing_channels: list[str],
):
    """Send the 'please subscribe' message with buttons."""
    buttons = []

    for channel in missing_channels:
        # Build the join URL
        if channel.startswith("-100"):
            # Private channel by ID — can't auto-link, show ID
            label = f"📢 Join Channel {channel}"
            # Admin must set invite link separately
            url = f"https://t.me/{channel.lstrip('@')}"
        else:
            clean = channel.lstrip("@")
            label = f"📢 Join @{clean}"
            url = f"https://t.me/{clean}"

        buttons.append([InlineKeyboardButton(label, url=url)])

    if settings.BACKUP_BOT_USERNAME:
        buttons.append([
            InlineKeyboardButton(
                f"🤖 Start {settings.BACKUP_BOT_USERNAME}",
                url=f"https://t.me/{settings.BACKUP_BOT_USERNAME.lstrip('@')}?start=backup"
            )
        ])

    buttons.append([
        InlineKeyboardButton("✅ I've subscribed — check again", callback_data="check_subscription")
    ])

    keyboard = InlineKeyboardMarkup(buttons)

    await update.effective_message.reply_text(
        "⚠️ *Access Required*\n\n"
        "To use this bot, you must first:\n"
        + "\n".join(f"• Join {ch}" for ch in missing_channels)
        + ("\n• Start the backup bot" if settings.BACKUP_BOT_USERNAME else "")
        + "\n\nAfter joining, tap the button below ⬇️",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


async def handle_subscription_check_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Called when user taps 'I've subscribed — check again'."""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    # Clear cache so we re-check fresh
    from database.redis_client import redis
    for channel in settings.REQUIRED_CHANNELS:
        if channel:
            await redis.delete(f"sub:{user_id}:{channel}")

    missing = await get_missing_subscriptions(user_id, context)
    if missing:
        await query.edit_message_text(
            "❌ You still haven't joined all required channels.\n\n"
            "Please join them and try again.",
            reply_markup=query.message.reply_markup,
        )
    else:
        await upsert_user(user_id, {"subscriptions_verified": True})
        await query.edit_message_text(
            "✅ *Access granted!*\n\nYou can now use all bot features. Send /start to begin.",
            parse_mode="Markdown",
        )
