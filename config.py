"""
Global configuration for Helen WiFi Server
Supports ALL network types including Fiber Optic (FTTH/GPON/EPON/XG-PON/XGS-PON/SFP/ONT/ONU)
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
MESH_TCP_PORT = 8402  # TCP fallback for mesh
MESH_BROADCAST_INTERVAL = 5  # seconds
MESH_MAX_SERVERS = 100
MESH_HEARTBEAT_TIMEOUT = 15  # seconds
MESH_ENCRYPTION_KEY = os.environ.get("BRO_MESH_KEY", secrets.token_hex(16))

# File transfer - unlimited
MAX_FILE_SIZE = 0  # 0 = unlimited
UPLOAD_FOLDER = os.path.join(RUNTIME_PATH, "uploads")
CHUNK_SIZE = 1024 * 1024  # 1MB chunks for resumable upload
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# WebRTC - STUN + TURN servers for full connectivity
ICE_SERVERS = [
    # STUN servers
    {"urls": "stun:stun.l.google.com:19302"},
    {"urls": "stun:stun1.l.google.com:19302"},
    {"urls": "stun:stun2.l.google.com:19302"},
    {"urls": "stun:stun3.l.google.com:19302"},
    {"urls": "stun:stun4.l.google.com:19302"},
    # Open TURN servers for NAT traversal
    {
        "urls": "turn:openrelay.metered.ca:80",
        "username": "openrelayproject",
        "credential": "openrelayproject",
    },
    {
        "urls": "turn:openrelay.metered.ca:443",
        "username": "openrelayproject",
        "credential": "openrelayproject",
    },
    {
        "urls": "turn:openrelay.metered.ca:443?transport=tcp",
        "username": "openrelayproject",
        "credential": "openrelayproject",
    },
]

# Network - ALL supported interface types including Fiber Optic
SUPPORTED_INTERFACES = [
    # Wireless
    "wifi", "wlan", "wireless",
    # Wired
    "ethernet", "lan", "wan", "eth",
    # DSL family
    "dsl", "adsl", "adsl2", "vdsl", "vdsl2", "sdsl", "hdsl",
    # Fiber Optic - ALL types
    "fiber", "fibre", "ftth", "fttb", "fttp", "fttc", "fttn", "fttx",
    "gpon", "epon", "xgpon", "xgspon", "10gpon", "ngpon", "ngpon2",
    "sfp", "sfp+", "sfp28", "qsfp", "qsfp+", "qsfp28", "cfp", "xfp",
    "ont", "onu", "olt",
    "optical", "optic",
    # Cellular
    "4g", "lte", "lte-a", "5g", "5gnr", "cellular", "3g", "hspa",
    # VPN
    "vpn", "tunnel", "wireguard", "openvpn",
    # Bridge/Bond
    "bridge", "bond", "team",
    # Satellite
    "satellite", "vsat",
    # Other
    "usb", "tethering", "hotspot",
]

# Fiber Optic Router Compatibility Matrix
FIBER_ROUTER_TYPES = {
    "FTTH": {"name": "Fiber to the Home", "max_speed": "10 Gbps", "mtu": 9000},
    "GPON": {"name": "Gigabit PON", "max_speed": "2.5 Gbps down / 1.25 Gbps up", "mtu": 9000},
    "EPON": {"name": "Ethernet PON", "max_speed": "1.25 Gbps symmetric", "mtu": 9000},
    "XG-PON": {"name": "10-Gigabit PON", "max_speed": "10 Gbps down / 2.5 Gbps up", "mtu": 9000},
    "XGS-PON": {"name": "10-Gigabit Symmetric PON", "max_speed": "10 Gbps symmetric", "mtu": 9000},
    "10G-EPON": {"name": "10-Gigabit EPON", "max_speed": "10 Gbps symmetric", "mtu": 9000},
    "NG-PON2": {"name": "Next-Gen PON 2", "max_speed": "40 Gbps", "mtu": 9000},
    "SFP": {"name": "Small Form-factor Pluggable", "max_speed": "1 Gbps", "mtu": 9000},
    "SFP+": {"name": "Enhanced SFP", "max_speed": "10 Gbps", "mtu": 9000},
    "SFP28": {"name": "SFP 28Gbps", "max_speed": "25 Gbps", "mtu": 9000},
    "QSFP": {"name": "Quad SFP", "max_speed": "4 Gbps", "mtu": 9000},
    "QSFP+": {"name": "Quad SFP+", "max_speed": "40 Gbps", "mtu": 9000},
    "QSFP28": {"name": "Quad SFP 28", "max_speed": "100 Gbps", "mtu": 9000},
    "XFP": {"name": "10 Gigabit SFP", "max_speed": "10 Gbps", "mtu": 9000},
    "CFP": {"name": "C Form-factor Pluggable", "max_speed": "100 Gbps", "mtu": 9000},
    "ONT": {"name": "Optical Network Terminal", "max_speed": "10 Gbps", "mtu": 9000},
    "ONU": {"name": "Optical Network Unit", "max_speed": "10 Gbps", "mtu": 9000},
    "OLT": {"name": "Optical Line Terminal", "max_speed": "40 Gbps", "mtu": 9000},
}

# Network optimization
SOCKET_BUFFER_SIZE = 65535  # Max UDP buffer
TCP_BUFFER_SIZE = 1048576  # 1MB TCP buffer for fiber
JUMBO_FRAME_MTU = 9000  # Jumbo frame support for fiber networks
DEFAULT_MTU = 1500  # Standard MTU

# Logging
LOG_LEVEL = os.environ.get("BRO_LOG_LEVEL", "INFO")
LOG_FILE = os.path.join(RUNTIME_PATH, "helen_wifi.log")
