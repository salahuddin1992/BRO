"""
Helen WiFi - Configuration
"""
import os
import secrets
import stat


def _secure_file(path):
    """Restrict file permissions to owner-only.

    On Unix: chmod 600.
    On Windows: os.chmod only sets the read-only flag and cannot restrict
    to a single user, so we use icacls to remove inherited permissions and
    grant access only to the current user.
    """
    try:
        if os.name == "nt":
            import subprocess
            username = os.environ.get("USERNAME", "")
            if username:
                # Remove inherited ACLs, grant only current user full control
                subprocess.run(
                    ["icacls", path, "/inheritance:r",
                     "/grant:r", f"{username}:(F)"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=0x08000000,  # CREATE_NO_WINDOW
                )
        else:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
    except Exception:
        pass

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
        _secure_file(_SECRET_FILE)
    except OSError:
        pass
    return key

SECRET_KEY = _load_or_create_secret()

# Admin
ADMIN_USERNAME = os.environ.get("BRO_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("BRO_ADMIN_PASS", "admin123")

# Password policy
PASSWORD_MIN_LENGTH = 6
PASSWORD_REQUIRE_MIXED = True  # require letters + digits

# ──────────────────────────────────────────────────────────
# Connection Types Between Servers
# ──────────────────────────────────────────────────────────
# Protocol        | Port  | Transport | Description
# ────────────────┼───────┼───────────┼──────────────────────────────────────
# UDP Broadcast   | 8401  | UDP       | Mesh auto-discovery & peer announcements
#                 |       |           | - HMAC-SHA256 signed messages
#                 |       |           | - Replay protection (30s window)
#                 |       |           | - msgpack serialized payloads
# ────────────────┼───────┼───────────┼──────────────────────────────────────
# TCP Mesh Bridge | 8402  | TCP       | Persistent server-to-server connections
#                 |       |           | - Length-prefixed JSON frames
#                 |       |           | - Optional zlib compression
#                 |       |           | - HMAC challenge-response auth
#                 |       |           | - Heartbeat every 15s (ping/pong)
#                 |       |           | - Auto-reconnect with exponential backoff
# ────────────────┼───────┼───────────┼──────────────────────────────────────
# HTTP/HTTPS REST | 8400  | TCP       | Inter-server API communication
#                 |       |           | - /api/mesh/sync-users  (user sync)
#                 |       |           | - /api/mesh/forward     (event forward)
#                 |       |           | - /api/mesh/broadcast   (broadcast)
#                 |       |           | - /api/mesh/info        (peer metadata)
#                 |       |           | - Auto TLS (self-signed certs)
# ────────────────┼───────┼───────────┼──────────────────────────────────────
# SSH             | 2222  | TCP       | Remote terminal access (encrypted)
#                 |       |           | - Auth via Helen WiFi user database
#                 |       |           | - Admin/moderator only
#                 |       |           | - Server management commands
#                 |       |           | - Requires: paramiko
# ────────────────┼───────┼───────────┼──────────────────────────────────────
# FTP             | 2121  | TCP       | File transfer (unencrypted)
#                 |       |           | - Auth via Helen WiFi user database
#                 |       |           | - Browse/upload/download files
#                 |       |           | - Anonymous read-only access
#                 |       |           | - Passive ports: 60000-60100
#                 |       |           | - Requires: pyftpdlib
# ────────────────┼───────┼───────────┼──────────────────────────────────────
# SFTP            | 2223  | TCP       | Secure file transfer via SSH (encrypted)
#                 |       |           | - Auth via Helen WiFi user database
#                 |       |           | - Browse/upload/download files
#                 |       |           | - Path traversal protection
#                 |       |           | - Requires: paramiko
# ────────────────┼───────┼───────────┼──────────────────────────────────────
# mDNS/DNS-SD    | 5353  | UDP       | Zeroconf service discovery
#                 |       |           | - Service: _helenwifi._tcp.local.
#                 |       |           | - Auto peer detection on LAN
# ────────────────┼───────┼───────────┼──────────────────────────────────────
# STUN/TURN      | 3478  | UDP/TCP   | WebRTC NAT traversal (media relay)
#                 | 5349  | TLS       | Secure TURN relay
#                 | 443   | TLS       | Fallback TURN (firewall-friendly)
# ────────────────┼───────┼───────────┼──────────────────────────────────────
# Socket.IO      | 8400  | WebSocket | Real-time client-server signaling
#                 |       |           | - Chat, calls, file transfer events
#                 |       |           | - WebRTC offer/answer/ICE exchange
# ──────────────────────────────────────────────────────────

# Mesh
MESH_PORT = 8401
MESH_MAX_SERVERS = 100

# SSH Server (remote terminal access - admin/moderator only)
SSH_ENABLED = os.environ.get("BRO_SSH_ENABLED", "1") == "1"
SSH_PORT = int(os.environ.get("BRO_SSH_PORT", 2222))
SSH_HOST_KEY = os.path.join(RUNTIME_PATH, "ssh_host_key")

# FTP Server (file transfer - unencrypted)
FTP_ENABLED = os.environ.get("BRO_FTP_ENABLED", "1") == "1"
FTP_PORT = int(os.environ.get("BRO_FTP_PORT", 2121))

# SFTP Server (secure file transfer via SSH)
SFTP_ENABLED = os.environ.get("BRO_SFTP_ENABLED", "1") == "1"
SFTP_PORT = int(os.environ.get("BRO_SFTP_PORT", 2223))
SFTP_HOST_KEY = os.path.join(RUNTIME_PATH, "sftp_host_key")

# Files
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
UPLOAD_FOLDER = os.path.join(RUNTIME_PATH, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
CHUNK_UPLOAD_FOLDER = os.path.join(RUNTIME_PATH, "uploads", "_chunks")
os.makedirs(CHUNK_UPLOAD_FOLDER, exist_ok=True)
DEFAULT_USER_QUOTA = 500 * 1024 * 1024  # 500MB per user
FILE_ENCRYPTION_KEY = os.environ.get("BRO_FILE_KEY", SECRET_KEY[:32])
FILE_TTL_DAYS = int(os.environ.get("BRO_FILE_TTL", "0"))  # 0 = no expiry

# Database
# On Windows, RUNTIME_PATH (exe directory) may be inside a protected folder
# (e.g. Program Files).  Fall back to %LOCALAPPDATA%/HelenWiFi if the
# runtime directory is not writable, so SQLite can always open the DB.
def _resolve_db_path():
    candidate = os.path.join(RUNTIME_PATH, "helen_wifi.db")
    # If the DB already exists, use it (user chose this location)
    if os.path.isfile(candidate):
        return candidate
    # Check if we can write to RUNTIME_PATH
    try:
        _test = os.path.join(RUNTIME_PATH, ".write_test")
        with open(_test, "w") as f:
            f.write("ok")
        os.remove(_test)
        return candidate
    except OSError:
        pass
    # Fallback: platform-appropriate writable directory
    if os.name == "nt":
        fallback = os.path.join(os.environ.get("LOCALAPPDATA", RUNTIME_PATH), "HelenWiFi")
    else:
        fallback = os.path.join(os.path.expanduser("~"), ".helenwifi")
    os.makedirs(fallback, exist_ok=True)
    return os.path.join(fallback, "helen_wifi.db")

DB_PATH = _resolve_db_path()

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

# TLS (auto-generated self-signed if not provided)
TLS_CERT = os.environ.get("BRO_TLS_CERT", os.path.join(RUNTIME_PATH, "tls_cert.pem"))
TLS_KEY = os.environ.get("BRO_TLS_KEY", os.path.join(RUNTIME_PATH, "tls_key.pem"))

def _ensure_tls_certs():
    """Auto-generate self-signed TLS certs if they don't exist."""
    if os.path.isfile(TLS_CERT) and os.path.isfile(TLS_KEY):
        return True
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        import datetime, ipaddress
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "Helen WiFi Local"),
        ])
        _now = datetime.datetime.now(datetime.timezone.utc)
        cert = (x509.CertificateBuilder()
                .subject_name(subject)
                .issuer_name(issuer)
                .public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(_now)
                .not_valid_after(_now + datetime.timedelta(days=365))
                .add_extension(x509.SubjectAlternativeName([
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]), critical=False)
                .sign(key, hashes.SHA256()))
        with open(TLS_KEY, "wb") as f:
            f.write(key.private_bytes(serialization.Encoding.PEM,
                                       serialization.PrivateFormat.TraditionalOpenSSL,
                                       serialization.NoEncryption()))
        _secure_file(TLS_KEY)
        with open(TLS_CERT, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        return True
    except Exception:
        return False

TLS_AVAILABLE = _ensure_tls_certs()

# Logging
LOG_LEVEL = os.environ.get("BRO_LOG_LEVEL", "INFO")
LOG_FILE = os.path.join(RUNTIME_PATH, "helen_wifi.log")
