#!/usr/bin/env python3
"""
BRO Server - Build to EXE
==========================
Converts the entire BRO project into a standalone .exe file.

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
        print(f"[OK] PyInstaller {PyInstaller.__version__}")
        return True
    except ImportError:
        print("[*] Installing PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller>=6.3.0"])
        return True


def install_dependencies():
    """Install all required packages."""
    req_file = os.path.join(PROJECT_DIR, "requirements.txt")
    if os.path.exists(req_file):
        print("[*] Installing dependencies...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", req_file])
        print("[OK] Dependencies installed")


def build_exe(with_console=False):
    """Build the .exe using PyInstaller."""
    mode = "Debug" if with_console else "Silent"
    name = "BRO-Server-Debug" if with_console else "BRO-Server"

    print(f"\n{'=' * 50}")
    print(f"  BRO Server - Building EXE ({mode})")
    print(f"{'=' * 50}\n")

    # Clean previous builds
    for d in [DIST_DIR, BUILD_DIR]:
        if os.path.exists(d):
            shutil.rmtree(d)

    sep = os.pathsep  # ; on Windows, : on Linux/Mac

    # All data directories to bundle
    data_args = []
    for folder in ["templates", "static", "server", "network", "mesh", "utils"]:
        folder_path = os.path.join(PROJECT_DIR, folder)
        if os.path.exists(folder_path):
            data_args.extend(["--add-data", f"{folder_path}{sep}{folder}"])

    # Config file
    config_path = os.path.join(PROJECT_DIR, "config.py")
    if os.path.exists(config_path):
        data_args.extend(["--add-data", f"{config_path}{sep}."])

    # Hidden imports - all modules PyInstaller might miss
    hidden_imports = [
        "eventlet",
        "eventlet.hubs",
        "eventlet.hubs.epolls",
        "eventlet.hubs.kqueue",
        "eventlet.hubs.selects",
        "eventlet.hubs.poll",
        "eventlet.green",
        "eventlet.green.ssl",
        "flask",
        "flask.json",
        "flask_socketio",
        "flask_cors",
        "engineio",
        "engineio.async_drivers",
        "engineio.async_drivers.eventlet",
        "socketio",
        "dns",
        "dns.resolver",
        "dns.rdatatype",
        "dns.name",
        "netifaces",
        "psutil",
        "zeroconf",
        "config",
        "server",
        "server.bro_server",
        "server.signaling",
        "network",
        "network.detector",
        "mesh",
        "mesh.mesh_node",
    ]

    hidden_args = []
    for h in hidden_imports:
        hidden_args.extend(["--hidden-import", h])

    # Build command
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", name,
        "--onefile",
        "--console" if with_console else "--noconsole",
        *data_args,
        *hidden_args,
        "--noconfirm",
        os.path.join(PROJECT_DIR, "run.py"),
    ]

    print(f"[*] Building {name}...")
    result = subprocess.run(cmd, cwd=PROJECT_DIR)

    if result.returncode == 0:
        exe_name = f"{name}.exe" if sys.platform == "win32" else name
        exe_path = os.path.join(DIST_DIR, exe_name)

        # Create uploads folder next to exe
        os.makedirs(os.path.join(DIST_DIR, "uploads"), exist_ok=True)

        print(f"\n{'=' * 50}")
        print("  BUILD SUCCESSFUL!")
        print(f"{'=' * 50}")
        print(f"\n  File: {exe_path}")
        if os.path.exists(exe_path):
            size_mb = os.path.getsize(exe_path) / (1024 * 1024)
            print(f"  Size: {size_mb:.1f} MB")
        print(f"\n  Run the EXE and it will:")
        print(f"    1. Start the server silently")
        print(f"    2. Open the browser automatically")
        print(f"    3. Client: http://localhost:8400/client")
        print(f"    4. Admin:  http://localhost:8400/admin")
        print()
        return True
    else:
        print("\n[ERROR] Build failed!")
        return False


def main():
    print("""
    +======================================+
    |     BRO Server - EXE Builder         |
    +======================================+
    |  1. Build EXE (Silent + Auto-open)   |
    |  2. Build EXE (With Console/Debug)   |
    |  3. Install Dependencies Only        |
    +======================================+
    """)

    if len(sys.argv) > 1:
        choice = sys.argv[1]
    else:
        choice = input("  Choose [1/2/3]: ").strip()

    if choice in ("1", ""):
        install_dependencies()
        check_pyinstaller()
        build_exe(with_console=False)
    elif choice == "2":
        install_dependencies()
        check_pyinstaller()
        build_exe(with_console=True)
    elif choice == "3":
        install_dependencies()
        print("[OK] Done!")
    else:
        print("Invalid choice")


if __name__ == "__main__":
    main()
