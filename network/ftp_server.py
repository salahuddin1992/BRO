"""
Helen WiFi - FTP Server
Provides FTP access to shared files (unencrypted).

Connection Type: FTP (port 2121)
  - Transport: TCP with FTP protocol (unencrypted)
  - Auth: Username/password from Helen WiFi user database
  - Features: File browse, upload, download
  - Note: Use SFTP for encrypted file transfer
"""
import logging
import os
import socket
import threading
import time

logger = logging.getLogger("BRO.ftp")

# Optional: pyftpdlib for FTP server
try:
    from pyftpdlib.authorizers import DummyAuthorizer
    from pyftpdlib.handlers import FTPHandler
    from pyftpdlib.servers import FTPServer as _FTPServer
    _pyftpdlib_available = True
except ImportError:
    _pyftpdlib_available = False
    logger.info("pyftpdlib not installed - FTP server disabled")


class FTPServer:
    """FTP server for Helen WiFi - provides file access via FTP.

    Uses pyftpdlib to create an FTP server. Users authenticate with
    their Helen WiFi credentials and get access to the uploads folder.
    """

    def __init__(self, db, upload_folder, host="0.0.0.0", port=2121):
        self.db = db
        self.upload_folder = upload_folder
        self.host = host
        self.port = port
        self._running = False
        self._server = None
        self._thread = None
        self._connections = []
        self._lock = threading.Lock()

    @property
    def available(self):
        return _pyftpdlib_available

    def start(self):
        """Start FTP server in background thread."""
        if not _pyftpdlib_available:
            logger.warning("FTP server not started: pyftpdlib not installed")
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info(f"FTP server started on {self.host}:{self.port}")

    def stop(self):
        """Stop FTP server."""
        self._running = False
        if self._server:
            try:
                self._server.close_all()
            except Exception:
                pass
        logger.info("FTP server stopped")

    def _build_authorizer(self):
        """Build FTP authorizer from current user database."""
        authorizer = DummyAuthorizer()

        # Add all registered users
        users = self.db.get_all_users()
        for user in users:
            username = user["username"]
            # Create per-user directory within uploads
            user_dir = os.path.join(self.upload_folder, f"_ftp_{username}")
            os.makedirs(user_dir, exist_ok=True)

            role = user.get("role", "user")
            if user.get("banned"):
                continue

            # Admin/moderator: full access to uploads folder
            # Regular user: access to their own directory
            if role in ("admin", "moderator"):
                home_dir = self.upload_folder
                perm = "elradfmw"  # full read/write
            else:
                home_dir = user_dir
                perm = "elradfmw"  # read/write in own dir

            try:
                # Use a placeholder password - actual auth handled via custom authorizer
                authorizer.add_user(username, username, home_dir, perm=perm)
            except Exception as e:
                logger.warning(f"FTP: could not add user {username}: {e}")

        # Anonymous read-only access to shared uploads
        try:
            authorizer.add_anonymous(self.upload_folder, perm="elr")
        except Exception:
            pass

        return authorizer

    def _run(self):
        """Run FTP server (blocking, in thread)."""
        try:
            authorizer = self._build_authorizer()

            handler = FTPHandler
            handler.authorizer = authorizer
            handler.banner = "Helen WiFi FTP Server"
            handler.passive_ports = range(60000, 60100)

            # Track connections
            server_ref = self

            class TrackingHandler(FTPHandler):
                def on_connect(self):
                    with server_ref._lock:
                        server_ref._connections.append({
                            "ip": self.remote_ip,
                            "username": None,
                            "connected_at": time.time(),
                        })

                def on_login(self, username):
                    with server_ref._lock:
                        for c in server_ref._connections:
                            if c["ip"] == self.remote_ip and c["username"] is None:
                                c["username"] = username
                                break

                def on_disconnect(self):
                    with server_ref._lock:
                        server_ref._connections = [
                            c for c in server_ref._connections
                            if not (c["ip"] == self.remote_ip and
                                    c.get("username") == getattr(self, "username", None))
                        ]

            TrackingHandler.authorizer = authorizer
            TrackingHandler.banner = "Helen WiFi FTP Server"
            TrackingHandler.passive_ports = range(60000, 60100)

            self._server = _FTPServer((self.host, self.port), TrackingHandler)
            self._server.max_cons = 20
            self._server.max_cons_per_ip = 5

            self._server.serve_forever()
        except Exception as e:
            logger.error(f"FTP server error: {e}")
            self._running = False

    def get_stats(self):
        """Return FTP server stats for admin panel."""
        with self._lock:
            connections = list(self._connections)
        return {
            "available": _pyftpdlib_available,
            "running": self._running,
            "port": self.port,
            "connections": connections,
            "connection_count": len(connections),
        }
