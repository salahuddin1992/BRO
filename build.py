#!/usr/bin/env python3
"""
Helen WiFi - Build System
Builds PyInstaller standalone executable + optional Electron desktop app

Usage:
    python build.py              # Build server executable only
    python build.py server       # Build server executable only
    python build.py electron     # Build Electron desktop app
    python build.py all          # Build both server + Electron
"""
import subprocess
import sys
import os
import shutil
import platform

DIR = os.path.dirname(os.path.abspath(__file__))
SEP = os.pathsep


def _find_libmagic_binaries():
    """Locate libmagic DLL/so and its magic.mgc database for bundling."""
    binaries = []
    try:
        import magic as _magic
        magic_dir = os.path.dirname(_magic.__file__)
        # python-magic-bin ships DLLs inside the package on Windows
        for name in ("libmagic-1.dll", "magic1.dll", "libgnurx-0.dll",
                     "libmagic.dylib", "libmagic.so", "libmagic.so.1"):
            p = os.path.join(magic_dir, name)
            if os.path.isfile(p):
                binaries.append((p, "."))
        # magic.mgc database file
        for root, _dirs, files in os.walk(magic_dir):
            for f in files:
                if f == "magic.mgc":
                    binaries.append((os.path.join(root, f), "."))
    except Exception:
        pass
    return binaries


