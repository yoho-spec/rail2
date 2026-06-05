"""
config/settings.py
All environment variables and configuration in one place.
Copy .env.example → .env and fill in your values.
"""
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Settings:
    # ── Telegram Bot ──
    BOT_TOKEN: str = field(default_factory=lambda: os.environ["BOT_TOKEN"])
    BOT_USERNAME: str = field(default_factory=lambda: os.environ.get("BOT_USERNAME", ""))

    # ── Telegram MTProto (from my.telegram.org) ──
    TELEGRAM_API_ID: int = field(default_factory=lambda: int(os.environ["TELEGRAM_API_ID"]))
    TELEGRAM_API_HASH: str = field(default_factory=lambda: os.environ["TELEGRAM_API_HASH"])

    # ── MongoDB Atlas ──
    MONGODB_URI: str = field(default_factory=lambda: os.environ["MONGODB_URI"])
    MONGODB_DB_NAME: str = field(default_factory=lambda: os.environ.get("MONGODB_DB_NAME", "archiverbot"))

    # ── Redis (Upstash) ──
    REDIS_URL: str = field(default_factory=lambda: os.environ["REDIS_URL"])

    # ── File Storage (Cloudinary) ──
    CLOUDINARY_CLOUD_NAME: str = field(default_factory=lambda: os.environ.get("CLOUDINARY_CLOUD_NAME", ""))
    CLOUDINARY_API_KEY: str = field(default_factory=lambda: os.environ.get("CLOUDINARY_API_KEY", ""))
    CLOUDINARY_API_SECRET: str = field(default_factory=lambda: os.environ.get("CLOUDINARY_API_SECRET", ""))

    # ── Admin ──
    ADMIN_USER_IDS: list = field(default_factory=lambda: [
        int(x) for x in os.environ.get("ADMIN_USER_IDS", "").split(",") if x.strip()
    ])

    # ── Mandatory subscription channel (ads gate) ──
    # Comma-separated list of channel usernames or IDs users must join
    REQUIRED_CHANNELS: list = field(default_factory=lambda: [
        x.strip() for x in os.environ.get("REQUIRED_CHANNELS", "").split(",") if x.strip()
    ])

    # ── Backup bot ──
    BACKUP_BOT_USERNAME: str = field(default_factory=lambda: os.environ.get("BACKUP_BOT_USERNAME", ""))

    # ── Railway keep-alive ──
    # Set BOT_URL manually in Railway variables after first deploy
    BOT_URL: str = field(default_factory=lambda: os.environ.get("BOT_URL", ""))

    # ── Free tier limits ──
    FREE_RESTRICTED_DOWNLOADS: int = field(default_factory=lambda: int(os.environ.get("FREE_RESTRICTED_DOWNLOADS", "7")))
    FREE_ARCHIVE_CHATS: int = field(default_factory=lambda: int(os.environ.get("FREE_ARCHIVE_CHATS", "3")))

    # ── Session encryption key (32 bytes hex) ──
    SESSION_ENCRYPTION_KEY: str = field(default_factory=lambda: os.environ["SESSION_ENCRYPTION_KEY"])

    # ── Environment ──
    ENVIRONMENT: str = field(default_factory=lambda: os.environ.get("ENVIRONMENT", "production"))

    @property
    def is_dev(self) -> bool:
        return self.ENVIRONMENT == "development"

    @property
    def is_prod(self) -> bool:
        return self.ENVIRONMENT == "production"


# Singleton — import this everywhere
settings = Settings()

