"""
database/schemas.py

MongoDB index definitions for all collections.

Call create_indexes(db) once at startup (done automatically by init_db()).
Keeping index definitions here makes them easy to audit and extend.
"""
import logging
from pymongo import IndexModel, ASCENDING, DESCENDING

logger = logging.getLogger(__name__)


async def create_indexes(db) -> None:
    """
    Idempotently create all required indexes across every collection.
    Safe to call on every startup — MongoDB ignores already-existing indexes
    with the same definition.
    """

    # ── users ──────────────────────────────────────────────────────────────
    await db.users.create_indexes([
        IndexModel([("user_id", ASCENDING)], unique=True, name="users_user_id_unique"),
        IndexModel([("username", ASCENDING)], name="users_username"),
        IndexModel([("is_premium", ASCENDING)], name="users_is_premium"),
        IndexModel([("created_at", DESCENDING)], name="users_created_at"),
    ])

    # ── archive_jobs ───────────────────────────────────────────────────────
    await db.archive_jobs.create_indexes([
        IndexModel([("user_id", ASCENDING)], name="archive_jobs_user_id"),
        IndexModel([("status", ASCENDING)], name="archive_jobs_status"),
        IndexModel([("created_at", DESCENDING)], name="archive_jobs_created_at"),
        IndexModel([("job_type", ASCENDING)], name="archive_jobs_job_type"),
    ])

    # ── duplicate_logs ─────────────────────────────────────────────────────
    await db.duplicate_logs.create_indexes([
        IndexModel([("user_id", ASCENDING)], name="duplicate_logs_user_id"),
        IndexModel([("file_hash", ASCENDING)], name="duplicate_logs_file_hash"),
        IndexModel([("created_at", DESCENDING)], name="duplicate_logs_created_at"),
    ])

    # ── premium_users ──────────────────────────────────────────────────────
    await db.premium_users.create_indexes([
        IndexModel([("user_id", ASCENDING)], unique=True, name="premium_users_user_id_unique"),
        IndexModel([("expires_at", ASCENDING)], name="premium_users_expires_at"),
        IndexModel([("granted_by", ASCENDING)], name="premium_users_granted_by"),
    ])

    # ── admin_logs ─────────────────────────────────────────────────────────
    await db.admin_logs.create_indexes([
        IndexModel([("admin_id", ASCENDING)], name="admin_logs_admin_id"),
        IndexModel([("action", ASCENDING)], name="admin_logs_action"),
        IndexModel([("target_user_id", ASCENDING)], name="admin_logs_target_user_id"),
        IndexModel([("created_at", DESCENDING)], name="admin_logs_created_at"),
    ])

    logger.info("✅ schemas.py indexes created (archive_jobs, duplicate_logs, premium_users, admin_logs)")
