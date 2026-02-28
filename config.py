"""
Global configuration for BRO WiFi Server
"""
import os
import sys
import secrets


def _get_base_path():
    """Base path: where code/templates/static are."""
    return os.environ.get("BRO_BASE_PATH", os.path.dirname(os.path.abspath(__file__)))


def _get_runtime_path():
    """Runtime path: where writable files go (uploads, logs)."""
    return os.environ.get("BRO_RUNTIME_PATH", os.path.dirname(os.path.abspath(__file__)))


BASE_PATH = _get_base_path()
RUNTIME_PATH = _get_runtime_path()

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

# File transfer - unlimited
MAX_FILE_SIZE = 0  # 0 = unlimited
UPLOAD_FOLDER = os.path.join(RUNTIME_PATH, "uploads")
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
LOG_FILE = os.path.join(RUNTIME_PATH, "bro_server.log")
