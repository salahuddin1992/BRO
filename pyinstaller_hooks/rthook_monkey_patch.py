# PyInstaller RUNTIME hook — executed before ANY user code.
# This guarantees eventlet/gevent monkey-patching happens first,
# regardless of how PyInstaller reorders module imports.

import warnings as _w
_w.filterwarnings("ignore", message=".*Eventlet is deprecated.*")

try:
    import eventlet as _ev
    _ev.monkey_patch()
except ImportError:
    try:
        from gevent import monkey as _gm
        _gm.patch_all()
    except ImportError:
        pass  # threading fallback — no patching needed
