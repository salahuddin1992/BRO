# PyInstaller RUNTIME hook — executed before ANY user code.
# This guarantees eventlet/gevent monkey-patching happens first,
# regardless of how PyInstaller reorders module imports.

import sys as _sys
import os as _os

# In --onefile mode, ensure DLLs (av/FFmpeg, libmagic) are findable
if getattr(_sys, 'frozen', False) and _sys.platform == 'win32':
    _meipass = getattr(_sys, '_MEIPASS', '')
    if _meipass:
        try:
            _os.add_dll_directory(_meipass)
        except (OSError, AttributeError):
            _os.environ['PATH'] = _meipass + _os.pathsep + _os.environ.get('PATH', '')

import warnings as _w
_w.filterwarnings("ignore", message=".*Eventlet is deprecated.*")
_w.filterwarnings("ignore", message=".*win32api.*")
_w.filterwarnings("ignore", category=DeprecationWarning, module="zstandard")
_w.filterwarnings("ignore", category=DeprecationWarning, module="msgpack")

try:
    import eventlet as _ev
    _ev.monkey_patch()
except ImportError:
    try:
        from gevent import monkey as _gm
        _gm.patch_all()
    except ImportError:
        pass  # threading fallback — no patching needed
