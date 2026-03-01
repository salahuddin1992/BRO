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
SECRET_KEY = os.environ.get("BRO_SECRET", secrets.token_hex(32))

# Admin
ADMIN_USERNAME = os.environ.get("BRO_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("BRO_ADMIN_PASS", "admin123")

# Mesh
MESH_PORT = 8401
MESH_MAX_SERVERS = 100

# Files
MAX_FILE_SIZE = 0  # unlimited
UPLOAD_FOLDER = os.path.join(RUNTIME_PATH, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Database
DB_PATH = os.path.join(RUNTIME_PATH, "helen_wifi.db")

# WebRTC ICE Servers (local network only - no external servers)
ICE_SERVERS = []

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
