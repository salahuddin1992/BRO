"""
Helen WiFi - Main Server
Chat + Voice/Video Calls + File Sharing + Mesh + Admin
"""
import os
import sys
import uuid
import time
import logging
import threading
import webbrowser
from datetime import datetime
from functools import wraps

from flask import (Flask, render_template, request, jsonify,
                   send_from_directory, session, redirect, url_for)
from flask_socketio import SocketIO, emit
from flask_cors import CORS

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from network.detector import NetworkDetector
from mesh.mesh_node import MeshNode
from server.signaling import SignalingServer

logger = logging.getLogger("HelenWiFi")


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

        # State
        self.clients = {}       # {sid: {sid, username, ip, connected_at}}
        self.messages = []
        self.files = []
        self.logs = []

        self._setup_routes()
        self._setup_events()

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
            return jsonify({
                "server_id": self.server_id,
                "uptime": uptime,
                "host_ip": self.host_ip,
                "port": config.SERVER_PORT,
                "is_fiber": self.is_fiber,
                "clients_count": len(self.clients),
                "clients": list(self.clients.values()),
                "messages_count": len(self.messages),
                "messages": self.messages[-50:],
                "files_count": len(self.files),
                "files": self.files,
                "network": self.detector.to_dict_list(),
                "mesh": self.mesh.get_stats(),
                "signaling": self.signaling.get_stats(),
                "fiber_types": config.FIBER_TYPES,
                "logs": self.logs[-50:],
            })

        @self.app.route("/api/admin/mesh/connect", methods=["POST"])
        @self._require_admin
        def api_mesh_connect():
            data = request.get_json()
            self.mesh.connect_to(data.get("host"), int(data.get("port", config.MESH_PORT)))
            return jsonify({"status": "ok"})

        # --- Files ---
        @self.app.route("/api/upload", methods=["POST"])
        def upload():
            f = request.files.get("file")
            if not f or not f.filename:
                return jsonify({"error": "No file"}), 400
            name = f"{int(time.time())}_{f.filename}"
            f.save(os.path.join(config.UPLOAD_FOLDER, name))
            info = {
                "name": f.filename, "saved_as": name,
                "size": os.path.getsize(os.path.join(config.UPLOAD_FOLDER, name)),
                "uploaded_by": request.form.get("username", "?"),
                "uploaded_at": datetime.utcnow().isoformat(),
            }
            self.files.append(info)
            self._log(f"File: {f.filename}")
            self.sio.emit("file_shared", info)
            return jsonify({"status": "ok", "file": info})

        @self.app.route("/api/download/<filename>")
        def download(filename):
            return send_from_directory(config.UPLOAD_FOLDER, filename)

        @self.app.route("/api/files")
        def list_files():
            return jsonify({"files": self.files})

        @self.app.route("/api/ice-config")
        def ice_config():
            return jsonify({"iceServers": config.ICE_SERVERS})

    def _setup_events(self):
        @self.sio.on("connect")
        def on_connect():
            sid = request.sid
            self.clients[sid] = {
                "sid": sid, "username": None,
                "ip": request.remote_addr,
                "connected_at": datetime.utcnow().isoformat(),
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
            name = client.get("username", sid)
            self._log(f"Disconnected: {name}")
            self.signaling.handle_disconnect(sid)
            self.sio.emit("user_offline", {"sid": sid, "username": name})
            self._broadcast_users()

        @self.sio.on("register")
        def on_register(data):
            sid = request.sid
            name = data.get("username", f"User-{sid[:6]}")
            if sid in self.clients:
                self.clients[sid]["username"] = name
            self._log(f"Joined: {name}")
            self._broadcast_users()

        @self.sio.on("chat_message")
        def on_msg(data):
            msg = {
                "sender": data.get("sender", "?"),
                "text": data.get("text", ""),
                "target": data.get("target"),
                "timestamp": datetime.utcnow().isoformat(),
            }
            self.messages.append(msg)
            if msg["target"]:
                emit("chat_message", msg, room=msg["target"])
                emit("chat_message", msg)
            else:
                self.sio.emit("chat_message", msg)

        # WebRTC signaling events
        @self.sio.on("call_request")
        def on_call_req(data):
            self.sio.emit("incoming_call", {
                "sender": request.sid,
                "sender_name": data.get("sender_name"),
                "call_type": data.get("call_type", "video"),
            }, room=data["target"])

        @self.sio.on("call_accept")
        def on_call_accept(data):
            self.sio.emit("call_accepted", {"sender": request.sid}, room=data["target"])

        @self.sio.on("call_reject")
        def on_call_reject(data):
            self.sio.emit("call_rejected", {"sender": request.sid}, room=data["target"])

        @self.sio.on("call_end")
        def on_call_end(data):
            target = data.get("target")
            if target:
                self.sio.emit("call_ended", {"sender": request.sid}, room=target)

        @self.sio.on("webrtc_offer")
        def on_offer(data):
            self.sio.emit("webrtc_offer", {
                "sdp": data["sdp"], "type": data["type"], "sender": request.sid,
            }, room=data["target"])

        @self.sio.on("webrtc_answer")
        def on_answer(data):
            self.sio.emit("webrtc_answer", {
                "sdp": data["sdp"], "type": data["type"], "sender": request.sid,
            }, room=data["target"])

        @self.sio.on("webrtc_ice")
        def on_ice(data):
            self.sio.emit("webrtc_ice", {
                "candidate": data.get("candidate"), "sender": request.sid,
            }, room=data["target"])

    def _broadcast_users(self):
        users = [{"sid": c["sid"], "username": c["username"]}
                 for c in self.clients.values() if c["username"]]
        self.sio.emit("users_online", {"users": users})

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
  Client    : http://{self.host_ip}:{port}/client
  Admin     : http://{self.host_ip}:{port}/admin
""")

        if getattr(sys, 'frozen', False):
            threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}/client")).start()

        self.sio.run(self.app, host=host, port=port, debug=False, log_output=not silent)


def create_app():
    return BROServer()
