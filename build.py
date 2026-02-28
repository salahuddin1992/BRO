#!/usr/bin/env python3
"""
Helen WiFi - Build EXE (one click)
    python build.py
"""
import subprocess, sys, os, shutil

DIR = os.path.dirname(os.path.abspath(__file__))
SEP = os.pathsep

def main():
    print("\n  Helen WiFi - Build\n")

    # 1. Install deps
    print("[1/3] Installing...")
    subprocess.run([sys.executable, "-m", "pip", "install", "-r", os.path.join(DIR, "requirements.txt"), "-q"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller>=6.3.0", "-q"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 2. Clean
    print("[2/3] Cleaning...")
    for d in ["dist", "build"]:
        p = os.path.join(DIR, d)
        if os.path.exists(p):
            shutil.rmtree(p)
    spec = os.path.join(DIR, "HelenWiFi.spec")
    if os.path.exists(spec):
        os.remove(spec)

    # 3. Build
    print("[3/3] Building...")
    data = []
    for folder in ["templates", "static", "server", "network", "mesh", "utils"]:
        p = os.path.join(DIR, folder)
        if os.path.exists(p):
            data += ["--add-data", f"{p}{SEP}{folder}"]
    cfg = os.path.join(DIR, "config.py")
    if os.path.exists(cfg):
        data += ["--add-data", f"{cfg}{SEP}."]

    hidden = ["eventlet", "eventlet.hubs", "eventlet.hubs.epolls", "eventlet.hubs.selects",
              "flask", "flask_socketio", "flask_cors", "engineio", "engineio.async_drivers.eventlet",
              "socketio", "dns", "dns.resolver", "config",
              "server", "server.bro_server", "server.signaling",
              "network", "network.detector", "mesh", "mesh.mesh_node"]
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
        sys.exit(1)

    os.makedirs(os.path.join(DIR, "dist", "uploads"), exist_ok=True)

    ext = ".exe" if sys.platform == "win32" else ""
    exe = os.path.join(DIR, "dist", f"HelenWiFi{ext}")
    size = os.path.getsize(exe) / 1048576 if os.path.exists(exe) else 0

    print(f"\n  BUILD OK! dist/HelenWiFi{ext} ({size:.1f} MB)")
    print(f"  Client: http://localhost:8400/client")
    print(f"  Admin:  http://localhost:8400/admin\n")

if __name__ == "__main__":
    main()
