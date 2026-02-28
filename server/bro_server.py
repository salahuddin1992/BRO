"""
Helen WiFi Server - Main Server Module
========================================
WiFi/Network Communication Server with WebRTC, Mesh Networking,
Full Control Panel, and Universal Router Support.

Features:
  - Real-time chat with typing indicators, read receipts, offline queue
  - Voice/Video calls via WebRTC with TURN fallback
  - File upload with progress bar, drag-drop, chunked/resumable
  - Mesh networking with TCP fallback
  - Screen sharing
  - Works on ALL routers including Fiber Optic (GPON/EPON/XG-PON/SFP/ONT/ONU)
"""
import os
import sys
import uuid
import json
import logging
import time
import hashlib
import threading
import webbrowser
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, request, jsonify, send_from_directory,
    session, redirect, url_for
)
from flask_socketio import SocketIO, emit
from flask_cors import CORS

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from network.detector import NetworkDetector
from mesh.mesh_node import MeshNode
from server.signaling import SignalingServer

logger = logging.getLogger("HelenWiFi")


class BROServer:
    """
    Main BRO Communication Server.
    Provides: WebRTC signaling, mesh networking, file transfer,
    messaging, admin control panel - works on ALL network types.
    """

    def __init__(self):
        self.server_id = str(uuid.uuid4())[:12]
        self.start_time = datetime.utcnow()

        # Flask app
        template_dir = os.path.join(config.BASE_PATH, "templates")
        static_dir = os.path.join(config.BASE_PATH, "static")
        self.app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
        self.app.secret_key = config.SECRET_KEY
        self.app.config["MAX_CONTENT_LENGTH"] = None  # unlimited
        CORS(self.app)

        # Network detection (includes fiber optic)
        self.net_detector = NetworkDetector()
        self.net_detector.detect_all()
        best = self.net_detector.get_best_interface()
        self.host_ip = best.ip if best else "0.0.0.0"
        self.is_fiber = self.net_detector.fiber_detected

        # Optimize socket settings for fiber
        buffer_size = self.net_detector.get_optimal_buffer_size()

        # SocketIO with optimized settings
        self.socketio = SocketIO(
            self.app,
            cors_allowed_origins="*",
            async_mode="eventlet",
            max_http_buffer_size=1e300,
            ping_timeout=120,  # Longer timeout for stability
            ping_interval=25,
            logger=False,
            engineio_logger=False,
        )

        # Mesh networking
        self.mesh = MeshNode(
            self.server_id, self.host_ip,
            config.SERVER_PORT, config.MESH_DISCOVERY_PORT
        )

        # Signaling
        self.signaling = SignalingServer(self.socketio)

        # State
        self.connected_clients = {}
        self.messages = []
        self.file_transfers = []
        self.server_logs = []
        self.typing_users = {}  # {sid: {username, target, timestamp}}
        self.offline_messages = {}  # {username: [messages]}
        self.message_acks = {}  # {msg_id: {delivered: bool, read: bool}}
        self.upload_chunks = {}  # {upload_id: {chunks, total, filename}}

        self._setup_routes()
        self._setup_socket_events()

    def _log(self, msg, level="info"):
        """Log and store for dashboard."""
        entry = {
            "time": datetime.utcnow().isoformat(),
            "level": level,
            "message": msg,
        }
        self.server_logs.append(entry)
        if len(self.server_logs) > 500:
            self.server_logs = self.server_logs[-500:]
        getattr(logger, level, logger.info)(msg)

    def _login_required(self, f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not session.get("admin_logged_in"):
                return redirect(url_for("login"))
            return f(*args, **kwargs)
        return wrapper

    def _get_sid_by_username(self, username):
        """Find SID by username."""
        for sid, client in self.connected_clients.items():
            if client.get("username") == username:
                return sid
        return None

    def _setup_routes(self):
        """Register all HTTP routes."""

        @self.app.route("/")
        def index():
            return redirect(url_for("client_page"))

        # ---- Auth ----
        @self.app.route("/login", methods=["GET", "POST"])
        def login():
            if request.method == "POST":
                username = request.form.get("username", "")
                password = request.form.get("password", "")
                if username == config.ADMIN_USERNAME and password == config.ADMIN_PASSWORD:
                    session["admin_logged_in"] = True
                    return redirect(url_for("admin_dashboard"))
                return render_template("login.html", error="Invalid credentials")
            return render_template("login.html", error=None)

        @self.app.route("/logout")
        def logout():
            session.pop("admin_logged_in", None)
            return redirect(url_for("login"))

        # ---- Admin ----
        @self.app.route("/admin")
        @self._login_required
        def admin_dashboard():
            return render_template("admin.html")

        @self.app.route("/api/admin/stats")
        @self._login_required
        def api_stats():
            uptime = (datetime.utcnow() - self.start_time).total_seconds()
            return jsonify({
                "server_id": self.server_id,
                "uptime": int(uptime),
                "host_ip": self.host_ip,
                "port": config.SERVER_PORT,
                "is_fiber": self.is_fiber,
                "connected_clients": len(self.connected_clients),
                "clients": list(self.connected_clients.values()),
                "total_messages": len(self.messages),
                "total_files": len(self.file_transfers),
                "network": self.net_detector.to_dict_list(),
                "mesh": self.mesh.get_stats(),
                "signaling": self.signaling.get_stats(),
                "fiber_routers": config.FIBER_ROUTER_TYPES,
                "logs": self.server_logs[-50:],
            })

        @self.app.route("/api/admin/network")
        @self._login_required
        def api_network():
            self.net_detector.detect_all()
            return jsonify({
                "interfaces": self.net_detector.to_dict_list(),
                "is_fiber": self.net_detector.fiber_detected,
                "optimal_mtu": self.net_detector.get_optimal_mtu(),
                "fiber_interfaces": [i.to_dict() for i in self.net_detector.get_fiber_interfaces()],
            })

        @self.app.route("/api/admin/mesh")
        @self._login_required
        def api_mesh():
            return jsonify(self.mesh.get_stats())

        @self.app.route("/api/admin/mesh/connect", methods=["POST"])
        @self._login_required
        def api_mesh_connect():
            data = request.get_json()
            host = data.get("host")
            port = int(data.get("port", config.MESH_DISCOVERY_PORT))
            if self.mesh.connect_to_server(host, port):
                return jsonify({"status": "ok", "message": f"Connecting to {host}:{port}"})
            return jsonify({"status": "error", "message": "Connection failed"}), 500

        @self.app.route("/api/admin/mesh/peers")
        @self._login_required
        def api_mesh_peers():
            return jsonify({"peers": self.mesh.get_peer_list()})

        @self.app.route("/api/admin/clients")
        @self._login_required
        def api_clients():
            return jsonify({"clients": list(self.connected_clients.values())})

        @self.app.route("/api/admin/logs")
        @self._login_required
        def api_logs():
            return jsonify({"logs": self.server_logs[-100:]})

        @self.app.route("/api/admin/messages")
        @self._login_required
        def api_messages():
            return jsonify({"messages": self.messages[-200:]})

        # ---- Client ----
        @self.app.route("/client")
        def client_page():
            return render_template("client.html")

        # ---- File Upload (standard) ----
        @self.app.route("/api/upload", methods=["POST"])
        def upload_file():
            if "file" not in request.files:
                return jsonify({"error": "No file"}), 400
            f = request.files["file"]
            if not f.filename:
                return jsonify({"error": "No filename"}), 400
            safe_name = f"{int(time.time())}_{f.filename}"
            path = os.path.join(config.UPLOAD_FOLDER, safe_name)
            f.save(path)
            file_info = {
                "name": f.filename,
                "saved_as": safe_name,
                "size": os.path.getsize(path),
                "uploaded_by": request.form.get("username", "Unknown"),
                "uploaded_at": datetime.utcnow().isoformat(),
            }
            self.file_transfers.append(file_info)
            self._log(f"File uploaded: {f.filename}")
            self.socketio.emit("file_shared", file_info)
            return jsonify({"status": "ok", "file": file_info})

        # ---- Chunked/Resumable Upload ----
        @self.app.route("/api/upload/init", methods=["POST"])
        def init_chunked_upload():
            """Initialize a chunked upload session."""
            data = request.get_json()
            filename = data.get("filename", "unknown")
            total_size = data.get("total_size", 0)
            total_chunks = data.get("total_chunks", 1)
            upload_id = str(uuid.uuid4())[:12]
            self.upload_chunks[upload_id] = {
                "filename": filename,
                "total_size": total_size,
                "total_chunks": total_chunks,
                "received_chunks": set(),
                "username": data.get("username", "Unknown"),
                "started_at": datetime.utcnow().isoformat(),
            }
            return jsonify({"upload_id": upload_id, "status": "ready"})

        @self.app.route("/api/upload/chunk", methods=["POST"])
        def upload_chunk():
            """Upload a single chunk."""
            upload_id = request.form.get("upload_id")
            chunk_index = int(request.form.get("chunk_index", 0))
            if upload_id not in self.upload_chunks:
                return jsonify({"error": "Invalid upload_id"}), 400
            if "chunk" not in request.files:
                return jsonify({"error": "No chunk data"}), 400

            info = self.upload_chunks[upload_id]
            chunk_dir = os.path.join(config.UPLOAD_FOLDER, f"_chunks_{upload_id}")
            os.makedirs(chunk_dir, exist_ok=True)
            chunk_path = os.path.join(chunk_dir, f"chunk_{chunk_index:06d}")
            request.files["chunk"].save(chunk_path)
            info["received_chunks"].add(chunk_index)

            if len(info["received_chunks"]) >= info["total_chunks"]:
                # All chunks received - assemble
                safe_name = f"{int(time.time())}_{info['filename']}"
                final_path = os.path.join(config.UPLOAD_FOLDER, safe_name)
                with open(final_path, "wb") as out:
                    for i in range(info["total_chunks"]):
                        cp = os.path.join(chunk_dir, f"chunk_{i:06d}")
                        with open(cp, "rb") as cf:
                            out.write(cf.read())
                # Cleanup chunks
                import shutil
                shutil.rmtree(chunk_dir, ignore_errors=True)
                del self.upload_chunks[upload_id]

                file_info = {
                    "name": info["filename"],
                    "saved_as": safe_name,
                    "size": os.path.getsize(final_path),
                    "uploaded_by": info["username"],
                    "uploaded_at": datetime.utcnow().isoformat(),
                }
                self.file_transfers.append(file_info)
                self._log(f"Chunked upload complete: {info['filename']}")
                self.socketio.emit("file_shared", file_info)
                return jsonify({"status": "complete", "file": file_info})

            return jsonify({
                "status": "ok",
                "received": len(info["received_chunks"]),
                "total": info["total_chunks"],
            })

        @self.app.route("/api/upload/status/<upload_id>")
        def upload_status(upload_id):
            """Check chunked upload status for resume."""
            if upload_id not in self.upload_chunks:
                return jsonify({"error": "Not found"}), 404
            info = self.upload_chunks[upload_id]
            return jsonify({
                "upload_id": upload_id,
                "filename": info["filename"],
                "received_chunks": sorted(info["received_chunks"]),
                "total_chunks": info["total_chunks"],
            })

        @self.app.route("/api/download/<filename>")
        def download_file(filename):
            return send_from_directory(config.UPLOAD_FOLDER, filename)

        @self.app.route("/api/files")
        def list_files():
            return jsonify({"files": self.file_transfers})

        # ---- ICE Config ----
        @self.app.route("/api/ice-config")
        def ice_config():
            return jsonify({"iceServers": config.ICE_SERVERS})

    def _setup_socket_events(self):
        """Register WebSocket events for real-time communication."""

        @self.socketio.on("connect")
        def on_connect():
            sid = request.sid
            self.connected_clients[sid] = {
                "sid": sid,
                "username": None,
                "connected_at": datetime.utcnow().isoformat(),
                "ip": request.remote_addr,
            }
            self._log(f"Client connected: {sid} from {request.remote_addr}")
            emit("server_info", {
                "server_id": self.server_id,
                "ice_servers": config.ICE_SERVERS,
                "is_fiber": self.is_fiber,
                "max_file_size": config.MAX_FILE_SIZE,
            })

        @self.socketio.on("disconnect")
        def on_disconnect():
            sid = request.sid
            client = self.connected_clients.pop(sid, None)
            self.typing_users.pop(sid, None)
            name = client.get("username", sid) if client else sid
            self._log(f"Client disconnected: {name}")
            self.signaling.handle_disconnect(sid)
            self.socketio.emit("user_offline", {"sid": sid, "username": name})
            # Broadcast updated user list
            users = [
                {"sid": c["sid"], "username": c["username"]}
                for c in self.connected_clients.values()
                if c["username"]
            ]
            self.socketio.emit("users_online", {"users": users})

        @self.socketio.on("register")
        def on_register(data):
            sid = request.sid
            username = data.get("username", f"User-{sid[:6]}")
            if sid in self.connected_clients:
                self.connected_clients[sid]["username"] = username
            self._log(f"User registered: {username}")
            # Broadcast online users
            users = [
                {"sid": c["sid"], "username": c["username"]}
                for c in self.connected_clients.values()
                if c["username"]
            ]
            self.socketio.emit("users_online", {"users": users})
            # Deliver offline messages
            if username in self.offline_messages:
                for msg in self.offline_messages.pop(username):
                    emit("chat_message", msg)

        @self.socketio.on("chat_message")
        def on_chat_message(data):
            msg_id = str(uuid.uuid4())[:10]
            msg = {
                "id": msg_id,
                "sender": data.get("sender", "Unknown"),
                "sender_sid": request.sid,
                "text": data.get("text", ""),
                "target": data.get("target"),
                "timestamp": datetime.utcnow().isoformat(),
            }
            self.messages.append(msg)
            target = data.get("target")
            if target:
                # Check if target is online
                if target in self.connected_clients:
                    emit("chat_message", msg, room=target)
                    emit("chat_message", msg)  # echo back
                else:
                    # Store for offline delivery by username
                    target_client = self.connected_clients.get(target, {})
                    target_name = target_client.get("username")
                    if target_name:
                        self.offline_messages.setdefault(target_name, []).append(msg)
                    emit("chat_message", msg)  # echo back
            else:
                self.socketio.emit("chat_message", msg)
            # Send delivery ack
            emit("message_ack", {"id": msg_id, "status": "delivered"})

        @self.socketio.on("message_read")
        def on_message_read(data):
            """Mark message as read."""
            msg_id = data.get("id")
            sender_sid = data.get("sender_sid")
            if sender_sid:
                self.socketio.emit("message_read_receipt", {
                    "id": msg_id,
                    "reader": request.sid,
                }, room=sender_sid)

        @self.socketio.on("typing")
        def on_typing(data):
            """Handle typing indicator."""
            sid = request.sid
            target = data.get("target")
            client = self.connected_clients.get(sid, {})
            username = client.get("username", "")
            typing_data = {
                "sid": sid,
                "username": username,
                "is_typing": data.get("is_typing", True),
            }
            if target:
                emit("user_typing", typing_data, room=target)
            else:
                emit("user_typing", typing_data, broadcast=True, include_self=False)

        @self.socketio.on("file_chunk")
        def on_file_chunk(data):
            target = data.get("target")
            if target:
                emit("file_chunk", data, room=target)
            else:
                emit("file_chunk", data, broadcast=True, include_self=False)

        @self.socketio.on("ping_check")
        def on_ping_check(data):
            """Client-server latency check."""
            emit("pong_check", {
                "client_time": data.get("time"),
                "server_time": datetime.utcnow().isoformat(),
            })

    def run(self, host=None, port=None, silent=True):
        """Start the BRO server."""
        host = host or config.SERVER_HOST
        port = port or config.SERVER_PORT

        # Setup logging
        if silent:
            log_handler = logging.FileHandler(config.LOG_FILE)
        else:
            log_handler = logging.StreamHandler()
        log_handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        ))
        logging.root.addHandler(log_handler)
        logging.root.setLevel(getattr(logging, config.LOG_LEVEL))

        # Start mesh
        self.mesh.start()
        self._log(f"Helen WiFi Server starting: {self.server_id}")
        self._log(f"Host IP: {self.host_ip}")
        self._log(f"Fiber Optic: {'YES' if self.is_fiber else 'No'}")
        self._log(f"Interfaces: {len(self.net_detector.interfaces)}")
        for iface in self.net_detector.interfaces:
            fiber_info = f" [FIBER: {iface.fiber_type}]" if iface.fiber_type else ""
            speed_info = f" {iface.speed}Mbps" if iface.speed else ""
            self._log(f"  {iface.name}: {iface.ip} ({iface.interface_type}){speed_info}{fiber_info}")

        if not silent:
            fiber_status = " [FIBER OPTIC]" if self.is_fiber else ""
            print(f"""
+----------------------------------------------+
|            Helen WiFi Server                 |
|              هيلين WiFi                      |
+----------------------------------------------+
|  Server ID  : {self.server_id:<30}|
|  Host       : {host}:{port:<27}|
|  Local IP   : {self.host_ip:<30}|
|  Connection : {'Fiber Optic' if self.is_fiber else 'Standard':<30}|
|  Admin Panel: http://{self.host_ip}:{port}/admin{' ' * (17 - len(str(port)))}|
|  Client     : http://{self.host_ip}:{port}/client{' ' * (16 - len(str(port)))}|
+----------------------------------------------+
|  Supported Routers: ALL (WiFi/Ethernet/DSL/  |
|  Fiber/GPON/EPON/XG-PON/XGS-PON/SFP/ONT/ONU)|
+----------------------------------------------+
""")

        # Auto-open browser when running as EXE
        if getattr(sys, 'frozen', False):
            url = f"http://127.0.0.1:{port}/client"
            threading.Timer(1.5, lambda: webbrowser.open(url)).start()

        self.socketio.run(self.app, host=host, port=port, debug=False, log_output=not silent)


def create_app():
    """Factory for creating the BRO server instance."""
    server = BROServer()
    return server
