#!/usr/bin/env python3
"""
BRO Server - Build to EXE
==========================
This script converts the entire BRO project into a standalone .exe file.

Just run:
    python build_exe.py

The .exe will be created in the 'dist' folder.
"""
import subprocess
import sys
import os
import shutil

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(PROJECT_DIR, "dist")
BUILD_DIR = os.path.join(PROJECT_DIR, "build")


def check_pyinstaller():
    """Ensure PyInstaller is installed."""
    try:
        import PyInstaller
        print(f"[OK] PyInstaller {PyInstaller.__version__} found")
        return True
    except ImportError:
        print("[!] PyInstaller not found. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller>=6.3.0"])
        print("[OK] PyInstaller installed")
        return True


def install_dependencies():
    """Install all required packages."""
    req_file = os.path.join(PROJECT_DIR, "requirements.txt")
    if os.path.exists(req_file):
        print("[*] Installing dependencies...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", req_file])
        print("[OK] Dependencies installed")


def build_exe():
    """Build the .exe using PyInstaller."""
    print("\n" + "=" * 50)
    print("  BRO Server - Building EXE")
    print("=" * 50 + "\n")

    # Clean previous builds
    for d in [DIST_DIR, BUILD_DIR]:
        if os.path.exists(d):
            shutil.rmtree(d)
            print(f"[*] Cleaned {d}")

    # Collect data files
    templates_dir = os.path.join(PROJECT_DIR, "templates")
    static_dir = os.path.join(PROJECT_DIR, "static")

    # Build PyInstaller command
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "BRO-Server",
        "--onefile",
        "--noconsole",  # Runs silently (no console window)
        "--icon", "NONE",
        # Add data directories
        "--add-data", f"{templates_dir}{os.pathsep}templates",
        "--add-data", f"{static_dir}{os.pathsep}static",
        # Hidden imports that PyInstaller might miss
        "--hidden-import", "eventlet",
        "--hidden-import", "eventlet.hubs.epolls",
        "--hidden-import", "eventlet.hubs.kqueue",
        "--hidden-import", "eventlet.hubs.selects",
        "--hidden-import", "flask",
        "--hidden-import", "flask_socketio",
        "--hidden-import", "flask_cors",
        "--hidden-import", "engineio.async_drivers.eventlet",
        "--hidden-import", "dns",
        "--hidden-import", "dns.resolver",
        # Main script
        os.path.join(PROJECT_DIR, "run.py"),
    ]

    print("[*] Running PyInstaller...")
    print(f"    Command: {' '.join(cmd[-5:])}")
    print()

    result = subprocess.run(cmd, cwd=PROJECT_DIR)

    if result.returncode == 0:
        exe_name = "BRO-Server.exe" if sys.platform == "win32" else "BRO-Server"
        exe_path = os.path.join(DIST_DIR, exe_name)

        # Create uploads folder next to exe
        uploads_in_dist = os.path.join(DIST_DIR, "uploads")
        os.makedirs(uploads_in_dist, exist_ok=True)

        print("\n" + "=" * 50)
        print("  BUILD SUCCESSFUL!")
        print("=" * 50)
        print(f"\n  EXE Location: {exe_path}")
        if os.path.exists(exe_path):
            size_mb = os.path.getsize(exe_path) / (1024 * 1024)
            print(f"  Size: {size_mb:.1f} MB")
        print(f"\n  To run: {exe_path}")
        print(f"  Then open: http://localhost:8400/client")
        print(f"  Admin:     http://localhost:8400/admin")
        print()
        return True
    else:
        print("\n[ERROR] Build failed!")
        print("Check the output above for errors.")
        return False


def build_with_console():
    """Build version WITH console window (for debugging)."""
    print("[*] Building debug version (with console)...")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "BRO-Server-Debug",
        "--onefile",
        "--console",  # Show console for debugging
        "--add-data", f"{os.path.join(PROJECT_DIR, 'templates')}{os.pathsep}templates",
        "--add-data", f"{os.path.join(PROJECT_DIR, 'static')}{os.pathsep}static",
        "--hidden-import", "eventlet",
        "--hidden-import", "eventlet.hubs.epolls",
        "--hidden-import", "eventlet.hubs.kqueue",
        "--hidden-import", "eventlet.hubs.selects",
        "--hidden-import", "flask",
        "--hidden-import", "flask_socketio",
        "--hidden-import", "flask_cors",
        "--hidden-import", "engineio.async_drivers.eventlet",
        os.path.join(PROJECT_DIR, "run.py"),
    ]
    subprocess.run(cmd, cwd=PROJECT_DIR)


def main():
    print("""
    ╔══════════════════════════════════════╗
    ║     BRO Server - EXE Builder        ║
    ╠══════════════════════════════════════╣
    ║  1. Build EXE (Silent)              ║
    ║  2. Build EXE (With Console/Debug)  ║
    ║  3. Install Dependencies Only       ║
    ╚══════════════════════════════════════╝
    """)

    if len(sys.argv) > 1:
        choice = sys.argv[1]
    else:
        choice = input("  Choose [1/2/3]: ").strip()

    if choice == "1" or choice == "":
        install_dependencies()
        check_pyinstaller()
        build_exe()
    elif choice == "2":
        install_dependencies()
        check_pyinstaller()
        build_with_console()
    elif choice == "3":
        install_dependencies()
        print("[OK] All dependencies installed!")
    else:
        print("Invalid choice")


if __name__ == "__main__":
    main()
