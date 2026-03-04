#!/usr/bin/env python3
"""
Helen WiFi Server - Main Entry Point

Usage:
    python run.py              # Start server (silent mode)
    python run.py --verbose    # Start with console output
    python run.py --port 9000  # Custom port
"""
# CRITICAL: async monkey patch MUST be first before any other import
# Suppress known harmless warnings before any library is imported:
#  - Eventlet deprecation
#  - plyer/win32api missing backend on non-Windows
#  - urllib3 InsecureRequestWarning (self-signed TLS in mesh)
#  - zstandard/msgpack C-extension deprecation notices
import warnings
warnings.filterwarnings("ignore", message=".*Eventlet is deprecated.*")
warnings.filterwarnings("ignore", message=".*win32api.*")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="zstandard")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="msgpack")

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
    """Get runtime path for writable files (uploads, logs, DB, certs).

    When running as a frozen EXE the executable's directory may be
    read-only (e.g. Program Files, Electron resources).  Use a known
    writable location instead.
    """
    # Allow explicit override via environment variable
    env_override = os.environ.get("BRO_RUNTIME_PATH")
    if env_override:
        os.makedirs(env_override, exist_ok=True)
        return env_override

    if getattr(sys, 'frozen', False):
        # First try the EXE's own directory (portable mode)
        exe_dir = os.path.dirname(sys.executable)
        try:
            _test = os.path.join(exe_dir, ".write_test")
            with open(_test, "w") as f:
                f.write("ok")
            os.remove(_test)
            return exe_dir
        except OSError:
            pass
        # Fallback to a writable user-local directory
        if os.name == "nt":
            base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
            p = os.path.join(base, "HelenWiFi")
        else:
            p = os.path.join(os.path.expanduser("~"), ".helenwifi")
        os.makedirs(p, exist_ok=True)
        return p

    return os.path.dirname(os.path.abspath(__file__))


# Set paths before importing anything else
BASE_PATH = get_base_path()
RUNTIME_PATH = get_runtime_path()
sys.path.insert(0, BASE_PATH)

# In frozen mode, av (PyAV/FFmpeg) DLLs live alongside the executable.
# Windows needs them on the DLL search path or av will fail to import.
if getattr(sys, 'frozen', False) and sys.platform == 'win32':
    # Collect all directories that might contain DLLs (BASE_PATH + subdirs)
    _dll_dirs = {BASE_PATH}
    for _entry in os.listdir(BASE_PATH):
        _subdir = os.path.join(BASE_PATH, _entry)
        if os.path.isdir(_subdir):
            # Check if the subdir actually contains DLLs to avoid noise
            if any(f.lower().endswith(('.dll', '.pyd')) for f in os.listdir(_subdir)):
                _dll_dirs.add(_subdir)
    # Also include the directory of the running executable itself
    _exe_dir = os.path.dirname(sys.executable)
    if _exe_dir != BASE_PATH:
        _dll_dirs.add(_exe_dir)

    for _d in _dll_dirs:
        try:
            os.add_dll_directory(_d)
        except (OSError, AttributeError):
            pass
    # Always set PATH as a fallback (works on all Python/Windows versions)
    _extra = os.pathsep.join(_dll_dirs)
    os.environ['PATH'] = _extra + os.pathsep + os.environ.get('PATH', '')

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
