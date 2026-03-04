"""
Helen WiFi - Scheduled Tasks
Uses APScheduler for automatic maintenance tasks.
"""
import os
import time
import logging

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger("BRO.scheduler")

_scheduler = None


def init_scheduler(db, upload_folder, backup_dir):
    """Initialize and start the background scheduler."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    _scheduler = BackgroundScheduler(daemon=True)

    # Auto-backup every 24 hours
    _scheduler.add_job(
        _auto_backup, "interval", hours=24,
        args=[db, backup_dir],
        id="auto_backup", replace_existing=True,
    )

    # Cleanup old orphaned temp files every 6 hours
    _scheduler.add_job(
        _cleanup_old_files, "interval", hours=6,
        args=[db, upload_folder],
        id="cleanup_files", replace_existing=True,
    )

    # Cleanup expired files every hour
    _scheduler.add_job(
        _cleanup_expired_files, "interval", hours=1,
        args=[db, upload_folder],
        id="cleanup_expired", replace_existing=True,
    )

    # Cleanup expired sessions every hour
    _scheduler.add_job(
        _cleanup_expired_sessions, "interval", hours=1,
        args=[db],
        id="cleanup_sessions", replace_existing=True,
    )

    _scheduler.start()
    logger.info("Scheduler started with auto-backup, cleanup tasks")
    return _scheduler


def shutdown_scheduler():
    """Shutdown the scheduler gracefully."""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def _auto_backup(db, backup_dir):
    """Create an automatic backup."""
    try:
        result = db.create_backup(backup_dir, "نسخة احتياطية تلقائية")
        logger.info(f"Auto-backup created: {result['filename']}")
    except Exception as e:
        logger.error(f"Auto-backup failed: {e}")


def _cleanup_old_files(db, upload_folder):
    """Remove orphaned files older than 30 days.

    Only deletes files that are NOT tracked in the database, so user-uploaded
    files are never removed silently.  Skips known subdirectories like
    thumbnails and _chunks.
    """
    if not os.path.isdir(upload_folder):
        return
    # Build a set of filenames the database still knows about
    try:
        tracked = {f["saved_as"] for f in db.get_files(limit=100_000)}
    except Exception:
        # If we can't query the DB, bail out rather than risk deleting user files
        logger.warning("Cleanup: could not query DB — skipping old-file cleanup")
        return
    cutoff = time.time() - 30 * 24 * 3600  # 30 days
    removed = 0
    for fname in os.listdir(upload_folder):
        if fname in ("thumbnails", "_chunks"):
            continue
        # Never delete files the database still references
        if fname in tracked:
            continue
        fpath = os.path.join(upload_folder, fname)
        if os.path.isfile(fpath):
            try:
                if os.path.getmtime(fpath) < cutoff:
                    os.remove(fpath)
                    removed += 1
            except OSError:
                pass
    if removed:
        logger.info(f"Cleanup: removed {removed} orphaned files")


def _cleanup_expired_files(db, upload_folder):
    """Delete files that have passed their expiration date."""
    try:
        expired = db.delete_expired_files()
        for f in expired:
            fpath = os.path.join(upload_folder, f["saved_as"])
            if os.path.isfile(fpath):
                try:
                    os.remove(fpath)
                except OSError:
                    pass
            # Also remove compressed version
            zpath = fpath + ".zst"
            if os.path.isfile(zpath):
                try:
                    os.remove(zpath)
                except OSError:
                    pass
        if expired:
            logger.info(f"Expired files cleanup: removed {len(expired)} files")
    except Exception as e:
        logger.warning(f"Expired files cleanup error: {e}")


def _cleanup_expired_sessions(db):
    """Mark users who haven't been seen in 24h as offline."""
    try:
        conn = db._get_conn()
        conn.execute(
            "UPDATE users SET status='offline' WHERE status='online' "
            "AND last_seen < datetime('now', '-24 hours')"
        )
        conn.commit()
    except Exception as e:
        logger.warning(f"Session cleanup error: {e}")
