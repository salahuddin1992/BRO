"""
Helen WiFi - Main Server
Chat + Voice/Video Calls + Screen Share + File Sharing + Rooms + Auth
+ Mesh + Admin + Roles + Backup + E2E + Recordings + Settings
"""
import os
import sys
import re
import uuid
import time
import hmac
import hashlib
import logging
import secrets
import threading
import webbrowser
from datetime import datetime
from functools import wraps
from collections import defaultdict

from flask import (Flask, render_template, request, jsonify,
                   send_from_directory, session, redirect, url_for)
from flask_socketio import SocketIO, emit
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from network.detector import NetworkDetector
from network.turn_server import LocalTurnServer
from network.discovery import ServiceDiscovery
from network.ws_mesh import WebSocketMeshBridge
from network.sfu import SFUManager
from mesh.mesh_node import MeshNode
from server.signaling import SignalingServer
from database.db import Database, ROLE_USER, ROLE_MODERATOR, ROLE_ADMIN
from utils.thumbnails import generate_thumbnail, THUMB_DIR_NAME
from utils.qr_generator import generate_qr_code
from utils.monitor import get_system_stats, get_process_stats
from utils.scheduler import init_scheduler, shutdown_scheduler
from utils.compression import should_compress, compress_file
from utils.notifications import (notify_server_started, notify_new_message,
                                 notify_incoming_call, notify_file_shared)
from utils.crypto import encrypt_file as crypto_encrypt_file, decrypt_file as crypto_decrypt_file

# python-magic: try import, fallback gracefully
try:
    import magic
    _magic_available = True
except ImportError:
    _magic_available = False

logger = logging.getLogger("HelenWiFi")

ALLOWED_EXTENSIONS = {
    'txt','pdf','png','jpg','jpeg','gif','bmp','webp','svg',
    'mp3','mp4','wav','ogg','webm','avi','mkv','mov',
    'doc','docx','xls','xlsx','ppt','pptx','odt','ods',
    'zip','rar','7z','tar','gz',
    'csv','json','xml','html','css','js','py',
}


