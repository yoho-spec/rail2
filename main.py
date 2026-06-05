"""
ARCHIVER BOT - Main Entry Point
Part 1: Foundation & Infrastructure
"""
import asyncio
import logging
import os
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ChatMemberHandler,
    filters,
    ContextTypes,
)
from config.settings import settings
from database.mongodb import init_db
from database.redis_client import init_redis
from middleware.subscription_gate import subscription_required
from handlers.start import start_handler, help_handler
from handlers.admin import admin_handler, add_premium_handler, test_mode_handler
from handlers.auth import login_conversation, logout_handler, mychats_handler
from utils.keep_alive import start_keep_alive
from utils.logger import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


async def post_init(application: Application) -> None:
    """Runs after bot is initialized — set up DB, Redis, etc."""
    await init_db()
    await init_redis()
    logger.info("✅ Database and Redis initialized")

    # Set bot commands menu
    from telegram import BotCommand
    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("help", "Show all commands"),
        BotCommand("mychats", "List your chats (login required)"),
        BotCommand("login", "Connect your Telegram account"),
        BotCommand("logout", "Disconnect your account"),
        BotCommand("archive", "Set up archiving"),
        BotCommand("setdest", "Set destination chat"),
        BotCommand("duplicates", "Duplicate checker"),
        BotCommand("premium", "Premium status"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("✅ Bot commands menu set")


def main() -> None:
    logger.info("🚀 Starting Archiver Bot...")

    app = (
        Application.builder()
        .token(settings.BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # ── Middleware: all non-admin commands go through subscription gate ──
    # (Applied per-handler via decorator in each handler file)

    # ── Core handlers ──
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", help_handler))

    # ── Admin handlers ──
    app.add_handler(CommandHandler("admintest", admin_handler))
    app.add_handler(CommandHandler("addpremium", add_premium_handler))
    app.add_handler(CommandHandler("testmode", test_mode_handler))

    # ── Auth handlers (Part 2) — registered before generic stubs ──
    app.add_handler(login_conversation)
    app.add_handler(CommandHandler("logout", logout_handler))
    app.add_handler(CommandHandler("mychats", mychats_handler))

    # ── Placeholder stubs (Parts 3–8 will fill these) ──
    from handlers.stubs import stub_handler
    for cmd in ["archive", "setdest", "duplicates", "premium",
                "search", "translate", "transcribe"]:
        app.add_handler(CommandHandler(cmd, stub_handler))

    # ── Keep-alive ping for Render free tier ──
    start_keep_alive()

    logger.info("✅ All handlers registered. Bot polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
