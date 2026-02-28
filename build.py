#!/usr/bin/env python3
"""
Helen WiFi - Build to EXE
=========================
Just run this file and it automatically builds the EXE.
No questions, no menus - one click.

    python build.py

The EXE will be in the 'dist' folder.
"""
import subprocess
import sys
import os
import shutil

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(PROJECT_DIR, "dist")
BUILD_DIR = os.path.join(PROJECT_DIR, "build")
SEP = os.pathsep  # ; on Windows, : on Linux/Mac

EXE_NAME = "HelenWiFi"


def main():
    print()
    print("  +--------------------------------------------+")
    print("  |        هيلين WiFi - بناء البرنامج          |")
    print("  |          Helen WiFi - EXE Builder           |")
    print("  +--------------------------------------------+")
    print()

    # Step 1: Install dependencies
    print("[1/3] تثبيت المتطلبات...")
    req_file = os.path.join(PROJECT_DIR, "requirements.txt")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-r", req_file, "-q"],
        stdout=subprocess.DEVNULL
    )
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "pyinstaller>=6.3.0", "-q"],
        stdout=subprocess.DEVNULL
    )
    print("    [OK] تم التثبيت")

    # Step 2: Clean
    print("[2/3] تنظيف البناء السابق...")
    for d in [DIST_DIR, BUILD_DIR]:
        if os.path.exists(d):
            shutil.rmtree(d)
    spec_file = os.path.join(PROJECT_DIR, f"{EXE_NAME}.spec")
    if os.path.exists(spec_file):
        os.remove(spec_file)
    print("    [OK] تم التنظيف")

    # Step 3: Build
    print("[3/3] بناء ملف EXE...")
    print()

    # Collect all data folders
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
        "netifaces", "psutil", "zeroconf",
        "config",
        "server", "server.bro_server", "server.signaling",
        "network", "network.detector",
        "mesh", "mesh.mesh_node",
    ]
    hidden_args = []
    for h in hidden:
        hidden_args.extend(["--hidden-import", h])

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", EXE_NAME,
        "--onefile",
        "--noconsole",
        *data_args,
        *hidden_args,
        "--noconfirm",
        os.path.join(PROJECT_DIR, "run.py"),
    ]

    result = subprocess.run(cmd, cwd=PROJECT_DIR)

    if result.returncode != 0:
        print()
        print("  [ERROR] فشل البناء!")
        input("  اضغط Enter للخروج...")
        sys.exit(1)

    # Create uploads folder
    os.makedirs(os.path.join(DIST_DIR, "uploads"), exist_ok=True)

    # Done
    exe_suffix = ".exe" if sys.platform == "win32" else ""
    exe_path = os.path.join(DIST_DIR, f"{EXE_NAME}{exe_suffix}")
    size_mb = 0
    if os.path.exists(exe_path):
        size_mb = os.path.getsize(exe_path) / (1024 * 1024)

    print()
    print("  +--------------------------------------------+")
    print("  |              تم البناء بنجاح!              |")
    print("  |           BUILD SUCCESSFUL!                 |")
    print("  +--------------------------------------------+")
    print(f"  |  الملف: dist/{EXE_NAME}{exe_suffix}")
    print(f"  |  الحجم: {size_mb:.1f} MB")
    print("  |")
    print("  |  شغّل الملف وراح يفتح المتصفح تلقائياً")
    print("  |  العميل: http://localhost:8400/client")
    print("  |  الادمن: http://localhost:8400/admin")
    print("  +--------------------------------------------+")
    print()

    if sys.platform == "win32":
        input("  اضغط Enter للخروج...")


if __name__ == "__main__":
    main()
