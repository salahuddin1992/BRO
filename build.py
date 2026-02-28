#!/usr/bin/env python3
"""
Helen WiFi - Cross-Platform Build System
==========================================
Builds a standalone executable for Windows, Linux, or macOS.
No questions, no menus - one click.

    python build.py                  # Auto-detect platform
    python build.py --platform win   # Force Windows build
    python build.py --clean          # Clean only (no build)

The executable will be in the 'dist' folder.
Supports ALL router types including Fiber Optic.
"""
import subprocess
import sys
import os
import shutil
import platform

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(PROJECT_DIR, "dist")
BUILD_DIR = os.path.join(PROJECT_DIR, "build")
SEP = os.pathsep  # ; on Windows, : on Linux/Mac

EXE_NAME = "HelenWiFi"
VERSION = "2.0.0"


def print_banner():
    print()
    print("  +--------------------------------------------+")
    print("  |        هيلين WiFi - بناء البرنامج          |")
    print("  |        Helen WiFi - Build System            |")
    print("  |            Version " + VERSION + "                    |")
    print("  +--------------------------------------------+")
    print()


def install_deps():
    """Step 1: Install all dependencies."""
    print("[1/4] تثبيت المتطلبات...")
    req_file = os.path.join(PROJECT_DIR, "requirements.txt")
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-r", req_file, "-q"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except subprocess.CalledProcessError:
        # Retry without quiet mode for visibility
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-r", req_file]
        )
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "pyinstaller>=6.3.0", "-q"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except subprocess.CalledProcessError:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "pyinstaller>=6.3.0"]
        )
    print("    [OK] تم التثبيت")


def clean_build():
    """Step 2: Clean previous build artifacts."""
    print("[2/4] تنظيف البناء السابق...")
    for d in [DIST_DIR, BUILD_DIR]:
        if os.path.exists(d):
            shutil.rmtree(d)
    spec_file = os.path.join(PROJECT_DIR, f"{EXE_NAME}.spec")
    if os.path.exists(spec_file):
        os.remove(spec_file)
    print("    [OK] تم التنظيف")


def detect_platform():
    """Detect current platform."""
    system = platform.system().lower()
    if system == "windows":
        return "win"
    elif system == "darwin":
        return "mac"
    return "linux"


def build_exe(target_platform=None):
    """Step 3: Build the executable."""
    if target_platform is None:
        target_platform = detect_platform()

    print(f"[3/4] بناء ملف التشغيل ({target_platform})...")
    print()

    # Collect data folders
    data_args = []
    for folder in ["templates", "static", "server", "network", "mesh", "utils"]:
        folder_path = os.path.join(PROJECT_DIR, folder)
        if os.path.exists(folder_path):
            data_args.extend(["--add-data", f"{folder_path}{SEP}{folder}"])

    # Config file
    config_path = os.path.join(PROJECT_DIR, "config.py")
    if os.path.exists(config_path):
        data_args.extend(["--add-data", f"{config_path}{SEP}."])

    # All hidden imports
    hidden = [
        "eventlet", "eventlet.hubs", "eventlet.hubs.epolls",
        "eventlet.hubs.kqueue", "eventlet.hubs.selects", "eventlet.hubs.poll",
        "eventlet.green", "eventlet.green.ssl",
        "flask", "flask.json", "flask_socketio", "flask_cors",
        "engineio", "engineio.async_drivers", "engineio.async_drivers.eventlet",
        "socketio",
        "dns", "dns.resolver", "dns.rdatatype", "dns.name",
        "config",
        "server", "server.bro_server", "server.signaling",
        "network", "network.detector",
        "mesh", "mesh.mesh_node",
        "hashlib", "hmac", "secrets", "struct",
        "shutil", "re",
    ]
    hidden_args = []
    for h in hidden:
        hidden_args.extend(["--hidden-import", h])

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", EXE_NAME,
        "--onefile",
        *data_args,
        *hidden_args,
        "--noconfirm",
    ]

    # Platform-specific options
    if target_platform == "win":
        cmd.append("--noconsole")
    # Linux/Mac: keep console by default for usability

    cmd.append(os.path.join(PROJECT_DIR, "run.py"))

    result = subprocess.run(cmd, cwd=PROJECT_DIR)

    if result.returncode != 0:
        print()
        print("  [ERROR] فشل البناء!")
        print("  حاول تشغيل: pip install pyinstaller --upgrade")
        if target_platform == "win":
            input("  اضغط Enter للخروج...")
        sys.exit(1)


def post_build(target_platform):
    """Step 4: Post-build tasks."""
    print("[4/4] إنهاء...")

    # Create uploads folder
    os.makedirs(os.path.join(DIST_DIR, "uploads"), exist_ok=True)

    # Determine executable name
    if target_platform == "win":
        exe_suffix = ".exe"
    else:
        exe_suffix = ""
    exe_path = os.path.join(DIST_DIR, f"{EXE_NAME}{exe_suffix}")

    # Make executable on Linux/Mac
    if target_platform != "win" and os.path.exists(exe_path):
        os.chmod(exe_path, 0o755)

    size_mb = 0
    if os.path.exists(exe_path):
        size_mb = os.path.getsize(exe_path) / (1024 * 1024)

    print()
    print("  +--------------------------------------------+")
    print("  |              تم البناء بنجاح!              |")
    print("  |           BUILD SUCCESSFUL!                 |")
    print("  +--------------------------------------------+")
    print(f"  |  Version : {VERSION}")
    print(f"  |  Platform: {target_platform}")
    print(f"  |  الملف   : dist/{EXE_NAME}{exe_suffix}")
    print(f"  |  الحجم   : {size_mb:.1f} MB")
    print("  |")
    print("  |  شغّل الملف وراح يفتح المتصفح تلقائياً")
    print("  |  العميل: http://localhost:8400/client")
    print("  |  الادمن: http://localhost:8400/admin")
    print("  |")
    print("  |  يدعم جميع الراوترات:")
    print("  |  WiFi/Ethernet/DSL/Fiber/GPON/EPON/")
    print("  |  XG-PON/XGS-PON/SFP/SFP+/ONT/ONU")
    print("  +--------------------------------------------+")
    print()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Helen WiFi Build System")
    parser.add_argument("--platform", choices=["win", "linux", "mac"],
                        help="Target platform (default: auto-detect)")
    parser.add_argument("--clean", action="store_true",
                        help="Clean build artifacts only")
    args = parser.parse_args()

    print_banner()

    if args.clean:
        clean_build()
        print("  [OK] تم التنظيف فقط")
        return

    target = args.platform or detect_platform()

    install_deps()
    clean_build()
    build_exe(target)
    post_build(target)

    if target == "win":
        input("  اضغط Enter للخروج...")


if __name__ == "__main__":
    main()
