"""
database/schemas.py
MongoDB collection schemas and indexes
"""

# Users collection schema
USER_SCHEMA = {
    "_id": "int (telegram user_id)",
    "telegram_name": "str",
    "telegram_username": "str (optional)",
    "telegram_phone": "str",
    "logged_in": "bool",
    "telethon_session": "str (encrypted session string)",
    "logged_in_at": "datetime",
    "logged_out_at": "datetime (optional)",
    "is_premium": "bool",
    "premium_added_at": "datetime (optional)",
    "chats": [
        {
            "id": "int (chat_id)",
            "name": "str",
            "type": "str (Channel/Group/Private)",
            "is_channel": "bool",
            "is_group": "bool",
        }
    ],
    "subscribed_to_backup": "bool",
    "created_at": "datetime",
    "updated_at": "datetime",
}

# Archive jobs collection
ARCHIVE_JOB_SCHEMA = {
    "_id": "ObjectId",
    "user_id": "int",
    "source_chat_id": "int",
    "destination_chat_id": "int",
    "destination_topic_id": "int (optional, for topics)",
    "live_forward": "bool",
    "file_types": ["str"],  # pictures, videos, music, files, voice, messages, links
    "created_at": "datetime",
    "last_forwarded_at": "datetime (optional)",
    "status": "str (active/paused/completed)",
}

# Duplicate detection logs
DUPLICATE_LOG_SCHEMA = {
    "_id": "ObjectId",
    "user_id": "int",
    "source_chat_id": "int",
    "file_unique_id": "str",
    "file_size": "int",
    "file_hash": "str (optional, premium only)",
    "message_id": "int",
    "moved_to_topic": "str",
    "detected_at": "datetime",
}

# Premium users list
PREMIUM_USER_SCHEMA = {
    "_id": "int (user_id)",
    "added_by_admin": "int (admin user_id)",
    "added_at": "datetime",
    "expires_at": "datetime (optional)",
}

# Admin logs
ADMIN_LOG_SCHEMA = {
    "_id": "ObjectId",
    "admin_id": "int",
    "action": "str (ban/mute/kick/delete/add_premium/etc)",
    "target_user_id": "int (optional)",
    "target_chat_id": "int (optional)",
    "details": "dict",
    "timestamp": "datetime",
}


async def create_indexes(db):
    """Create MongoDB indexes for performance."""
    # Users
    await db.users.create_index("telegram_username")
    await db.users.create_index("logged_in")
    await db.users.create_index("is_premium")

    # Archive jobs
    await db.archive_jobs.create_index("user_id")
    await db.archive_jobs.create_index([("user_id", 1), ("source_chat_id", 1)])
    await db.archive_jobs.create_index("status")

    # Duplicate logs
    await db.duplicate_logs.create_index("user_id")
    await db.duplicate_logs.create_index("file_unique_id")
    await db.duplicate_logs.create_index([("user_id", 1), ("source_chat_id", 1)])

    # Premium users
    await db.premium_users.create_index("added_at")

    # Admin logs
    await db.admin_logs.create_index("admin_id")
    await db.admin_logs.create_index("timestamp")

