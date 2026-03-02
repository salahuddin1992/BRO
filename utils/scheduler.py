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

    # Cleanup old temp files every 6 hours
    _scheduler.add_job(
        _cleanup_old_files, "interval", hours=6,
        args=[upload_folder],
        id="cleanup_files", replace_existing=True,
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


def _cleanup_old_files(upload_folder):
    """Remove temporary/orphaned files older than 30 days."""
    if not os.path.isdir(upload_folder):
        return
    cutoff = time.time() - 30 * 24 * 3600  # 30 days
    removed = 0
    for fname in os.listdir(upload_folder):
        if fname == "thumbnails":
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
        logger.info(f"Cleanup: removed {removed} old files")


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
