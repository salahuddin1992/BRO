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


def build_server():
    """Build Python server into standalone executable using PyInstaller."""
    print("\n  === Building Python Server (PyInstaller) ===\n")

    # 1. Install deps
    print("[1/3] Installing dependencies...")
    subprocess.run([sys.executable, "-m", "pip", "install", "-r",
                    os.path.join(DIR, "requirements.txt"), "-q"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller>=6.3.0", "-q"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 2. Clean
    print("[2/3] Cleaning previous build...")
    for d in ["dist", "build"]:
        p = os.path.join(DIR, d)
        if os.path.exists(p):
            shutil.rmtree(p)
    spec = os.path.join(DIR, "HelenWiFi.spec")
    if os.path.exists(spec):
        os.remove(spec)

    # 3. Build
    print("[3/3] Building executable...")
    data = []
    for folder in ["templates", "static", "server", "network", "mesh", "database", "utils"]:
        p = os.path.join(DIR, folder)
        if os.path.exists(p):
            data += ["--add-data", f"{p}{SEP}{folder}"]
    cfg = os.path.join(DIR, "config.py")
    if os.path.exists(cfg):
        data += ["--add-data", f"{cfg}{SEP}."]

    hidden = [
        "eventlet", "eventlet.hubs", "eventlet.hubs.epolls", "eventlet.hubs.selects",
        "flask", "flask_socketio", "flask_cors", "flask_limiter",
        "engineio", "engineio.async_drivers.eventlet",
        "socketio", "dns", "dns.resolver", "config",
        "server", "server.bro_server", "server.signaling",
        "network", "network.detector", "mesh", "mesh.mesh_node",
        "database", "database.db",
        "utils", "utils.crypto", "utils.thumbnails", "utils.qr_generator",
        "utils.monitor", "utils.scheduler", "utils.compression", "utils.notifications",
        "cryptography", "PIL", "qrcode", "psutil", "apscheduler",
        "msgpack", "zstandard", "cachetools", "plyer",
    ]
    h_args = []
    for h in hidden:
        h_args += ["--hidden-import", h]

    cmd = [sys.executable, "-m", "PyInstaller", "--name", "HelenWiFi", "--onefile",
           *data, *h_args, "--noconfirm"]
    if sys.platform == "win32":
        cmd.append("--noconsole")
    cmd.append(os.path.join(DIR, "run.py"))

    r = subprocess.run(cmd, cwd=DIR)
    if r.returncode != 0:
        print("\n  BUILD FAILED!")
        return False

    # Create necessary directories in dist
    for d in ["uploads", "backups", "recordings"]:
        os.makedirs(os.path.join(DIR, "dist", d), exist_ok=True)

    ext = ".exe" if sys.platform == "win32" else ""
    exe = os.path.join(DIR, "dist", f"HelenWiFi{ext}")
    size = os.path.getsize(exe) / 1048576 if os.path.exists(exe) else 0

    print(f"\n  SERVER BUILD OK!")
    print(f"  Executable : dist/HelenWiFi{ext} ({size:.1f} MB)")
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

    # Check server exe exists
    ext = ".exe" if sys.platform == "win32" else ""
    exe = os.path.join(DIR, "dist", f"HelenWiFi{ext}")
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
