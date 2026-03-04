#!/usr/bin/env python3
"""
Helen WiFi Server - Main Entry Point

Usage:
    python run.py              # Start server (silent mode)
    python run.py --verbose    # Start with console output
    python run.py --port 9000  # Custom port
"""
# CRITICAL: async monkey patch MUST be first before any other import
# Eventlet is deprecated - gevent will be used when available
import warnings
warnings.filterwarnings("ignore", message=".*Eventlet is deprecated.*")

_async_mode = "threading"
try:
    import eventlet
    eventlet.monkey_patch()
    _async_mode = "eventlet"
except ImportError:
    try:
        from gevent import monkey
        monkey.patch_all()
        _async_mode = "gevent"
    except ImportError:
        pass  # fallback to threading mode (no monkey-patching needed)

import sys
import os
import argparse


def get_base_path():
    """Get the base path - works both for script and PyInstaller EXE."""
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller bundle
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def get_runtime_path():
    """Get runtime path for writable files (uploads, logs)."""
    if getattr(sys, 'frozen', False):
        # EXE: use the folder where the .exe is located
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


# Set paths before importing anything else
BASE_PATH = get_base_path()
RUNTIME_PATH = get_runtime_path()
sys.path.insert(0, BASE_PATH)

# Set environment for config module
os.environ["BRO_BASE_PATH"] = BASE_PATH
os.environ["BRO_RUNTIME_PATH"] = RUNTIME_PATH

from server.bro_server import create_app


def _setup_crash_logging():
    """Redirect stderr to a log file so crashes are never silently lost.

    When running as a frozen PyInstaller executable the console may or may not
    be visible.  Writing to a crash log guarantees the traceback is preserved
    regardless.
    """
    if not getattr(sys, 'frozen', False):
        return
    try:
        import logging
        log_path = os.path.join(RUNTIME_PATH, "helen_crash.log")
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setLevel(logging.ERROR)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logging.getLogger().addHandler(handler)

        # Also capture unhandled exceptions into the same file
        _original_excepthook = sys.excepthook

        def _crash_hook(exc_type, exc_value, exc_tb):
            logging.getLogger("crash").critical(
                "Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))
            # Try to show a visible error dialog on Windows
            try:
                if sys.platform == "win32":
                    import ctypes
                    import traceback
                    msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
                    ctypes.windll.user32.MessageBoxW(
                        0,
                        f"Helen WiFi crashed.\n\nDetails saved to:\n{log_path}\n\n{msg[:800]}",
                        "Helen WiFi - Error",
                        0x10,  # MB_ICONERROR
                    )
            except Exception:
                pass
            _original_excepthook(exc_type, exc_value, exc_tb)

        sys.excepthook = _crash_hook
    except Exception:
        pass  # logging setup itself must never prevent startup


def main():
    _setup_crash_logging()

    parser = argparse.ArgumentParser(description="Helen WiFi Server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8400, help="Port (default: 8400)")
    parser.add_argument("--verbose", action="store_true", help="Show console output")
    args = parser.parse_args()

    # If running as EXE without --verbose, default to verbose so user sees the URL
    if getattr(sys, 'frozen', False) and not args.verbose:
        args.verbose = True

    server = create_app()
    server.run(host=args.host, port=args.port, silent=not args.verbose)


if __name__ == "__main__":
    main()