def build_server():
    """Build Python server into standalone executable using PyInstaller."""
    print("\n  === Building Python Server (PyInstaller) ===\n")

    # 1. Install deps
    print("[1/4] Installing dependencies...")
    subprocess.run([sys.executable, "-m", "pip", "install", "-r",
                    os.path.join(DIR, "requirements.txt"), "-q"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller>=6.3.0", "-q"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 2. Clean
    print("[2/4] Cleaning previous build...")
    for d in ["dist", "build"]:
        p = os.path.join(DIR, d)
        if os.path.exists(p):
            shutil.rmtree(p)
    spec = os.path.join(DIR, "HelenWiFi.spec")
    if os.path.exists(spec):
        os.remove(spec)

    # 3. Collect assets
    print("[3/4] Collecting assets & dependencies...")
    data = []
    for folder in ["templates", "static", "server", "network", "mesh", "database", "utils"]:
        p = os.path.join(DIR, folder)
        if os.path.exists(p):
            data += ["--add-data", f"{p}{SEP}{folder}"]
    cfg = os.path.join(DIR, "config.py")
    if os.path.exists(cfg):
        data += ["--add-data", f"{cfg}{SEP}."]

    # --- FIX #2: Bundle libmagic DLL + magic.mgc for python-magic ---
    for src, dst in _find_libmagic_binaries():
        data += ["--add-binary", f"{src}{SEP}{dst}"]

    # --- Hidden imports (expanded for all 6 fixes) ---
    hidden = [
        # --- eventlet (full hub set) ---
        "eventlet", "eventlet.hubs", "eventlet.hubs.epolls",
        "eventlet.hubs.selects", "eventlet.hubs.poll", "eventlet.hubs.kqueue",
        "eventlet.green", "eventlet.green.ssl",
        # --- gevent + greenlet C extension (FIX #4) ---
        "gevent", "gevent.resolver", "gevent.resolver.dnspython",
        "gevent.resolver.ares", "gevent._ffi", "gevent.libuv",
        "greenlet", "greenlet._greenlet",
        # --- Flask / SocketIO ---
        "flask", "flask_socketio", "flask_cors", "flask_limiter",
        "engineio", "engineio.async_drivers.threading",
        "engineio.async_drivers.eventlet", "engineio.async_drivers.gevent",
        "socketio",
        # --- DNS (dnspython — used by gevent resolver + network) ---
        "dns", "dns.resolver", "dns.rdatatype", "dns.asyncresolver",
        "dns.name", "dns.message", "dns.query", "dns.rdata",
        "dns.rdataclass", "dns.zone", "dns.reversename",
        "dns.inet", "dns.entropy",
        # --- App modules ---
        "config",
        "server", "server.bro_server", "server.signaling",
        "network", "network.detector", "network.turn_server",
        "network.discovery", "network.ws_mesh", "network.sfu",
        "network.media_relay",
        "mesh", "mesh.mesh_node",
        "database", "database.db",
        "utils", "utils.crypto", "utils.thumbnails", "utils.qr_generator",
        "utils.monitor", "utils.scheduler", "utils.compression",
        "utils.notifications",
        # --- Crypto / imaging / misc ---
        "cryptography", "cryptography.hazmat.bindings._rust",
        "PIL", "PIL.Image", "PIL.JpegImagePlugin", "PIL.PngImagePlugin",
        "PIL.GifImagePlugin", "PIL.BmpImagePlugin", "PIL.WebPImagePlugin",
        "qrcode", "psutil",
        # --- APScheduler (triggers + jobstores + executors) ---
        "apscheduler", "apscheduler.schedulers.background",
        "apscheduler.triggers.interval", "apscheduler.triggers.cron",
        "apscheduler.triggers.date",
        "apscheduler.jobstores.memory", "apscheduler.executors.pool",
        "msgpack", "zstandard", "cachetools", "plyer",
        # --- paramiko + bcrypt + nacl (SSH key support) ---
        "paramiko", "bcrypt", "bcrypt._bcrypt", "nacl", "nacl.bindings",
        "nacl.public", "nacl.signing",
        # --- aiortc + FFmpeg + cffi + pyOpenSSL (FIX #3) ---
        "aiortc", "aiortc.codecs", "aiortc.contrib", "aiortc.contrib.media",
        "aioice",
        "av",
        "cffi", "_cffi_backend",
        "OpenSSL", "OpenSSL.SSL", "OpenSSL.crypto",
        # --- Flask-Limiter storage backend ---
        "limits", "limits.storage", "limits.strategies",
        # --- Networking ---
        "zeroconf", "requests",
        # --- python-magic ---
        "magic",
    ]
    h_args = []
    for h in hidden:
        h_args += ["--hidden-import", h]

    # --- Custom hooks directory (hooks for eventlet, gevent, greenlet, aiortc) ---
    hooks_dir = os.path.join(DIR, "pyinstaller_hooks")

    # --- Runtime hook: monkey-patch BEFORE anything else (FIX #1) ---
    rthook = os.path.join(hooks_dir, "rthook_monkey_patch.py")

    # 4. Build
    # FIX #5: REMOVED --noconsole so crash tracebacks are visible.
    #         The app itself minimises console noise (run.py --verbose controls output).
    # FIX #6: SWITCHED from --onefile to --onedir.
    #         --onefile extracts to %TEMP% on every launch which triggers Windows
    #         Defender / antivirus heuristics and causes slow startup.  --onedir
    #         produces a normal folder that does not trigger AV self-extraction alerts.
    print("[4/4] Building executable (--onedir)...")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "HelenWiFi",
        "--onedir",                                   # FIX #6
        "--additional-hooks-dir", hooks_dir,          # FIX #1,3,4
        "--runtime-hook", rthook,                     # FIX #1
        *data, *h_args, "--noconfirm",
        # NOTE: --noconsole deliberately omitted (FIX #5)
        os.path.join(DIR, "run.py"),
    ]

    r = subprocess.run(cmd, cwd=DIR)
    if r.returncode != 0:
        print("\n  BUILD FAILED!")
        return False

    # Create necessary writable directories next to the executable
    out_dir = os.path.join(DIR, "dist", "HelenWiFi")
    for d in ["uploads", "backups", "recordings"]:
        os.makedirs(os.path.join(out_dir, d), exist_ok=True)

    ext = ".exe" if sys.platform == "win32" else ""
    exe = os.path.join(out_dir, f"HelenWiFi{ext}")
    size = os.path.getsize(exe) / 1048576 if os.path.exists(exe) else 0

    print(f"\n  SERVER BUILD OK!")
    print(f"  Output dir : dist/HelenWiFi/")
    print(f"  Executable : dist/HelenWiFi/HelenWiFi{ext} ({size:.1f} MB)")
    print(f"  Client     : http://localhost:8400/client")
    print(f"  Admin      : http://localhost:8400/admin\n")
    return True


def build_electron():
    """Build Electron desktop app (requires Node.js)."""
    print("\n  === Building Electron Desktop App ===\n")

    electron_dir = os.path.join(DIR, "electron")
    if not os.path.isdir(electron_dir):
        print("  Error: electron/ directory not found")
        return False

    # Check npm
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    try:
        subprocess.run([npm_cmd, "--version"], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        print("  Error: npm not found. Install Node.js first.")
        print("  Download: https://nodejs.org/")
        return False

    # Check server exe exists (--onedir puts it inside dist/HelenWiFi/)
    ext = ".exe" if sys.platform == "win32" else ""
    exe = os.path.join(DIR, "dist", "HelenWiFi", f"HelenWiFi{ext}")
    if not os.path.isfile(exe):
        print("  Warning: Server executable not found. Build server first:")
        print("    python build.py server")
        print("  Continuing with Electron build anyway...\n")

    # Install dependencies
    print("[1/2] Installing Electron dependencies...")
    r = subprocess.run([npm_cmd, "install"], cwd=electron_dir)
    if r.returncode != 0:
        print("  Failed to install npm dependencies!")
        return False

    # Build Electron
    print("[2/2] Building Electron app...")
    target = ""
    if sys.platform == "win32":
        target = "--win"
    elif sys.platform == "darwin":
        target = "--mac"
    else:
        target = "--linux"

    r = subprocess.run([npm_cmd, "run", "build"], cwd=electron_dir)
    if r.returncode != 0:
        print("\n  ELECTRON BUILD FAILED!")
        return False

    dist_electron = os.path.join(DIR, "dist-electron")
    print(f"\n  ELECTRON BUILD OK!")
    print(f"  Output: {dist_electron}\n")
    return True


def main():
    target = "server"
    if len(sys.argv) > 1:
        target = sys.argv[1].lower()
        if target not in ("server", "electron", "all"):
            print(f"Unknown target: {target}")
            print("Usage: python build.py [server|electron|all]")
            sys.exit(1)

    print(f"""
  Helen WiFi - Build System v2.0
  ==============================
  Platform : {platform.system()} {platform.architecture()[0]}
  Python   : {sys.version.split()[0]}
  Target   : {target}
""")

    if target == "server":
        build_server()
    elif target == "electron":
        build_electron()
    elif target == "all":
        if build_server():
            build_electron()


if __name__ == "__main__":
    main()
