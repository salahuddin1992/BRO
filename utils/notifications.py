"""
Helen WiFi - Desktop Notifications
Uses plyer for cross-platform desktop notifications.
"""
import logging
import sys
import threading
import warnings

logger = logging.getLogger("BRO.notifications")

_plyer_available = False
try:
    # plyer may emit warnings about missing platform backends (e.g. win32api
    # on non-Windows, or dbus on headless Linux).  Suppress them so they don't
    # clutter the console – the fallback path handles unavailability gracefully.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning)
        warnings.filterwarnings("ignore", message=".*win32api.*")
        warnings.filterwarnings("ignore", message=".*dbus.*")
        from plyer import notification as plyer_notification
    # Quick smoke-test on Windows: win32api must be importable for plyer to
    # actually work.  On other platforms plyer uses different backends.
    if sys.platform == "win32":
        import importlib
        importlib.import_module("win32api")
    _plyer_available = True
except (ImportError, Exception):
    logger.info("plyer not available - desktop notifications disabled")


def notify(title, message, timeout=5):
    """Send a desktop notification (non-blocking)."""
    if not _plyer_available:
        return
    threading.Thread(
        target=_send_notification,
        args=(title, message, timeout),
        daemon=True,
    ).start()


def _send_notification(title, message, timeout):
    try:
        plyer_notification.notify(
            title=title,
            message=message,
            app_name="Helen WiFi",
            timeout=timeout,
        )
    except Exception as e:
        logger.debug(f"Notification failed: {e}")


def notify_new_message(sender, text):
    """Notify about a new chat message."""
    preview = text[:100] + "..." if len(text) > 100 else text
    notify(f"رسالة من {sender}", preview)


def notify_incoming_call(caller_name, call_type="video"):
    """Notify about an incoming call."""
    type_text = "مكالمة فيديو" if call_type == "video" else "مكالمة صوتية"
    notify(f"{type_text} واردة", f"{caller_name} يتصل بك")


def notify_file_shared(uploader, filename):
    """Notify about a shared file."""
    notify(f"ملف من {uploader}", filename)


def notify_server_started(ip, port):
    """Notify that the server has started."""
    notify("Helen WiFi", f"السيرفر يعمل على {ip}:{port}")
