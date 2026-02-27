"""
Global configuration for BRO WiFi Server
"""
import os
import secrets

# Server settings
SERVER_HOST = "0.0.0.0"
SERVER_PORT = int(os.environ.get("BRO_PORT", 8400))
SECRET_KEY = os.environ.get("BRO_SECRET", secrets.token_hex(32))

# Control panel
ADMIN_USERNAME = os.environ.get("BRO_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("BRO_ADMIN_PASS", "admin123")

# Mesh networking
MESH_DISCOVERY_PORT = 8401
MESH_BROADCAST_INTERVAL = 5  # seconds
MESH_MAX_SERVERS = 100
MESH_HEARTBEAT_TIMEOUT = 15  # seconds

# File transfer
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# WebRTC
ICE_SERVERS = [
    {"urls": "stun:stun.l.google.com:19302"},
    {"urls": "stun:stun1.l.google.com:19302"},
    {"urls": "stun:stun2.l.google.com:19302"},
    {"urls": "stun:stun3.l.google.com:19302"},
]

# Network
SUPPORTED_INTERFACES = [
    "wifi", "ethernet", "lan", "wan", "wlan",
    "dsl", "adsl", "vdsl", "fiber", "gpon", "epon",
    "4g", "lte", "5g", "cellular",
    "vpn", "tunnel", "bridge",
]

# Logging
LOG_LEVEL = os.environ.get("BRO_LOG_LEVEL", "INFO")
LOG_FILE = os.path.join(os.path.dirname(__file__), "bro_server.log")