class BROServer:
    def __init__(self):
        self.server_id = str(uuid.uuid4())[:12]
        self.start_time = datetime.utcnow()

        # Flask
        self.app = Flask(
            __name__,
            template_folder=os.path.join(config.BASE_PATH, "templates"),
            static_folder=os.path.join(config.BASE_PATH, "static"),
        )
        self.app.secret_key = config.SECRET_KEY
        self.app.config["MAX_CONTENT_LENGTH"] = config.MAX_FILE_SIZE
        CORS(self.app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=False)

        # Rate Limiter (flask-limiter)
        self.limiter = Limiter(
            get_remote_address,
            app=self.app,
            default_limits=["200 per minute"],
            storage_uri="memory://",
        )

        # Database
        self.db = Database(config.DB_PATH)

        # Restore persisted admin password hash if changed
        saved_hash = self.db.get_setting("admin_password_hash")
        if saved_hash:
            self._admin_pw_hash = saved_hash
        else:
            self._admin_pw_hash = None  # use plain config.ADMIN_PASSWORD as fallback

        # Network - detect ALL interfaces for multi-network support
        self.detector = NetworkDetector()
        self.detector.detect_all()
        best = self.detector.get_best_interface()
        self.host_ip = best["ip"] if best else "0.0.0.0"
        self.all_ips = self.detector.get_all_ips()
        self.is_fiber = self.detector.has_fiber()

        # SocketIO
        self.sio = SocketIO(self.app, cors_allowed_origins="*", async_mode="eventlet",
                            max_http_buffer_size=10*1024*1024, ping_timeout=60, ping_interval=25)

        # Mesh + Signaling (pass all interfaces for multi-network broadcast)
        self.mesh = MeshNode(self.server_id, self.host_ip, config.SERVER_PORT, config.MESH_PORT,
                             interfaces=self.detector.interfaces)
        self.signaling = SignalingServer(self.sio)

        # Local TURN/STUN server (WebRTC without internet)
        # Full TURN with relay + UDP/TCP/TLS + REST API credentials
        self.turn_server = LocalTurnServer(
            secret_key=config.SECRET_KEY,
            relay_ip=self.host_ip,
        )

        # SFU Manager (Selective Forwarding Unit for reliable media relay)
        self.sfu = SFUManager(self.sio)

        # mDNS/Zeroconf discovery (auto-find peers - register on all interfaces)
        self.discovery = ServiceDiscovery(self.server_id, self.host_ip, config.SERVER_PORT,
                                          all_ips=self.all_ips)

        # WebSocket mesh bridge (persistent peer-to-peer connections)
        self.ws_mesh = WebSocketMeshBridge(
            self.server_id, self.host_ip, config.SERVER_PORT, config.SECRET_KEY
        )

        # State (online sessions) - thread-safe via lock
        self._clients_lock = threading.Lock()
        self.clients = {}       # {sid: {sid, username, ip, connected_at, status}}
        self.auth_tokens = {}   # {token: {username, created_at}}  - session persistence
        self._TOKEN_TTL = 7 * 24 * 3600  # 7 days
        self.logs = []
        self.typing_state = {}  # {sid: {target, username, timestamp}}
        self._MAX_MSG_LEN = 5000  # max message length in characters

        # Chat message rate limiting: {sid: [timestamps]}
        self._msg_rate = defaultdict(list)
        self._MSG_RATE_MAX = 10   # max messages per window
        self._MSG_RATE_WINDOW = 2  # 2-second window

        # Backup directory
        self.backup_dir = os.path.join(config.RUNTIME_PATH, "backups")
        os.makedirs(self.backup_dir, exist_ok=True)

        # Recordings directory
        self.recordings_dir = os.path.join(config.RUNTIME_PATH, "recordings")
        os.makedirs(self.recordings_dir, exist_ok=True)

        # Thumbnails directory
        self.thumb_dir = os.path.join(config.UPLOAD_FOLDER, THUMB_DIR_NAME)
        os.makedirs(self.thumb_dir, exist_ok=True)

        # QR Code (generated on server start in run())
        self._qr_b64 = None

        # Scheduler (initialized in run())
        self._scheduler = None

        # Brute force protection: {ip: [timestamps]}
        self._auth_attempts = defaultdict(list)
        self._AUTH_MAX = 5          # max attempts
        self._AUTH_WINDOW = 60      # per 60 seconds

        # CSRF protection for admin routes
        self._csrf_tokens = {}  # {token: created_at}

        self._setup_routes()
        self._setup_events()

    def _gen_token(self, username):
        raw = f"{username}:{config.SECRET_KEY}:{uuid.uuid4().hex}"
        token = hmac.new(config.SECRET_KEY.encode(), raw.encode(), hashlib.sha256).hexdigest()
        self.auth_tokens[token] = {"username": username, "created_at": time.time()}
        self._cleanup_tokens()
        return token

    def _cleanup_tokens(self):
        now = time.time()
        expired = [t for t, v in self.auth_tokens.items() if now - v["created_at"] > self._TOKEN_TTL]
        for t in expired:
            del self.auth_tokens[t]

    def _get_token_user(self, token):
        info = self.auth_tokens.get(token)
        if not info:
            return None
        if time.time() - info["created_at"] > self._TOKEN_TTL:
            del self.auth_tokens[token]
            return None
        return info["username"]

    def _check_rate(self, ip):
        now = time.time()
        attempts = self._auth_attempts[ip]
        self._auth_attempts[ip] = [t for t in attempts if now - t < self._AUTH_WINDOW]
        return len(self._auth_attempts[ip]) < self._AUTH_MAX

    def _record_attempt(self, ip):
        self._auth_attempts[ip].append(time.time())

    def _check_msg_rate(self, sid):
        """Rate-limit chat messages per session (prevent spam)."""
        now = time.time()
        self._msg_rate[sid] = [t for t in self._msg_rate[sid] if now - t < self._MSG_RATE_WINDOW]
        if len(self._msg_rate[sid]) >= self._MSG_RATE_MAX:
            return False
        self._msg_rate[sid].append(now)
        return True

    def _log(self, msg, level="info"):
        self.logs.append({"time": datetime.utcnow().isoformat(), "level": level, "message": msg})
        if len(self.logs) > 500:
            self.logs = self.logs[-500:]

    def _gen_csrf(self):
        token = secrets.token_hex(32)
        self._csrf_tokens[token] = time.time()
        # Cleanup old tokens (>4 hours)
        cutoff = time.time() - 4 * 3600
        self._csrf_tokens = {t: ts for t, ts in self._csrf_tokens.items() if ts > cutoff}
        return token

    def _check_csrf(self):
        token = (request.headers.get("X-CSRF-Token") or
                 request.form.get("_csrf") or
                 (request.get_json(silent=True) or {}).get("_csrf", ""))
        if token and token in self._csrf_tokens:
            return True
        return False

    def _require_admin(self, f):
        @wraps(f)
        def w(*a, **kw):
            if not session.get("admin"):
                return redirect(url_for("login"))
            # CSRF check for state-changing methods
            if request.method in ("POST", "PUT", "DELETE", "PATCH"):
                if not self._check_csrf():
                    return jsonify({"error": "CSRF token مفقود"}), 403
            return f(*a, **kw)
        return w

    def _setup_routes(self):
        @self.app.route("/")
        def index():
            return redirect(url_for("client_page"))

        @self.app.route("/client")
        def client_page():
            return render_template("client.html")

        # --- Auth ---
        def _check_admin_pw(password):
            if self._admin_pw_hash:
                return check_password_hash(self._admin_pw_hash, password)
            return password == config.ADMIN_PASSWORD

        @self.app.route("/login", methods=["GET", "POST"])
        @self.limiter.limit("10 per minute")
        def login():
            if request.method == "POST":
                ip = request.remote_addr
                if not self._check_rate(ip):
                    return render_template("login.html", error="محاولات كثيرة، انتظر دقيقة")
                self._record_attempt(ip)
                if (request.form.get("username") == config.ADMIN_USERNAME and
                        _check_admin_pw(request.form.get("password", ""))):
                    session["admin"] = True
                    return redirect(url_for("admin_page"))
                return render_template("login.html", error="خطأ بالدخول")
            return render_template("login.html", error=None)

        @self.app.route("/logout")
        def logout():
            session.pop("admin", None)
            return redirect(url_for("login"))

        @self.app.route("/admin")
        @self._require_admin
        def admin_page():
            csrf = self._gen_csrf()
            return render_template("admin.html", csrf_token=csrf)

        @self.app.route("/api/admin/csrf-token")
        @self._require_admin
        def api_csrf_token():
            return jsonify({"token": self._gen_csrf()})

        # --- Admin API ---
        @self.app.route("/api/admin/stats")
        @self._require_admin
        def api_stats():
            uptime = int((datetime.utcnow() - self.start_time).total_seconds())
            mesh_stats = self.mesh.get_stats()
            return jsonify({
                "server_id": self.server_id,
                "uptime": uptime,
                "host_ip": self.host_ip,
                "port": config.SERVER_PORT,
                "is_fiber": self.is_fiber,
                "clients_count": len(self.clients),
                "clients": list(self.clients.values()),
                "messages_count": self.db.count_messages(),
                "messages": self.db.get_all_messages(50),
                "files_count": self.db.count_files(),
                "files": self.db.get_files(limit=50),
                "registered_users": self.db.count_users(),
                "banned_users": self.db.count_banned(),
                "all_users": self.db.get_all_users(),
                "rooms": self.db.get_rooms(),
                "db_size": self.db.get_db_size(),
                "network": self.detector.to_dict_list(),
                "mesh": mesh_stats,
                "remote_users": self.mesh.get_all_remote_users(),
                "signaling": self.signaling.get_stats(),
                "fiber_types": config.FIBER_TYPES,
                "recordings_count": self.db.count_recordings(),
                "logs": self.logs[-50:],
                "system": get_system_stats(),
                "process": get_process_stats(),
                "discovery": {
                    "mdns_peers": self.discovery.get_discovered_peers(),
                },
                "ws_mesh": self.ws_mesh.get_stats(),
            })

        @self.app.route("/api/admin/mesh/connect", methods=["POST"])
        @self._require_admin
        def api_mesh_connect():
            data = request.get_json()
            self.mesh.connect_to(data.get("host"), int(data.get("port", config.SERVER_PORT)))
            return jsonify({"status": "ok"})

        # --- Admin: User Management ---
        @self.app.route("/api/admin/users/<username>/ban", methods=["POST"])
        @self._require_admin
        def api_ban_user(username):
            self.db.ban_user(username)
            for sid, cl in list(self.clients.items()):
                if cl.get("username") == username:
                    self.sio.emit("force_disconnect", {"reason": "تم حظرك"}, room=sid)
                    self.sio.server.disconnect(sid, namespace="/")
            self.auth_tokens = {t: v for t, v in self.auth_tokens.items() if v["username"] != username}
            self._log(f"Admin banned: {username}", "warning")
            self._broadcast_users()
            return jsonify({"status": "ok"})

        @self.app.route("/api/admin/users/<username>/unban", methods=["POST"])
        @self._require_admin
        def api_unban_user(username):
            self.db.unban_user(username)
            self._log(f"Admin unbanned: {username}")
            return jsonify({"status": "ok"})

        @self.app.route("/api/admin/users/<username>/kick", methods=["POST"])
        @self._require_admin
        def api_kick_user(username):
            for sid, cl in list(self.clients.items()):
                if cl.get("username") == username:
                    self.sio.emit("force_disconnect", {"reason": "تم طردك"}, room=sid)
                    self.sio.server.disconnect(sid, namespace="/")
            self._log(f"Admin kicked: {username}", "warning")
            return jsonify({"status": "ok"})

        @self.app.route("/api/admin/users/<username>/delete", methods=["DELETE"])
        @self._require_admin
        def api_delete_user(username):
            for sid, cl in list(self.clients.items()):
                if cl.get("username") == username:
                    self.sio.emit("force_disconnect", {"reason": "تم حذف حسابك"}, room=sid)
                    self.sio.server.disconnect(sid, namespace="/")
            self.auth_tokens = {t: v for t, v in self.auth_tokens.items() if v["username"] != username}
            self.db.delete_user(username)
            self._log(f"Admin deleted user: {username}", "warning")
            self._broadcast_users()
            return jsonify({"status": "ok"})

        @self.app.route("/api/admin/users/<username>/reset-password", methods=["POST"])
        @self._require_admin
        def api_reset_password(username):
            data = request.get_json()
            new_pw = data.get("password", "")
            if len(new_pw) < 4:
                return jsonify({"error": "كلمة المرور قصيرة"}), 400
            self.db.admin_reset_password(username, new_pw)
            self._log(f"Admin reset password: {username}")
            return jsonify({"status": "ok"})

        # --- Admin: Role Management ---
        @self.app.route("/api/admin/users/<username>/role", methods=["POST"])
        @self._require_admin
        def api_set_role(username):
            data = request.get_json()
            role = data.get("role", ROLE_USER)
            if role not in (ROLE_USER, ROLE_MODERATOR, ROLE_ADMIN):
                return jsonify({"error": "صلاحية غير صالحة"}), 400
            self.db.set_user_role(username, role)
            self._log(f"Admin set role: {username} -> {role}")
            # Notify the user about role change
            for sid, cl in self.clients.items():
                if cl.get("username") == username:
                    self.sio.emit("role_updated", {"role": role}, room=sid)
            return jsonify({"status": "ok"})

        # --- Admin: Room Management ---
        @self.app.route("/api/admin/rooms/<int:room_id>", methods=["DELETE"])
        @self._require_admin
        def api_delete_room(room_id):
            room_files = self.db.get_files_by_room(room_id)
            for rf in room_files:
                fpath = os.path.join(config.UPLOAD_FOLDER, rf["saved_as"])
                if os.path.isfile(fpath):
                    try:
                        os.remove(fpath)
                    except OSError:
                        pass
            self.db.delete_room(room_id)
            self._log(f"Admin deleted room: {room_id}", "warning")
            return jsonify({"status": "ok"})

        # --- Admin: Message Management ---
        @self.app.route("/api/admin/messages/<int:msg_id>", methods=["DELETE"])
        @self._require_admin
        def api_delete_message(msg_id):
            self.db.delete_message(msg_id)
            self.sio.emit("message_deleted", {"id": msg_id})
            return jsonify({"status": "ok"})

        @self.app.route("/api/admin/messages/by-user/<username>", methods=["DELETE"])
        @self._require_admin
        def api_delete_user_messages(username):
            self.db.admin_delete_messages_by_user(username)
            self._log(f"Admin deleted all messages by: {username}", "warning")
            return jsonify({"status": "ok"})

        # --- Admin: File Management ---
        @self.app.route("/api/admin/files/<int:file_id>", methods=["DELETE"])
        @self._require_admin
        def api_delete_file(file_id):
            saved_as = self.db.delete_file(file_id)
            if saved_as:
                fpath = os.path.join(config.UPLOAD_FOLDER, saved_as)
                if os.path.isfile(fpath):
                    try:
                        os.remove(fpath)
                    except OSError:
                        pass
            self._log(f"Admin deleted file: {file_id}", "warning")
            return jsonify({"status": "ok"})

        # --- Admin: Change admin password ---
        @self.app.route("/api/admin/change-password", methods=["POST"])
        @self._require_admin
        def api_change_admin_pw():
            data = request.get_json()
            old = data.get("old_password", "")
            new = data.get("new_password", "")
            if not _check_admin_pw(old):
                return jsonify({"error": "كلمة المرور الحالية خطأ"}), 400
            if len(new) < 4:
                return jsonify({"error": "كلمة المرور الجديدة قصيرة"}), 400
            self._admin_pw_hash = generate_password_hash(new)
            self.db.set_setting("admin_password_hash", self._admin_pw_hash)
            self._log("Admin password changed")
            return jsonify({"status": "ok"})

        # --- Admin: Backup & Restore ---
        @self.app.route("/api/admin/backup", methods=["POST"])
        @self._require_admin
        def api_create_backup():
            data = request.get_json() or {}
            desc = data.get("description", "")
            result = self.db.create_backup(self.backup_dir, desc)
            self._log(f"Backup created: {result['filename']}")
            return jsonify({"status": "ok", "backup": result})

        @self.app.route("/api/admin/backups")
        @self._require_admin
        def api_list_backups():
            backups = self.db.get_backups()
            return jsonify({"backups": backups})

        @self.app.route("/api/admin/restore", methods=["POST"])
        @self._require_admin
        def api_restore_backup():
            data = request.get_json()
            filename = data.get("filename", "")
            if not filename:
                return jsonify({"error": "اسم الملف مطلوب"}), 400
            safe = secure_filename(filename)
            if not safe or safe != filename:
                return jsonify({"error": "اسم ملف غير صالح"}), 400
            if self.db.restore_backup(self.backup_dir, safe):
                self._log(f"Backup restored: {filename}", "warning")
                return jsonify({"status": "ok"})
            return jsonify({"error": "فشل استعادة النسخة"}), 400

        @self.app.route("/api/admin/backups/<int:backup_id>", methods=["DELETE"])
        @self._require_admin
        def api_delete_backup(backup_id):
            filename = self.db.delete_backup_record(backup_id)
            if filename:
                fpath = os.path.join(self.backup_dir, filename)
                if os.path.isfile(fpath):
                    try:
                        os.remove(fpath)
                    except OSError:
                        pass
            self._log(f"Backup deleted: {backup_id}")
            return jsonify({"status": "ok"})

        @self.app.route("/api/admin/backup/download/<filename>")
        @self._require_admin
        def api_download_backup(filename):
            safe = secure_filename(filename)
            if not safe or safe != filename:
                return jsonify({"error": "اسم ملف غير صالح"}), 400
            return send_from_directory(self.backup_dir, safe, as_attachment=True)

        # --- Admin: Recordings Management ---
        @self.app.route("/api/admin/recordings")
        @self._require_admin
        def api_list_recordings():
            recs = self.db.get_recordings()
            return jsonify({"recordings": recs})

        @self.app.route("/api/admin/recordings/<int:rec_id>", methods=["DELETE"])
        @self._require_admin
        def api_delete_recording(rec_id):
            filename = self.db.delete_recording(rec_id)
            if filename:
                fpath = os.path.join(self.recordings_dir, filename)
                if os.path.isfile(fpath):
                    try:
                        os.remove(fpath)
                    except OSError:
                        pass
            self._log(f"Recording deleted: {rec_id}")
            return jsonify({"status": "ok"})

        # --- Admin: Server Settings ---
        @self.app.route("/api/admin/settings", methods=["GET"])
        @self._require_admin
        def api_get_settings():
            settings = self.db.get_all_settings()
            return jsonify({"settings": settings})

        @self.app.route("/api/admin/settings", methods=["POST"])
        @self._require_admin
        def api_save_settings():
            data = request.get_json()
            for key, value in data.items():
                self.db.set_setting(key, str(value))
            self._log("Settings updated")
            return jsonify({"status": "ok"})

        # --- Files ---
        def _verify_user(self_ref):
            """Check if uploader is authenticated via token or active socket."""
            token = request.form.get("token") or request.args.get("token", "")
            if token:
                uname = self_ref._get_token_user(token)
                if uname:
                    return uname
            uname = request.form.get("username", "")
            if not uname or uname == "?":
                return None
            for cl in self_ref.clients.values():
                if cl.get("username") == uname:
                    return uname
            return None

        @self.app.route("/api/upload", methods=["POST"])
        @self.limiter.limit("30 per minute")
        def upload():
            uploader = _verify_user(self)
            if not uploader:
                return jsonify({"error": "غير مصرح"}), 401
            f = request.files.get("file")
            if not f or not f.filename:
                return jsonify({"error": "No file"}), 400
            original = f.filename
            safe = secure_filename(original) or "file"
            ext = safe.rsplit('.', 1)[-1].lower() if '.' in safe else ''
            if ext and ext not in ALLOWED_EXTENSIONS:
                return jsonify({"error": f"نوع الملف غير مسموح: .{ext}"}), 400
            name = f"{int(time.time())}_{safe}"
            save_path = os.path.join(config.UPLOAD_FOLDER, name)
            f.save(save_path)
            # Validate MIME type with python-magic
            if _magic_available:
                try:
                    mime = magic.from_file(save_path, mime=True)
                    dangerous_mimes = {"application/x-executable", "application/x-dosexec",
                                       "application/x-sharedlib", "application/x-mach-binary"}
                    if mime in dangerous_mimes:
                        os.remove(save_path)
                        return jsonify({"error": "نوع الملف غير مسموح (ملف تنفيذي)"}), 400
                except Exception:
                    pass
            size = os.path.getsize(save_path)
            if size > 100 * 1024 * 1024:
                os.remove(os.path.join(config.UPLOAD_FOLDER, name))
                return jsonify({"error": "حجم الملف كبير جداً (100MB كحد أقصى)"}), 400
            uploaded_by = uploader
            room_id = request.form.get("room_id", type=int)
            target_user = request.form.get("target_user")

            # Generate thumbnail for images
            thumb = generate_thumbnail(config.UPLOAD_FOLDER, name)

            # Compress compressible files
            if should_compress(name, size):
                try:
                    compressed_path = compress_file(save_path, save_path + ".zst")
                    # Keep compressed version alongside original
                except Exception:
                    pass

            # Check quota
            if not self.db.check_quota(uploaded_by, size):
                os.remove(save_path)
                return jsonify({"error": "تجاوزت حد التخزين المسموح"}), 413
            # Detect MIME type
            mime_type = ''
            if _magic_available:
                try:
                    mime_type = magic.from_file(save_path, mime=True) or ''
                except Exception:
                    pass
            # Optional file encryption
            encrypted = False
            if config.FILE_ENCRYPTION_KEY and request.form.get("encrypt") == "1":
                try:
                    enc_path = save_path + ".enc"
                    key = config.FILE_ENCRYPTION_KEY.encode()[:32].ljust(32, b'\0')
                    crypto_encrypt_file(key, save_path, enc_path)
                    os.replace(enc_path, save_path)
                    encrypted = True
                except Exception:
                    pass
            # TTL / expiration
            expires_at = None
            ttl_hours = request.form.get("ttl_hours", type=int)
            if ttl_hours and ttl_hours > 0:
                from datetime import timedelta
                expires_at = (datetime.utcnow() + timedelta(hours=ttl_hours)).isoformat()
            elif config.FILE_TTL_DAYS > 0:
                from datetime import timedelta
                expires_at = (datetime.utcnow() + timedelta(days=config.FILE_TTL_DAYS)).isoformat()
            self.db.save_file(original, name, size, uploaded_by, room_id,
                              mime_type=mime_type, encrypted=encrypted, expires_at=expires_at)
            info = {
                "name": f.filename, "saved_as": name,
                "size": size,
                "uploaded_by": uploaded_by,
                "uploaded_at": datetime.utcnow().isoformat(),
                "room_id": room_id,
                "target_user": target_user,
                "thumbnail": thumb,
                "mime_type": mime_type,
            }
            self._log(f"File: {f.filename}")
            notify_file_shared(uploaded_by, f.filename)
            if room_id:
                members = self.db.get_room_members(room_id)
                for sid, cl in self.clients.items():
                    if cl.get("username") in members:
                        self.sio.emit("file_shared", info, room=sid)
            elif target_user:
                for sid, cl in self.clients.items():
                    if cl.get("username") in (target_user, uploaded_by):
                        self.sio.emit("file_shared", info, room=sid)
            else:
                self.sio.emit("file_shared", info)
            return jsonify({"status": "ok", "file": info})

        @self.app.route("/api/upload-recording", methods=["POST"])
        def upload_recording():
            uploader = _verify_user(self)
            if not uploader:
                return jsonify({"error": "غير مصرح"}), 401
            f = request.files.get("recording")
            if not f or not f.filename:
                return jsonify({"error": "No recording"}), 400
            callee = request.form.get("callee", "unknown")
            call_type = request.form.get("call_type", "audio")
            duration = request.form.get("duration", 0, type=int)
            ts = int(time.time())
            name = f"recording_{ts}_{secure_filename(f.filename) or 'rec.webm'}"
            fpath = os.path.join(self.recordings_dir, name)
            f.save(fpath)
            size = os.path.getsize(fpath)
            rec_id = self.db.save_recording(uploader, callee, call_type, name, size, duration)
            self._log(f"Recording saved: {name}")
            return jsonify({"status": "ok", "id": rec_id})

        @self.app.route("/api/download/<filename>")
        def download(filename):
            if not session.get("admin"):
                # Check token first, then fallback to username
                token = request.args.get("token", "")
                user = self._get_token_user(token) if token else None
                if not user:
                    user = request.args.get("u", "")
                    if not user or not any(c.get("username") == user for c in self.clients.values()):
                        return jsonify({"error": "غير مصرح"}), 401
            safe = secure_filename(filename)
            if not safe or safe != filename:
                return jsonify({"error": "اسم ملف غير صالح"}), 400
            fpath = os.path.join(config.UPLOAD_FOLDER, safe)
            if not os.path.isfile(fpath):
                return jsonify({"error": "الملف غير موجود"}), 404
            return send_from_directory(config.UPLOAD_FOLDER, safe, as_attachment=True)

        @self.app.route("/api/recording/<filename>")
        def download_recording(filename):
            if not session.get("admin"):
                token = request.args.get("token", "")
                user = self._get_token_user(token) if token else None
                if not user:
                    user = request.args.get("u", "")
                    if not user or not any(c.get("username") == user for c in self.clients.values()):
                        return jsonify({"error": "غير مصرح"}), 401
            safe = secure_filename(filename)
            if not safe or safe != filename:
                return jsonify({"error": "اسم ملف غير صالح"}), 400
            fpath = os.path.join(self.recordings_dir, safe)
            if not os.path.isfile(fpath):
                return jsonify({"error": "التسجيل غير موجود"}), 404
            return send_from_directory(self.recordings_dir, safe, as_attachment=True)

        @self.app.route("/api/files")
        def list_files():
            room_id = request.args.get("room_id", type=int)
            return jsonify({"files": self.db.get_files(room_id=room_id)})

        @self.app.route("/api/ice-config")
        def ice_config():
            # Full ICE config with STUN + TURN (UDP/TCP/TLS) + credentials
            username = request.args.get("username")
            config_data = self.turn_server.get_ice_server_config(self.host_ip, username)
            # Also add STUN on all other interfaces
            existing_urls = set()
            for s in config_data["iceServers"]:
                urls = s["urls"] if isinstance(s["urls"], list) else [s["urls"]]
                existing_urls.update(urls)
            for iface in self.detector.interfaces:
                stun_url = f"stun:{iface['ip']}:{self.turn_server.port}"
                if stun_url not in existing_urls:
                    config_data["iceServers"].insert(0, {"urls": stun_url})
            return jsonify(config_data)

        # --- QR Code ---
        @self.app.route("/api/qr-code")
        def api_qr_code():
            if self._qr_b64:
                return jsonify({"qr": self._qr_b64})
            url = f"http://{self.host_ip}:{config.SERVER_PORT}/client"
            self._qr_b64 = generate_qr_code(url)
            return jsonify({"qr": self._qr_b64})

        # --- Thumbnail ---
        @self.app.route("/api/thumbnail/<filename>")
        def serve_thumbnail(filename):
            safe = secure_filename(filename)
            if not safe or safe != filename:
                return jsonify({"error": "اسم ملف غير صالح"}), 400
            thumb_name = f"thumb_{safe}"
            thumb_path = os.path.join(self.thumb_dir, thumb_name)
            if os.path.isfile(thumb_path):
                return send_from_directory(self.thumb_dir, thumb_name)
            return jsonify({"error": "الصورة المصغرة غير موجودة"}), 404

        # --- Media Preview (stream video/audio/PDF inline) ---
        @self.app.route("/api/preview/<filename>")
        def preview_file(filename):
            if not session.get("admin"):
                token = request.args.get("token", "")
                user = self._get_token_user(token) if token else None
                if not user:
                    user = request.args.get("u", "")
                    if not user or not any(c.get("username") == user for c in self.clients.values()):
                        return jsonify({"error": "غير مصرح"}), 401
            safe = secure_filename(filename)
            if not safe or safe != filename:
                return jsonify({"error": "اسم ملف غير صالح"}), 400
            fpath = os.path.join(config.UPLOAD_FOLDER, safe)
            if not os.path.isfile(fpath):
                return jsonify({"error": "الملف غير موجود"}), 404
            # Serve inline (not as attachment) for preview
            from flask import send_file
            import mimetypes
            mime = mimetypes.guess_type(safe)[0] or 'application/octet-stream'
            return send_file(fpath, mimetype=mime, download_name=safe)

        # --- Chunked Upload ---
        @self.app.route("/api/upload/chunk", methods=["POST"])
        @self.limiter.limit("60 per minute")
        def upload_chunk():
            uploader = _verify_user(self)
            if not uploader:
                return jsonify({"error": "غير مصرح"}), 401
            upload_id = request.form.get("upload_id")
            chunk_index = request.form.get("chunk_index", type=int)
            total_chunks = request.form.get("total_chunks", type=int)
            filename = request.form.get("filename", "file")
            total_size = request.form.get("total_size", 0, type=int)
            if not upload_id or chunk_index is None or not total_chunks:
                return jsonify({"error": "بيانات ناقصة"}), 400
            # Check quota before accepting
            if not self.db.check_quota(uploader, total_size):
                return jsonify({"error": "تجاوزت حد التخزين المسموح"}), 413
            chunk = request.files.get("chunk")
            if not chunk:
                return jsonify({"error": "لا يوجد جزء"}), 400
            chunk_dir = os.path.join(config.CHUNK_UPLOAD_FOLDER, secure_filename(upload_id))
            os.makedirs(chunk_dir, exist_ok=True)
            chunk_path = os.path.join(chunk_dir, f"chunk_{chunk_index:05d}")
            chunk.save(chunk_path)
            # Check if all chunks received
            received = len([f for f in os.listdir(chunk_dir) if f.startswith("chunk_")])
            if received >= total_chunks:
                # Assemble file
                safe = secure_filename(filename) or "file"
                ext = safe.rsplit('.', 1)[-1].lower() if '.' in safe else ''
                if ext and ext not in ALLOWED_EXTENSIONS:
                    import shutil
                    shutil.rmtree(chunk_dir, ignore_errors=True)
                    return jsonify({"error": f"نوع الملف غير مسموح: .{ext}"}), 400
                name = f"{int(time.time())}_{safe}"
                save_path = os.path.join(config.UPLOAD_FOLDER, name)
                with open(save_path, 'wb') as out_f:
                    for i in range(total_chunks):
                        cp = os.path.join(chunk_dir, f"chunk_{i:05d}")
                        if os.path.isfile(cp):
                            with open(cp, 'rb') as cf:
                                out_f.write(cf.read())
                import shutil
                shutil.rmtree(chunk_dir, ignore_errors=True)
                size = os.path.getsize(save_path)
                room_id = request.form.get("room_id", type=int)
                target_user = request.form.get("target_user")
                thumb = generate_thumbnail(config.UPLOAD_FOLDER, name)
                if should_compress(name, size):
                    try:
                        compress_file(save_path, save_path + ".zst")
                    except Exception:
                        pass
                # Detect MIME type
                mime_type = ''
                if _magic_available:
                    try:
                        mime_type = magic.from_file(save_path, mime=True) or ''
                    except Exception:
                        pass
                # Optional file encryption
                encrypted = False
                if config.FILE_ENCRYPTION_KEY and request.form.get("encrypt") == "1":
                    try:
                        enc_path = save_path + ".enc"
                        key = config.FILE_ENCRYPTION_KEY.encode()[:32].ljust(32, b'\0')
                        crypto_encrypt_file(key, save_path, enc_path)
                        os.replace(enc_path, save_path)
                        encrypted = True
                    except Exception:
                        pass
                # TTL / expiration
                expires_at = None
                ttl_hours = request.form.get("ttl_hours", type=int)
                if ttl_hours and ttl_hours > 0:
                    from datetime import timedelta
                    expires_at = (datetime.utcnow() + timedelta(hours=ttl_hours)).isoformat()
                elif config.FILE_TTL_DAYS > 0:
                    from datetime import timedelta
                    expires_at = (datetime.utcnow() + timedelta(days=config.FILE_TTL_DAYS)).isoformat()
                self.db.save_file(filename, name, size, uploader, room_id,
                                  mime_type=mime_type, encrypted=encrypted, expires_at=expires_at)
                info = {
                    "name": filename, "saved_as": name, "size": size,
                    "uploaded_by": uploader, "uploaded_at": datetime.utcnow().isoformat(),
                    "room_id": room_id, "target_user": target_user,
                    "thumbnail": thumb, "mime_type": mime_type,
                }
                notify_file_shared(uploader, filename)
                if room_id:
                    members = self.db.get_room_members(room_id)
                    for sid, cl in self.clients.items():
                        if cl.get("username") in members:
                            self.sio.emit("file_shared", info, room=sid)
                elif target_user:
                    for sid, cl in self.clients.items():
                        if cl.get("username") in (target_user, uploader):
                            self.sio.emit("file_shared", info, room=sid)
                else:
                    self.sio.emit("file_shared", info)
                return jsonify({"status": "ok", "complete": True, "file": info})
            return jsonify({"status": "ok", "complete": False, "received": received, "total": total_chunks})

        # --- File Search ---
        @self.app.route("/api/files/search")
        def search_files():
            query = request.args.get("q", "")
            uploader = request.args.get("uploaded_by", "")
            room_id = request.args.get("room_id", type=int)
            date_from = request.args.get("date_from", "")
            date_to = request.args.get("date_to", "")
            results = self.db.search_files(query, uploaded_by=uploader or None,
                                           room_id=room_id, date_from=date_from or None,
                                           date_to=date_to or None)
            return jsonify({"files": results})

        # --- User Quota ---
        @self.app.route("/api/quota")
        def get_quota():
            token = request.args.get("token", "")
            user = self._get_token_user(token) if token else None
            if not user:
                user = request.args.get("u", "")
            if not user:
                return jsonify({"error": "غير مصرح"}), 401
            quota = self.db.get_user_quota(user)
            return jsonify({"quota": quota})

        # --- Mesh Inter-server API ---
        def _check_mesh_secret():
            token = request.headers.get("X-Mesh-Secret", "")
            return hmac.compare_digest(token, config.SECRET_KEY)

        @self.app.route("/api/mesh/info")
        def mesh_info():
            if not _check_mesh_secret() and not session.get("admin"):
                return jsonify({"error": "unauthorized"}), 403
            return jsonify({
                "server_id": self.server_id,
                "host": self.host_ip,
                "port": config.SERVER_PORT,
                "mesh_port": config.MESH_PORT,
            })

        @self.app.route("/api/mesh/sync-users", methods=["POST"])
        def mesh_sync():
            if not _check_mesh_secret():
                return jsonify({"error": "unauthorized"}), 403
            data = request.get_json()
            server_id = data.get("server_id")
            users = data.get("users", [])
            host = data.get("host")
            port = data.get("port")
            if server_id:
                self.mesh.update_remote_users(server_id, users)
                if host and port:
                    self.mesh.touch_peer(server_id, host, port)
                self._broadcast_users(sync=False)
            return jsonify({"status": "ok"})

        @self.app.route("/api/mesh/forward", methods=["POST"])
        def mesh_forward():
            if not _check_mesh_secret():
                return jsonify({"error": "unauthorized"}), 403
            data = request.get_json()
            event = data.get("event")
            payload = data.get("data", {})
            target = payload.get("target")
            if target and target in self.clients:
                self.sio.emit(event, payload, room=target)
            return jsonify({"status": "ok"})

        @self.app.route("/api/mesh/broadcast", methods=["POST"])
        def mesh_broadcast_recv():
            if not _check_mesh_secret():
                return jsonify({"error": "unauthorized"}), 403
            data = request.get_json()
            event = data.get("event")
            payload = data.get("data", {})
            self.sio.emit(event, payload)
            return jsonify({"status": "ok"})

        # ── WebRTC Monitoring & Diagnostics API ──────────────────────────

        @self.app.route("/api/rtc/diagnostics")
        def rtc_diagnostics():
            """Full WebRTC diagnostics dashboard data."""
            if not session.get("admin"):
                return jsonify({"error": "unauthorized"}), 403
            return jsonify({
                "signaling": self.signaling.get_stats(),
                "turn": self.turn_server.get_stats(),
                "sfu": self.sfu.get_stats(),
                "active_calls": self.signaling.get_active_calls(),
            })

        @self.app.route("/api/rtc/call-logs")
        def rtc_call_logs():
            """Recent call logs with ICE diagnostics."""
            if not session.get("admin"):
                return jsonify({"error": "unauthorized"}), 403
            limit = request.args.get("limit", 50, type=int)
            return jsonify({"logs": self.signaling.get_call_logs(limit)})

        @self.app.route("/api/rtc/turn-credentials")
        def rtc_turn_credentials():
            """Get fresh TURN credentials (time-limited)."""
            username = request.args.get("username")
            return jsonify(self.turn_server.get_ice_server_config(self.host_ip, username))

        @self.app.route("/api/rtc/turn-stats")
        def rtc_turn_stats():
            """TURN server statistics."""
            if not session.get("admin"):
                return jsonify({"error": "unauthorized"}), 403
            return jsonify(self.turn_server.get_stats())

        @self.app.route("/api/rtc/sfu-stats")
        def rtc_sfu_stats():
            """SFU room statistics."""
            if not session.get("admin"):
                return jsonify({"error": "unauthorized"}), 403
            return jsonify(self.sfu.get_stats())

    def _setup_events(self):
        @self.sio.on("connect")
        def on_connect():
            sid = request.sid
            self.clients[sid] = {
                "sid": sid, "username": None,
                "ip": request.remote_addr,
                "connected_at": datetime.utcnow().isoformat(),
                "status": "online",
            }
            # Full ICE config: STUN + TURN (UDP/TCP/TLS) with credentials
            ice_config = self.turn_server.get_ice_server_config(self.host_ip)
            # Add STUN on all other interfaces
            for iface in self.detector.interfaces:
                stun_url = f"stun:{iface['ip']}:{self.turn_server.port}"
                if not any(stun_url in str(s.get("urls", "")) for s in ice_config["iceServers"]):
                    ice_config["iceServers"].insert(0, {"urls": stun_url})
            emit("server_info", {
                "server_id": self.server_id,
                "ice_servers": ice_config["iceServers"],
                "sfu_available": True,
                "is_fiber": self.is_fiber,
                "networks": [{"ip": i["ip"], "type": i["type"], "name": i["name"]} for i in self.detector.interfaces],
            })

        @self.sio.on("disconnect")
        def on_disconnect():
            sid = request.sid
            client = self.clients.pop(sid, {})
            name = client.get("username")
            if name:
                still_online = any(c.get("username") == name for c in self.clients.values())
                if not still_online:
                    self.db.set_offline(name)
                self._log(f"Disconnected: {name}")
            self.signaling.handle_disconnect(sid, username=name)
            self.sfu.handle_disconnect(sid)
            # Notify typing recipients that this user stopped typing
            ts = self.typing_state.pop(sid, None)
            if ts and name:
                target_sid = ts.get("target_sid")
                room_id = ts.get("room_id")
                if target_sid and target_sid in self.clients:
                    self.sio.emit("user_stop_typing", {"username": name, "room_id": None}, room=target_sid)
                elif room_id:
                    members = self.db.get_room_members(room_id)
                    for csid, cl in self.clients.items():
                        if cl.get("username") in members and csid != sid:
                            self.sio.emit("user_stop_typing", {"username": name, "room_id": room_id}, room=csid)
            self.sio.emit("user_offline", {"sid": sid, "username": name})
            self._broadcast_users()

        # --- Auth events ---
        @self.sio.on("auth_register")
        def on_register(data):
            sid = request.sid
            ip = request.remote_addr
            if not self._check_rate(ip):
                emit("auth_result", {"ok": False, "error": "محاولات كثيرة، انتظر دقيقة"})
                return
            self._record_attempt(ip)
            username = (data.get("username") or "").strip()
            password = data.get("password", "")
            if not username or not password:
                emit("auth_result", {"ok": False, "error": "الاسم وكلمة المرور مطلوبين"})
                return
            if len(username) < 2:
                emit("auth_result", {"ok": False, "error": "الاسم قصير جداً"})
                return
            if len(username) > 30:
                emit("auth_result", {"ok": False, "error": "الاسم طويل جداً"})
                return
            if not re.match(r'^[\w\u0600-\u06FF\u0750-\u077F\s\-]+$', username):
                emit("auth_result", {"ok": False, "error": "الاسم يحتوي على رموز غير مسموحة"})
                return
            if len(password) < 4:
                emit("auth_result", {"ok": False, "error": "كلمة المرور قصيرة جداً (4 أحرف على الأقل)"})
                return
            if self.db.register_user(username, password):
                token = self._gen_token(username)
                self.clients[sid]["username"] = username
                self.clients[sid]["status"] = "online"
                self.db.set_status(username, "online")
                self.signaling.register_session(username, sid)
                self._log(f"Registered: {username}")
                rooms = self.db.get_user_rooms(username)
                role = self.db.get_user_role(username)
                emit("auth_result", {"ok": True, "username": username, "rooms": rooms, "token": token, "role": role})
                self._broadcast_users()
            else:
                emit("auth_result", {"ok": False, "error": "الاسم مستخدم بالفعل"})

        @self.sio.on("auth_login")
        def on_login(data):
            sid = request.sid
            ip = request.remote_addr
            if not self._check_rate(ip):
                emit("auth_result", {"ok": False, "error": "محاولات كثيرة، انتظر دقيقة"})
                return
            self._record_attempt(ip)
            username = (data.get("username") or "").strip()
            password = data.get("password", "")
            if not username or not password:
                emit("auth_result", {"ok": False, "error": "الاسم وكلمة المرور مطلوبين"})
                return
            auth = self.db.authenticate(username, password)
            if auth is None:
                emit("auth_result", {"ok": False, "error": "تم حظر هذا الحساب"})
            elif auth:
                token = self._gen_token(username)
                self.clients[sid]["username"] = username
                self.clients[sid]["status"] = "online"
                self.db.set_status(username, "online")
                self.signaling.register_session(username, sid)
                self._log(f"Logged in: {username}")
                rooms = self.db.get_user_rooms(username)
                role = self.db.get_user_role(username)
                emit("auth_result", {"ok": True, "username": username, "rooms": rooms, "token": token, "role": role})
                self._broadcast_users()
                # Deliver offline messages
                self._deliver_offline_messages(sid, username)
            else:
                self._log(f"Failed login: {username} from {ip}", "warning")
                emit("auth_result", {"ok": False, "error": "اسم المستخدم أو كلمة المرور خطأ"})

        @self.sio.on("auth_token")
        def on_token_auth(data):
            sid = request.sid
            token = data.get("token", "")
            username = self._get_token_user(token)
            if username and self.db.is_banned(username):
                emit("auth_result", {"ok": False, "error": "تم حظر هذا الحساب", "token_expired": True})
                return
            if username and self.db.user_exists(username):
                self.clients[sid]["username"] = username
                self.clients[sid]["status"] = "online"
                self.db.set_status(username, "online")
                self.signaling.register_session(username, sid)
                self._log(f"Token resume: {username}")
                rooms = self.db.get_user_rooms(username)
                role = self.db.get_user_role(username)
                emit("auth_result", {"ok": True, "username": username, "rooms": rooms, "token": token, "role": role})
                self._broadcast_users()
                # Deliver offline messages
                self._deliver_offline_messages(sid, username)
            else:
                emit("auth_result", {"ok": False, "error": "الجلسة انتهت، سجل دخول مرة ثانية", "token_expired": True})

        @self.sio.on("auth_logout")
        def on_logout(data):
            sid = request.sid
            token = data.get("token", "")
            self.auth_tokens.pop(token, None)
            client = self.clients.get(sid, {})
            name = client.get("username")
            if name:
                self.db.set_offline(name)
                self.clients[sid]["username"] = None
                self._log(f"Logged out: {name}")
                self._broadcast_users()
            emit("logged_out", {})

        # --- Room events ---
        @self.sio.on("create_room")
        def on_create_room(data):
            sid = request.sid
            client = self.clients.get(sid, {})
            username = client.get("username")
            if not username:
                return
            name = (data.get("name") or "").strip()
            desc = (data.get("description") or "").strip()
            if not name:
                emit("room_error", {"error": "اسم الغرفة مطلوب"})
                return
            room_id = self.db.create_room(name, desc, username)
            if room_id:
                self._log(f"Room created: {name} by {username}")
                rooms = self.db.get_user_rooms(username)
                emit("rooms_updated", {"rooms": rooms})
                self.sio.emit("room_created", {"id": room_id, "name": name, "description": desc})
            else:
                emit("room_error", {"error": "الغرفة موجودة بالفعل"})

        @self.sio.on("join_room_req")
        def on_join_room(data):
            sid = request.sid
            client = self.clients.get(sid, {})
            username = client.get("username")
            if not username:
                return
            room_id = data.get("room_id")
            if room_id and self.db.join_room(room_id, username):
                rooms = self.db.get_user_rooms(username)
                emit("rooms_updated", {"rooms": rooms})

        @self.sio.on("leave_room_req")
        def on_leave_room(data):
            sid = request.sid
            client = self.clients.get(sid, {})
            username = client.get("username")
            if not username:
                return
            room_id = data.get("room_id")
            if room_id:
                self.db.leave_room(room_id, username)
                rooms = self.db.get_user_rooms(username)
                emit("rooms_updated", {"rooms": rooms})

        @self.sio.on("get_room_history")
        def on_room_history(data):
            sid = request.sid
            client = self.clients.get(sid, {})
            username = client.get("username")
            room_id = data.get("room_id")
            before_id = data.get("before_id")
            if room_id and username:
                members = self.db.get_room_members(room_id)
                if username not in members:
                    return
                msgs = self.db.get_messages(room_id=room_id, limit=50, before_id=before_id)
                self._attach_reply_info(msgs)
                files = self.db.get_files(room_id=room_id, limit=20) if not before_id else []
                has_more = len(msgs) == 50
                emit("room_history", {"room_id": room_id, "messages": msgs, "files": files, "before_id": before_id, "has_more": has_more})

        @self.sio.on("get_dm_history")
        def on_dm_history(data):
            sid = request.sid
            client = self.clients.get(sid, {})
            me = client.get("username")
            other = data.get("username")
            before_id = data.get("before_id")
            if me and other:
                msgs = self.db.get_dm_history(me, other, limit=50, before_id=before_id)
                self._attach_reply_info(msgs)
                has_more = len(msgs) == 50
                emit("dm_history", {"username": other, "messages": msgs, "before_id": before_id, "has_more": has_more})

        @self.sio.on("get_rooms_list")
        def on_get_rooms():
            rooms = self.db.get_rooms()
            emit("all_rooms", {"rooms": rooms})

        # --- Status ---
        @self.sio.on("set_status")
        def on_set_status(data):
            sid = request.sid
            client = self.clients.get(sid, {})
            username = client.get("username")
            status = data.get("status", "online")
            if username and status in ("online", "away", "busy"):
                self.clients[sid]["status"] = status
                self.db.set_status(username, status)
                self._broadcast_users()

        # --- Typing ---
        @self.sio.on("typing")
        def on_typing(data):
            sid = request.sid
            client = self.clients.get(sid, {})
            username = client.get("username")
            if not username:
                return
            target_sid = data.get("target_sid")
            room_id = data.get("room_id")
            self.typing_state[sid] = {"target_sid": target_sid, "room_id": room_id}
            if target_sid and target_sid in self.clients:
                self.sio.emit("user_typing", {"username": username, "room_id": None}, room=target_sid)
            elif room_id:
                members = self.db.get_room_members(room_id)
                for csid, cl in self.clients.items():
                    if cl.get("username") in members and csid != sid:
                        self.sio.emit("user_typing", {"username": username, "room_id": room_id}, room=csid)

        @self.sio.on("stop_typing")
        def on_stop_typing(data):
            sid = request.sid
            client = self.clients.get(sid, {})
            username = client.get("username")
            if not username:
                return
            self.typing_state.pop(sid, None)
            target_sid = data.get("target_sid")
            room_id = data.get("room_id")
            if target_sid and target_sid in self.clients:
                self.sio.emit("user_stop_typing", {"username": username, "room_id": None}, room=target_sid)
            elif room_id:
                members = self.db.get_room_members(room_id)
                for csid, cl in self.clients.items():
                    if cl.get("username") in members and csid != sid:
                        self.sio.emit("user_stop_typing", {"username": username, "room_id": room_id}, room=csid)

        # --- Chat ---
        @self.sio.on("chat_message")
        def on_msg(data):
            sid = request.sid
            client = self.clients.get(sid, {})
            sender = client.get("username")
            if not sender:
                return
            if not self._check_msg_rate(sid):
                emit("chat_error", {"error": "أنت ترسل بسرعة كبيرة، انتظر قليلاً"})
                return
            text = (data.get("text") or "").strip()
            if not text:
                return
            if len(text) > self._MAX_MSG_LEN:
                text = text[:self._MAX_MSG_LEN]
            target_user = data.get("target_user")
            room_id = data.get("room_id")
            reply_to = data.get("reply_to")
            encrypted = data.get("encrypted", False)

            if room_id:
                members = self.db.get_room_members(room_id)
                if sender not in members:
                    return

            result = self.db.save_message(sender, text, target=target_user, room_id=room_id, reply_to=reply_to, encrypted=encrypted)
            msg = {
                "id": result["id"], "sender": sender, "text": text,
                "target_user": target_user, "room_id": room_id,
                "reply_to": reply_to, "encrypted": encrypted,
                "timestamp": result["timestamp"],
            }
            if reply_to:
                ref = self.db.get_message(reply_to)
                if ref:
                    msg["reply_info"] = {"sender": ref["sender"], "text": ref["text"][:80]}

            if target_user:
                delivered = False
                for csid, cl in self.clients.items():
                    uname = cl.get("username")
                    if uname == target_user or (uname == sender and csid != sid):
                        self.sio.emit("chat_message", msg, room=csid)
                        if uname == target_user:
                            delivered = True
                emit("chat_message", msg)
                # Queue for offline delivery if target not online
                if not delivered and not self._is_user_online(target_user):
                    self.db.save_offline_message(target_user, "chat_message", msg)
            elif room_id:
                members = self.db.get_room_members(room_id)
                for csid, cl in self.clients.items():
                    if cl.get("username") in members:
                        self.sio.emit("chat_message", msg, room=csid)
            else:
                self.sio.emit("chat_message", msg)
                self.mesh.broadcast_to_peers("chat_message", msg)

        @self.sio.on("delete_message")
        def on_delete_msg(data):
            sid = request.sid
            client = self.clients.get(sid, {})
            username = client.get("username")
            msg_id = data.get("id")
            if username and msg_id:
                # Moderators and admins can delete any message
                if self.db.has_permission(username, 'delete_message'):
                    self.db.delete_message(msg_id)
                else:
                    self.db.delete_message(msg_id, username)
                self.sio.emit("message_deleted", {"id": msg_id})

        @self.sio.on("search_files")
        def on_search_files(data):
            sid = request.sid
            client = self.clients.get(sid, {})
            username = client.get("username")
            if not username:
                return
            query = (data.get("query") or "").strip()
            room_id = data.get("room_id")
            results = self.db.search_files(query, room_id=room_id)
            emit("file_search_results", {"query": query, "files": results})

        @self.sio.on("search_messages")
        def on_search(data):
            sid = request.sid
            client = self.clients.get(sid, {})
            username = client.get("username")
            if not username:
                return
            query = (data.get("query") or "").strip()
            room_id = data.get("room_id")
            if query and len(query) >= 2:
                if room_id:
                    members = self.db.get_room_members(room_id)
                    if username not in members:
                        return
                results = self.db.search_messages(query, room_id=room_id, username=username)
                emit("search_results", {"query": query, "results": results})

        @self.sio.on("change_password")
        def on_change_pw(data):
            sid = request.sid
            client = self.clients.get(sid, {})
            username = client.get("username")
            if not username:
                return
            old_pw = data.get("old_password", "")
            new_pw = data.get("new_password", "")
            if len(new_pw) < 4:
                emit("profile_result", {"ok": False, "error": "كلمة المرور قصيرة (4 أحرف على الأقل)"})
                return
            if self.db.change_password(username, old_pw, new_pw):
                emit("profile_result", {"ok": True, "msg": "تم تغيير كلمة المرور"})
            else:
                emit("profile_result", {"ok": False, "error": "كلمة المرور الحالية خطأ"})

        @self.sio.on("update_display_name")
        def on_display_name(data):
            sid = request.sid
            client = self.clients.get(sid, {})
            username = client.get("username")
            name = (data.get("display_name") or "").strip()
            if username and name:
                self.db.update_display_name(username, name)
                emit("profile_result", {"ok": True, "msg": "تم تحديث الاسم"})

        # --- E2E Public Key Exchange ---
        @self.sio.on("set_public_key")
        def on_set_public_key(data):
            sid = request.sid
            client = self.clients.get(sid, {})
            username = client.get("username")
            if not username:
                return
            public_key = data.get("public_key", "")
            if public_key:
                self.db.set_public_key(username, public_key)

        @self.sio.on("get_public_key")
        def on_get_public_key(data):
            target = data.get("username", "")
            if target:
                key = self.db.get_public_key(target)
                emit("public_key_response", {"username": target, "public_key": key})

        # --- Screen Share Signaling ---
        @self.sio.on("screen_share_start")
        def on_screen_start(data):
            target = data.get("target")
            if target and target in self.clients:
                self.sio.emit("screen_share_started", {
                    "sender": request.sid,
                    "sender_name": data.get("sender_name"),
                }, room=target)

        @self.sio.on("screen_share_stop")
        def on_screen_stop(data):
            target = data.get("target")
            if target and target in self.clients:
                self.sio.emit("screen_share_stopped", {
                    "sender": request.sid,
                }, room=target)

        @self.sio.on("screen_offer")
        def on_screen_offer(data):
            target = data.get("target")
            if target and target in self.clients:
                self.sio.emit("screen_offer", {
                    "sdp": data["sdp"], "type": data["type"],
                    "sender": request.sid, "target": target,
                }, room=target)

        @self.sio.on("screen_answer")
        def on_screen_answer(data):
            target = data.get("target")
            if target and target in self.clients:
                self.sio.emit("screen_answer", {
                    "sdp": data["sdp"], "type": data["type"],
                    "sender": request.sid, "target": target,
                }, room=target)

        @self.sio.on("screen_ice")
        def on_screen_ice(data):
            target = data.get("target")
            if target and target in self.clients:
                self.sio.emit("screen_ice", {
                    "candidate": data.get("candidate"),
                    "sender": request.sid, "target": target,
                }, room=target)

        # --- Group Call Signaling ---
        @self.sio.on("group_call_start")
        def on_group_call_start(data):
            sid = request.sid
            client = self.clients.get(sid, {})
            username = client.get("username")
            room_id = data.get("room_id")
            call_type = data.get("call_type", "audio")
            if not username or not room_id:
                return
            members = self.db.get_room_members(room_id)
            if username not in members:
                return
            room = self.db.get_room(room_id)
            # Register in signaling
            self.signaling.join_room(room_id, username, sid)
            # Notify all room members
            for csid, cl in self.clients.items():
                if cl.get("username") in members and csid != sid:
                    self.sio.emit("group_call_invite", {
                        "room_id": room_id,
                        "room_name": room["name"] if room else str(room_id),
                        "initiator": username,
                        "call_type": call_type,
                    }, room=csid)

        @self.sio.on("group_call_join")
        def on_group_call_join(data):
            sid = request.sid
            client = self.clients.get(sid, {})
            username = client.get("username")
            room_id = data.get("room_id")
            if not username or not room_id:
                return
            self.signaling.join_room(room_id, username, sid)
            # Get existing participants
            participants = self.signaling.get_room_users(room_id)
            # Notify user of existing participants
            emit("group_call_participants", {
                "room_id": room_id,
                "participants": [p for p in participants if p["sid"] != sid],
            })
            # Notify others that a new user joined
            for p in participants:
                if p["sid"] != sid:
                    self.sio.emit("group_call_peer_joined", {
                        "room_id": room_id,
                        "sid": sid,
                        "username": username,
                    }, room=p["sid"])

        @self.sio.on("group_call_leave")
        def on_group_call_leave(data):
            sid = request.sid
            client = self.clients.get(sid, {})
            username = client.get("username")
            room_id = data.get("room_id")
            if not room_id:
                return
            participants = self.signaling.get_room_users(room_id)
            self.signaling.leave_room(room_id, sid)
            for p in participants:
                if p["sid"] != sid:
                    self.sio.emit("group_call_peer_left", {
                        "room_id": room_id,
                        "sid": sid,
                        "username": username,
                    }, room=p["sid"])

        @self.sio.on("group_call_offer")
        def on_group_offer(data):
            target = data.get("target")
            if target and target in self.clients:
                self.sio.emit("group_call_offer", {
                    "sdp": data["sdp"], "type": data["type"],
                    "sender": request.sid, "room_id": data.get("room_id"),
                }, room=target)

        @self.sio.on("group_call_answer")
        def on_group_answer(data):
            target = data.get("target")
            if target and target in self.clients:
                self.sio.emit("group_call_answer", {
                    "sdp": data["sdp"], "type": data["type"],
                    "sender": request.sid, "room_id": data.get("room_id"),
                }, room=target)

        @self.sio.on("group_call_ice")
        def on_group_ice(data):
            target = data.get("target")
            if target and target in self.clients:
                self.sio.emit("group_call_ice", {
                    "candidate": data.get("candidate"),
                    "sender": request.sid, "room_id": data.get("room_id"),
                }, room=target)

        # --- WebRTC signaling ---
        @self.sio.on("call_request")
        def on_call_req(data):
            sid = request.sid
            target = data["target"]
            call_type = data.get("call_type", "video")
            # Create call in state machine (IDLE -> RINGING)
            call_id = self.signaling.create_call(sid, target, call_type)
            notify_incoming_call(data.get("sender_name", "?"), call_type)
            self._route_event("incoming_call", {
                "sender": sid,
                "sender_name": data.get("sender_name"),
                "call_type": call_type,
                "call_id": call_id,
                "target": target,
            }, target)

        @self.sio.on("call_accept")
        def on_call_accept(data):
            sid = request.sid
            target = data["target"]
            call_id = data.get("call_id")
            if call_id:
                self.signaling.accept_call(call_id)
            self._route_event("call_accepted", {
                "sender": sid,
                "call_id": call_id,
                "target": target,
            }, target)

        @self.sio.on("call_reject")
        def on_call_reject(data):
            sid = request.sid
            target = data["target"]
            call_id = data.get("call_id")
            if call_id:
                self.signaling.end_call(call_id, reason="rejected")
            self._route_event("call_rejected", {
                "sender": sid,
                "call_id": call_id,
                "target": target,
            }, target)

        @self.sio.on("call_end")
        def on_call_end(data):
            target = data.get("target")
            call_id = data.get("call_id")
            if call_id:
                self.signaling.end_call(call_id)
            if target:
                self._route_event("call_ended", {
                    "sender": request.sid,
                    "call_id": call_id,
                    "target": target,
                }, target)

        @self.sio.on("webrtc_offer")
        def on_offer(data):
            call_id = data.get("call_id")
            if call_id:
                self.signaling.call_connecting(call_id)
            # Use reliable signaling with ACK
            self.signaling.send_reliable("webrtc_offer", {
                "sdp": data["sdp"], "type": data["type"],
                "sender": request.sid, "target": data["target"],
                "call_id": call_id,
            }, data["target"], sender_sid=request.sid)

        @self.sio.on("webrtc_answer")
        def on_answer(data):
            self.signaling.send_reliable("webrtc_answer", {
                "sdp": data["sdp"], "type": data["type"],
                "sender": request.sid, "target": data["target"],
                "call_id": data.get("call_id"),
            }, data["target"], sender_sid=request.sid)

        @self.sio.on("webrtc_ice")
        def on_ice(data):
            call_id = data.get("call_id")
            if call_id:
                self.signaling.record_ice_candidate(call_id, request.sid, data.get("candidate"))
            self.signaling.send_reliable("webrtc_ice", {
                "candidate": data.get("candidate"),
                "sender": request.sid, "target": data["target"],
                "call_id": call_id,
            }, data["target"], sender_sid=request.sid)

    def _deliver_offline_messages(self, sid, username):
        """Deliver queued offline messages to a user who just came online."""
        try:
            messages = self.db.get_offline_messages(username)
            for msg in messages:
                self.sio.emit(msg["event_type"], msg["payload"], room=sid)
        except Exception as e:
            logger.warning(f"Offline message delivery error: {e}")

    def _is_user_online(self, username):
        """Check if a user is currently connected."""
        return any(c.get("username") == username for c in self.clients.values())

    def _route_event(self, event, data, target_sid):
        if target_sid in self.clients:
            self.sio.emit(event, data, room=target_sid)
        else:
            server_id = self.mesh.find_user_server(target_sid)
            if server_id:
                self.mesh.forward_to_peer(server_id, event, data)

    def _attach_reply_info(self, msgs):
        """Attach reply_info to messages that have reply_to."""
        for m in msgs:
            if m.get("reply_to"):
                ref = self.db.get_message(m["reply_to"])
                if ref:
                    m["reply_info"] = {"sender": ref["sender"], "text": ref["text"][:80]}

    def _broadcast_users(self, sync=True):
        local_users = []
        for c in self.clients.values():
            if c["username"]:
                local_users.append({
                    "sid": c["sid"], "username": c["username"],
                    "status": c.get("status", "online"),
                })
        remote_users = self.mesh.get_all_remote_users()
        all_users = local_users + remote_users
        self.sio.emit("users_online", {"users": all_users})
        if sync:
            self.mesh.sync_users(local_users)

    def run(self, host=None, port=None, silent=True):
        host = host or config.SERVER_HOST
        port = port or config.SERVER_PORT

        if silent:
            h = logging.FileHandler(config.LOG_FILE)
        else:
            h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logging.root.addHandler(h)
        logging.root.setLevel(getattr(logging, config.LOG_LEVEL))

        self.mesh.start()
        self._log(f"Server started: {self.server_id}")

        # Start local TURN/STUN server (WebRTC without internet)
        self.turn_server.start()
        self._log("Local STUN/TURN server started")

        # Start mDNS/Zeroconf discovery (auto-find peers)
        def _on_mdns_peer_found(peer_info):
            self._log(f"mDNS discovered: {peer_info['server_id']} at {peer_info['host']}:{peer_info['port']}")
            self.mesh.connect_to(peer_info["host"], peer_info["port"])
            self.ws_mesh.connect_to_peer(peer_info["host"], peer_info["port"])

        def _on_mdns_peer_lost(peer_info):
            self._log(f"mDNS peer lost: {peer_info.get('server_id', '?')}")

        self.discovery.start(on_peer_found=_on_mdns_peer_found, on_peer_lost=_on_mdns_peer_lost)

        # Start WebSocket mesh bridge (persistent connections)
        def _on_ws_message(data):
            event = data.get("type")
            if event == "user_sync":
                peer_id = data.get("_from_peer")
                users = data.get("users", [])
                if peer_id:
                    self.mesh.update_remote_users(peer_id, users)
                    self._broadcast_users(sync=False)
            elif event == "chat_forward":
                self.sio.emit("chat_message", data.get("message", {}))

        self.ws_mesh.start(on_message=_on_ws_message)

        # Generate QR code for easy connection
        client_url = f"http://{self.host_ip}:{port}/client"
        self._qr_b64 = generate_qr_code(client_url)
        self._log("QR code generated for client connection")

        # Start scheduled tasks (auto-backup, cleanup)
        self._scheduler = init_scheduler(self.db, config.UPLOAD_FOLDER, self.backup_dir)

        # Desktop notification
        notify_server_started(self.host_ip, port)

        if not silent:
            net_lines = ""
            for iface in self.detector.interfaces:
                net_lines += f"    {iface['name']:12s} {iface['ip']:16s} ({iface['type']})\n"
            if not net_lines:
                net_lines = f"    {'auto':12s} {self.host_ip:16s}\n"
            print(f"""
  Helen WiFi - هيلين WiFi (LAN Only / Multi-Network)
  Server ID : {self.server_id}
  Primary IP: {self.host_ip}:{port}
  Networks  :
{net_lines}  Fiber     : {'Yes' if self.is_fiber else 'No'}
  Database  : {config.DB_PATH}
  Client    : http://{self.host_ip}:{port}/client
  Admin     : http://{self.host_ip}:{port}/admin
  QR Code   : http://{self.host_ip}:{port}/api/qr-code
  STUN/TURN : stun:{self.host_ip}:3478 | turn:UDP/TCP:3478
  SFU       : Active (relay media server)
  Diagnostics: http://{self.host_ip}:{port}/api/rtc/diagnostics
  WS Mesh   : ws://{self.host_ip}:{port + 2}
  mDNS      : Active (auto-discovery on all networks)
""")

        if getattr(sys, 'frozen', False):
            threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}/client")).start()

        try:
            self.sio.run(self.app, host=host, port=port, debug=False, log_output=not silent)
        finally:
            self.turn_server.stop()
            self.discovery.stop()
            self.ws_mesh.stop()
            shutdown_scheduler()


def create_app():
    return BROServer()
