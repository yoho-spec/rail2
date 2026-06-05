"""
handlers/admin.py
Admin-only commands:
  /admintest  — show bot status + DB/Redis health
  /addpremium — manually grant premium to a user
  /testmode   — override bot behavior for testing (simulate premium/free)
"""
import logging
from datetime import datetime, timezone
from telegram import Update
from telegram.ext import ContextTypes
from config.settings import settings
from database.mongodb import db, get_user, upsert_user, new_premium_doc, log_action
from database.redis_client import redis, get_queue_length

logger = logging.getLogger(__name__)


def admin_only(func):
    """Decorator: only allows ADMIN_USER_IDS through."""
    from functools import wraps
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not user or user.id not in settings.ADMIN_USER_IDS:
            await update.message.reply_text("⛔ Admin only.")
            return
        return await func(update, context)
    return wrapper


@admin_only
async def admin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /admintest — System health check.
    Shows: DB status, Redis status, queue lengths, user count, job count.
    """
    lines = ["🛠 *Admin Dashboard*\n"]

    # DB health
    try:
        await db.command("ping")
        lines.append("✅ MongoDB: connected")
    except Exception as e:
        lines.append(f"❌ MongoDB: {e}")

    # Redis health
    try:
        await redis.ping()
        lines.append("✅ Redis: connected")
    except Exception as e:
        lines.append(f"❌ Redis: {e}")

    # Counts
    user_count = await db.users.count_documents({})
    premium_count = await db.users.count_documents({"is_premium": True})
    job_count = await db.jobs.count_documents({})
    pending_jobs = await db.jobs.count_documents({"status": "pending"})
    running_jobs = await db.jobs.count_documents({"status": "running"})

    lines.append(f"\n👤 Users: {user_count} ({premium_count} premium)")
    lines.append(f"📋 Jobs: {job_count} total | {pending_jobs} pending | {running_jobs} running")

    # Queue lengths
    for q in ["archive", "forward", "duplicate"]:
        length = await get_queue_length(q)
        lines.append(f"📬 Queue [{q}]: {length}")

    lines.append(f"\n🕒 Server time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(f"🌍 Environment: {settings.ENVIRONMENT}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@admin_only
async def add_premium_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /addpremium @username  OR  /addpremium <user_id>

    Grants premium to a user. The user gets a notification message.
    """
    if not context.args:
        await update.message.reply_text(
            "Usage:\n"
            "/addpremium @username\n"
            "/addpremium 123456789"
        )
        return

    target = context.args[0].lstrip("@")

    # Resolve user — try by username first, then ID
    target_user = None
    target_id = None

    if target.isdigit():
        target_id = int(target)
        target_user = await get_user(target_id)
    else:
        target_user = await db.users.find_one({"username": target})
        if target_user:
            target_id = target_user["user_id"]

    if not target_user or not target_id:
        await update.message.reply_text(
            f"❌ User `{target}` not found in database.\n"
            "They must have started the bot at least once.",
            parse_mode="Markdown",
        )
        return

    # Grant premium
    await upsert_user(target_id, {"is_premium": True})

    # Upsert premium collection
    await db.premium.update_one(
        {"user_id": target_id},
        {"$set": new_premium_doc(target_id, update.effective_user.id)},
        upsert=True,
    )

    await log_action(
        update.effective_user.id,
        "grant_premium",
        {"target_user_id": target_id, "target_username": target},
    )

    # Notify the user
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=(
                "🌟 *Premium Activated!*\n\n"
                "A premium subscription has been sent to you by the admin.\n\n"
                "You now have access to:\n"
                "• Cryptographic hash duplicate checking\n"
                "• Unlimited restricted content downloads\n"
                "• Priority job queue\n\n"
                "Thank you for using Archiver Bot! ⭐"
            ),
            parse_mode="Markdown",
        )
        notify_status = "✅ User notified"
    except Exception as e:
        notify_status = f"⚠️ Could not notify user: {e}"

    await update.message.reply_text(
        f"✅ Premium granted to `{target}`\n{notify_status}",
        parse_mode="Markdown",
    )


@admin_only
async def test_mode_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /testmode premium  — admin acts as premium user
    /testmode free     — admin acts as free user
    /testmode reset    — admin back to real admin status
    /testmode status   — show current mode

    This affects how the bot treats the admin's user_id in all checks.
    """
    if not context.args:
        await update.message.reply_text(
            "Usage:\n"
            "/testmode premium — simulate premium user\n"
            "/testmode free    — simulate free user\n"
            "/testmode reset   — back to admin\n"
            "/testmode status  — show current mode"
        )
        return

    mode = context.args[0].lower()
    user_id = update.effective_user.id

    if mode == "status":
        user = await get_user(user_id)
        current = user.get("test_mode") if user else None
        await update.message.reply_text(
            f"Current test mode: `{current or 'none (real admin)'}`",
            parse_mode="Markdown",
        )
        return

    if mode not in ("premium", "free", "reset"):
        await update.message.reply_text("Invalid mode. Use: premium / free / reset")
        return

    test_mode_value = None if mode == "reset" else mode
    await upsert_user(user_id, {"test_mode": test_mode_value})

    labels = {
        "premium": "⭐ You are now simulating a *premium* user.",
        "free": "👤 You are now simulating a *free* user.",
        "reset": "🔧 Test mode reset. You are back to full *admin* access.",
    }
    await update.message.reply_text(labels[mode], parse_mode="Markdown")
