"""
Helen WiFi - Main Server
Chat + Voice/Video Calls + File Sharing + Rooms + Auth + Mesh + Admin
"""
import os
import sys
import uuid
import time
import hmac
import hashlib
import logging
import threading
import webbrowser
from datetime import datetime
from functools import wraps
from collections import defaultdict

from flask import (Flask, render_template, request, jsonify,
                   send_from_directory, session, redirect, url_for)
from flask_socketio import SocketIO, emit
from flask_cors import CORS
from werkzeug.utils import secure_filename

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from network.detector import NetworkDetector
from mesh.mesh_node import MeshNode
from server.signaling import SignalingServer
from database.db import Database

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
        self.app.config["MAX_CONTENT_LENGTH"] = None
        CORS(self.app)

        # Database
        self.db = Database(config.DB_PATH)

        # Restore persisted admin password if changed
        saved_pw = self.db.get_setting("admin_password")
        if saved_pw:
            config.ADMIN_PASSWORD = saved_pw

        # Network
        self.detector = NetworkDetector()
        self.detector.detect_all()
        best = self.detector.get_best_interface()
        self.host_ip = best["ip"] if best else "0.0.0.0"
        self.is_fiber = self.detector.has_fiber()

        # SocketIO
        self.sio = SocketIO(self.app, cors_allowed_origins="*", async_mode="eventlet",
                            max_http_buffer_size=1e300, ping_timeout=60, ping_interval=25)

        # Mesh + Signaling
        self.mesh = MeshNode(self.server_id, self.host_ip, config.SERVER_PORT, config.MESH_PORT)
        self.signaling = SignalingServer(self.sio)

        # State (online sessions)
        self.clients = {}       # {sid: {sid, username, ip, connected_at, status}}
        self.auth_tokens = {}   # {token: username}  - session persistence
        self.logs = []
        self.typing_state = {}  # {sid: {target, username, timestamp}}

        # Brute force protection: {ip: [timestamps]}
        self._auth_attempts = defaultdict(list)
        self._AUTH_MAX = 5          # max attempts
        self._AUTH_WINDOW = 60      # per 60 seconds

        self._setup_routes()
        self._setup_events()

    def _gen_token(self, username):
        raw = f"{username}:{config.SECRET_KEY}:{uuid.uuid4().hex}"
        token = hmac.new(config.SECRET_KEY.encode(), raw.encode(), hashlib.sha256).hexdigest()
        self.auth_tokens[token] = username
        return token

    def _check_rate(self, ip):
        now = time.time()
        attempts = self._auth_attempts[ip]
        self._auth_attempts[ip] = [t for t in attempts if now - t < self._AUTH_WINDOW]
        return len(self._auth_attempts[ip]) < self._AUTH_MAX

    def _record_attempt(self, ip):
        self._auth_attempts[ip].append(time.time())

    def _log(self, msg, level="info"):
        self.logs.append({"time": datetime.utcnow().isoformat(), "level": level, "message": msg})
        if len(self.logs) > 500:
            self.logs = self.logs[-500:]

    def _require_admin(self, f):
        @wraps(f)
        def w(*a, **kw):
            if not session.get("admin"):
                return redirect(url_for("login"))
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
        @self.app.route("/login", methods=["GET", "POST"])
        def login():
            if request.method == "POST":
                if (request.form.get("username") == config.ADMIN_USERNAME and
                        request.form.get("password") == config.ADMIN_PASSWORD):
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
            return render_template("admin.html")

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
                "logs": self.logs[-50:],
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
            # Kick from active sessions
            for sid, cl in list(self.clients.items()):
                if cl.get("username") == username:
                    self.sio.emit("force_disconnect", {"reason": "تم حظرك"}, room=sid)
            # Remove auth tokens
            self.auth_tokens = {t: u for t, u in self.auth_tokens.items() if u != username}
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
            self._log(f"Admin kicked: {username}", "warning")
            return jsonify({"status": "ok"})

        @self.app.route("/api/admin/users/<username>/delete", methods=["DELETE"])
        @self._require_admin
        def api_delete_user(username):
            # Kick first
            for sid, cl in list(self.clients.items()):
                if cl.get("username") == username:
                    self.sio.emit("force_disconnect", {"reason": "تم حذف حسابك"}, room=sid)
            self.auth_tokens = {t: u for t, u in self.auth_tokens.items() if u != username}
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

        # --- Admin: Room Management ---
        @self.app.route("/api/admin/rooms/<int:room_id>", methods=["DELETE"])
        @self._require_admin
        def api_delete_room(room_id):
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
            if old != config.ADMIN_PASSWORD:
                return jsonify({"error": "كلمة المرور الحالية خطأ"}), 400
            if len(new) < 4:
                return jsonify({"error": "كلمة المرور الجديدة قصيرة"}), 400
            config.ADMIN_PASSWORD = new
            self.db.set_setting("admin_password", new)
            self._log("Admin password changed")
            return jsonify({"status": "ok"})

        # --- Files ---
        @self.app.route("/api/upload", methods=["POST"])
        def upload():
            f = request.files.get("file")
            if not f or not f.filename:
                return jsonify({"error": "No file"}), 400
            original = f.filename
            safe = secure_filename(original) or "file"
            ext = safe.rsplit('.', 1)[-1].lower() if '.' in safe else ''
            if ext and ext not in ALLOWED_EXTENSIONS:
                return jsonify({"error": f"نوع الملف غير مسموح: .{ext}"}), 400
            name = f"{int(time.time())}_{safe}"
            f.save(os.path.join(config.UPLOAD_FOLDER, name))
            size = os.path.getsize(os.path.join(config.UPLOAD_FOLDER, name))
            uploaded_by = request.form.get("username", "?")
            room_id = request.form.get("room_id", type=int)
            target_user = request.form.get("target_user")

            self.db.save_file(original, name, size, uploaded_by, room_id)
            info = {
                "name": f.filename, "saved_as": name,
                "size": size,
                "uploaded_by": uploaded_by,
                "uploaded_at": datetime.utcnow().isoformat(),
                "room_id": room_id,
                "target_user": target_user,
            }
            self._log(f"File: {f.filename}")
            if room_id:
                members = self.db.get_room_members(room_id)
                for sid, cl in self.clients.items():
                    if cl.get("username") in members:
                        self.sio.emit("file_shared", info, room=sid)
            elif target_user:
                # DM file - send only to target and sender
                for sid, cl in self.clients.items():
                    if cl.get("username") in (target_user, uploaded_by):
                        self.sio.emit("file_shared", info, room=sid)
            else:
                self.sio.emit("file_shared", info)
            return jsonify({"status": "ok", "file": info})

        @self.app.route("/api/download/<filename>")
        def download(filename):
            safe = secure_filename(filename)
            if not safe or safe != filename:
                return jsonify({"error": "اسم ملف غير صالح"}), 400
            fpath = os.path.join(config.UPLOAD_FOLDER, safe)
            if not os.path.isfile(fpath):
                return jsonify({"error": "الملف غير موجود"}), 404
            return send_from_directory(config.UPLOAD_FOLDER, safe)

        @self.app.route("/api/files")
        def list_files():
            room_id = request.args.get("room_id", type=int)
            return jsonify({"files": self.db.get_files(room_id=room_id)})

        @self.app.route("/api/ice-config")
        def ice_config():
            return jsonify({"iceServers": config.ICE_SERVERS})

        # --- Mesh Inter-server API ---
        @self.app.route("/api/mesh/info")
        def mesh_info():
            return jsonify({
                "server_id": self.server_id,
                "host": self.host_ip,
                "port": config.SERVER_PORT,
                "mesh_port": config.MESH_PORT,
            })

        @self.app.route("/api/mesh/sync-users", methods=["POST"])
        def mesh_sync():
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
            data = request.get_json()
            event = data.get("event")
            payload = data.get("data", {})
            target = payload.get("target")
            if target and target in self.clients:
                self.sio.emit(event, payload, room=target)
            return jsonify({"status": "ok"})

        @self.app.route("/api/mesh/broadcast", methods=["POST"])
        def mesh_broadcast_recv():
            data = request.get_json()
            event = data.get("event")
            payload = data.get("data", {})
            self.sio.emit(event, payload)
            return jsonify({"status": "ok"})

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
            emit("server_info", {
                "server_id": self.server_id,
                "ice_servers": config.ICE_SERVERS,
                "is_fiber": self.is_fiber,
            })

        @self.sio.on("disconnect")
        def on_disconnect():
            sid = request.sid
            client = self.clients.pop(sid, {})
            name = client.get("username")
            if name:
                # Only set offline if no other sessions for this user
                still_online = any(c.get("username") == name for c in self.clients.values())
                if not still_online:
                    self.db.set_offline(name)
                self._log(f"Disconnected: {name}")
            self.signaling.handle_disconnect(sid)
            self.typing_state.pop(sid, None)
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
            if len(password) < 4:
                emit("auth_result", {"ok": False, "error": "كلمة المرور قصيرة جداً (4 أحرف على الأقل)"})
                return
            if self.db.register_user(username, password):
                token = self._gen_token(username)
                self.clients[sid]["username"] = username
                self.clients[sid]["status"] = "online"
                self.db.set_status(username, "online")
                self._log(f"Registered: {username}")
                rooms = self.db.get_user_rooms(username)
                emit("auth_result", {"ok": True, "username": username, "rooms": rooms, "token": token})
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
                self._log(f"Logged in: {username}")
                rooms = self.db.get_user_rooms(username)
                emit("auth_result", {"ok": True, "username": username, "rooms": rooms, "token": token})
                self._broadcast_users()
            else:
                self._log(f"Failed login: {username} from {ip}", "warning")
                emit("auth_result", {"ok": False, "error": "اسم المستخدم أو كلمة المرور خطأ"})

        @self.sio.on("auth_token")
        def on_token_auth(data):
            sid = request.sid
            token = data.get("token", "")
            username = self.auth_tokens.get(token)
            if username and self.db.is_banned(username):
                emit("auth_result", {"ok": False, "error": "تم حظر هذا الحساب", "token_expired": True})
                return
            if username and self.db.user_exists(username):
                self.clients[sid]["username"] = username
                self.clients[sid]["status"] = "online"
                self.db.set_status(username, "online")
                self._log(f"Token resume: {username}")
                rooms = self.db.get_user_rooms(username)
                emit("auth_result", {"ok": True, "username": username, "rooms": rooms, "token": token})
                self._broadcast_users()
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
                # Notify all users about new room
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
            room_id = data.get("room_id")
            if room_id:
                msgs = self.db.get_messages(room_id=room_id, limit=50)
                self._attach_reply_info(msgs)
                files = self.db.get_files(room_id=room_id, limit=20)
                emit("room_history", {"room_id": room_id, "messages": msgs, "files": files})

        @self.sio.on("get_dm_history")
        def on_dm_history(data):
            sid = request.sid
            client = self.clients.get(sid, {})
            me = client.get("username")
            other = data.get("username")
            if me and other:
                msgs = self.db.get_dm_history(me, other, limit=50)
                self._attach_reply_info(msgs)
                emit("dm_history", {"username": other, "messages": msgs})

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
            sender = client.get("username", data.get("sender", "?"))
            if not sender or sender == "?":
                return
            text = data.get("text", "")
            target_user = data.get("target_user")
            room_id = data.get("room_id")
            reply_to = data.get("reply_to")

            # Verify room membership
            if room_id:
                members = self.db.get_room_members(room_id)
                if sender not in members:
                    return

            result = self.db.save_message(sender, text, target=target_user, room_id=room_id, reply_to=reply_to)
            msg = {
                "id": result["id"], "sender": sender, "text": text,
                "target_user": target_user, "room_id": room_id,
                "reply_to": reply_to, "timestamp": result["timestamp"],
            }
            # Attach reply info
            if reply_to:
                ref = self.db.get_message(reply_to)
                if ref:
                    msg["reply_info"] = {"sender": ref["sender"], "text": ref["text"][:80]}

            if target_user:
                for csid, cl in self.clients.items():
                    if cl.get("username") == target_user and cl.get("username") != sender:
                        self.sio.emit("chat_message", msg, room=csid)
                emit("chat_message", msg)
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
                self.db.delete_message(msg_id, username)
                self.sio.emit("message_deleted", {"id": msg_id})

        @self.sio.on("search_messages")
        def on_search(data):
            query = (data.get("query") or "").strip()
            room_id = data.get("room_id")
            if query and len(query) >= 2:
                results = self.db.search_messages(query, room_id=room_id)
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

        # --- WebRTC signaling ---
        @self.sio.on("call_request")
        def on_call_req(data):
            self._route_event("incoming_call", {
                "sender": request.sid,
                "sender_name": data.get("sender_name"),
                "call_type": data.get("call_type", "video"),
                "target": data["target"],
            }, data["target"])

        @self.sio.on("call_accept")
        def on_call_accept(data):
            self._route_event("call_accepted", {
                "sender": request.sid,
                "target": data["target"],
            }, data["target"])

        @self.sio.on("call_reject")
        def on_call_reject(data):
            self._route_event("call_rejected", {
                "sender": request.sid,
                "target": data["target"],
            }, data["target"])

        @self.sio.on("call_end")
        def on_call_end(data):
            target = data.get("target")
            if target:
                self._route_event("call_ended", {
                    "sender": request.sid,
                    "target": target,
                }, target)

        @self.sio.on("webrtc_offer")
        def on_offer(data):
            self._route_event("webrtc_offer", {
                "sdp": data["sdp"], "type": data["type"],
                "sender": request.sid, "target": data["target"],
            }, data["target"])

        @self.sio.on("webrtc_answer")
        def on_answer(data):
            self._route_event("webrtc_answer", {
                "sdp": data["sdp"], "type": data["type"],
                "sender": request.sid, "target": data["target"],
            }, data["target"])

        @self.sio.on("webrtc_ice")
        def on_ice(data):
            self._route_event("webrtc_ice", {
                "candidate": data.get("candidate"),
                "sender": request.sid, "target": data["target"],
            }, data["target"])

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

        if not silent:
            print(f"""
  Helen WiFi - هيلين WiFi
  Server ID : {self.server_id}
  IP        : {self.host_ip}:{port}
  Fiber     : {'Yes' if self.is_fiber else 'No'}
  Database  : {config.DB_PATH}
  Client    : http://{self.host_ip}:{port}/client
  Admin     : http://{self.host_ip}:{port}/admin
""")

        if getattr(sys, 'frozen', False):
            threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}/client")).start()

        self.sio.run(self.app, host=host, port=port, debug=False, log_output=not silent)


def create_app():
    return BROServer()
