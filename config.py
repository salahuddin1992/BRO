"""
Helen WiFi - Configuration
"""
import os
import secrets

BASE_PATH = os.environ.get("BRO_BASE_PATH", os.path.dirname(os.path.abspath(__file__)))
RUNTIME_PATH = os.environ.get("BRO_RUNTIME_PATH", os.path.dirname(os.path.abspath(__file__)))

# Server
SERVER_HOST = "0.0.0.0"
SERVER_PORT = int(os.environ.get("BRO_PORT", 8400))

# SECRET_KEY: persisted to file so it survives restarts and is shared across mesh
_SECRET_FILE = os.path.join(RUNTIME_PATH, ".secret_key")
def _load_or_create_secret():
    env = os.environ.get("BRO_SECRET")
    if env:
        return env
    if os.path.isfile(_SECRET_FILE):
        try:
            with open(_SECRET_FILE, "r") as f:
                key = f.read().strip()
            if len(key) >= 32:
                return key
        except OSError:
            pass
    key = secrets.token_hex(32)
    try:
        with open(_SECRET_FILE, "w") as f:
            f.write(key)
        os.chmod(_SECRET_FILE, 0o600)
    except OSError:
        pass
    return key

SECRET_KEY = _load_or_create_secret()

# Admin
ADMIN_USERNAME = os.environ.get("BRO_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("BRO_ADMIN_PASS", "admin123")

# Mesh
MESH_PORT = 8401
MESH_MAX_SERVERS = 100

# Files
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
UPLOAD_FOLDER = os.path.join(RUNTIME_PATH, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Database
DB_PATH = os.path.join(RUNTIME_PATH, "helen_wifi.db")

# WebRTC ICE Servers
# Local-only: no external STUN servers needed - uses local STUN on port 3478
ICE_SERVERS = []

# Multi-Network: broadcast mesh discovery on all detected subnets
MULTI_NETWORK = True

# Fiber Router Types
FIBER_TYPES = {
    "FTTH": "Fiber to the Home - 10 Gbps",
    "GPON": "Gigabit PON - 2.5/1.25 Gbps",
    "EPON": "Ethernet PON - 1.25 Gbps",
    "XG-PON": "10-Gigabit PON - 10/2.5 Gbps",
    "XGS-PON": "10G Symmetric PON - 10 Gbps",
    "SFP": "Small Form-factor Pluggable - 1 Gbps",
    "SFP+": "Enhanced SFP - 10 Gbps",
    "ONT": "Optical Network Terminal",
    "ONU": "Optical Network Unit",
    "OLT": "Optical Line Terminal",
}

# Logging
LOG_LEVEL = os.environ.get("BRO_LOG_LEVEL", "INFO")
LOG_FILE = os.path.join(RUNTIME_PATH, "helen_wifi.log")
