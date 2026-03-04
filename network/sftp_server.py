"""
Helen WiFi - SFTP Server
Provides SFTP (SSH File Transfer Protocol) access to shared files.

Connection Type: SFTP (port 2223)
  - Transport: TCP with SSH protocol (encrypted)
  - Auth: Username/password from Helen WiFi user database
  - Features: Secure file browse, upload, download via SSH subsystem
"""
import logging
import os
import socket
import stat
import threading
import time

logger = logging.getLogger("BRO.sftp")

# Optional: paramiko for SFTP server
try:
    import paramiko
    _paramiko_available = True
except ImportError:
    _paramiko_available = False
    logger.info("paramiko not installed - SFTP server disabled")


class _SFTPServerInterface(paramiko.ServerInterface if _paramiko_available else object):
    """SFTP SSH authentication handler."""

    def __init__(self, db):
        self._db = db
        self.username = None
        if _paramiko_available:
            super().__init__()

    def check_channel_request(self, kind, chanid):
        if kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_auth_password(self, username, password):
        user = self._db.authenticate(username, password)
        if user:
            self.username = username
            logger.info(f"SFTP auth success: {username}")
            return paramiko.AUTH_SUCCESSFUL
        logger.warning(f"SFTP auth failed: {username}")
        return paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):
        return "password"


class _SFTPHandle(paramiko.SFTPHandle if _paramiko_available else object):
    """Handle for an open SFTP file."""

    def __init__(self, flags=0):
        if _paramiko_available:
            super().__init__(flags)
        self._fobj = None
        self._path = None

    def close(self):
        if self._fobj:
            self._fobj.close()
        if _paramiko_available:
            super().close()

    def read(self, offset, length):
        try:
            self._fobj.seek(offset)
            data = self._fobj.read(length)
            if not data:
                return paramiko.SFTP_EOF
            return data
        except Exception:
            return paramiko.SFTPServer.convert_errno(os.errno.EIO)

    def write(self, offset, data):
        try:
            self._fobj.seek(offset)
            self._fobj.write(data)
            self._fobj.flush()
            return paramiko.SFTP_OK
        except Exception:
            return paramiko.SFTPServer.convert_errno(os.errno.EIO)

    def stat(self):
        try:
            st = os.fstat(self._fobj.fileno())
            return paramiko.SFTPAttributes.from_stat(st)
        except Exception:
            return paramiko.SFTP_NO_SUCH_FILE


class _SFTPRequestHandler(paramiko.SFTPServerInterface if _paramiko_available else object):
    """SFTP file system handler - maps to Helen WiFi upload folder."""

    def __init__(self, server, *args, **kwargs):
        self._root = getattr(server, "_root_path", "/tmp")
        if _paramiko_available:
            super().__init__(server, *args, **kwargs)

    def _resolve(self, path):
        """Resolve SFTP path to real filesystem path (with traversal protection)."""
        # Normalize and join with root
        path = path.replace("\\", "/").lstrip("/")
        real = os.path.realpath(os.path.join(self._root, path))
        # Prevent directory traversal
        if not real.startswith(os.path.realpath(self._root)):
            return None
        return real

    def list_folder(self, path):
        real = self._resolve(path)
        if not real or not os.path.isdir(real):
            return paramiko.SFTP_NO_SUCH_FILE
        result = []
        try:
            for name in os.listdir(real):
                # Skip internal directories
                if name.startswith("_"):
                    continue
                full = os.path.join(real, name)
                try:
                    st = os.stat(full)
                    attr = paramiko.SFTPAttributes.from_stat(st)
                    attr.filename = name
                    result.append(attr)
                except OSError:
                    continue
        except OSError:
            return paramiko.SFTP_PERMISSION_DENIED
        return result

    def stat(self, path):
        real = self._resolve(path)
        if not real:
            return paramiko.SFTP_NO_SUCH_FILE
        try:
            st = os.stat(real)
            return paramiko.SFTPAttributes.from_stat(st)
        except OSError:
            return paramiko.SFTP_NO_SUCH_FILE

    def lstat(self, path):
        return self.stat(path)

    def open(self, path, flags, attr):
        real = self._resolve(path)
        if not real:
            return paramiko.SFTP_NO_SUCH_FILE

        # Determine file mode from flags
        if flags & os.O_WRONLY:
            mode = "wb"
        elif flags & os.O_RDWR:
            mode = "r+b"
        else:
            mode = "rb"

        # Create file if needed
        if flags & os.O_CREAT:
            mode = "wb" if flags & os.O_TRUNC else "ab"
            parent = os.path.dirname(real)
            if not os.path.isdir(parent):
                os.makedirs(parent, exist_ok=True)

        try:
            fobj = open(real, mode)
        except OSError:
            return paramiko.SFTP_PERMISSION_DENIED

        handle = _SFTPHandle(flags)
        handle._fobj = fobj
        handle._path = real
        return handle

    def remove(self, path):
        real = self._resolve(path)
        if not real:
            return paramiko.SFTP_NO_SUCH_FILE
        try:
            os.remove(real)
            return paramiko.SFTP_OK
        except OSError:
            return paramiko.SFTP_PERMISSION_DENIED

    def mkdir(self, path, attr):
        real = self._resolve(path)
        if not real:
            return paramiko.SFTP_NO_SUCH_FILE
        try:
            os.makedirs(real, exist_ok=True)
            return paramiko.SFTP_OK
        except OSError:
            return paramiko.SFTP_PERMISSION_DENIED

    def rmdir(self, path):
        real = self._resolve(path)
        if not real:
            return paramiko.SFTP_NO_SUCH_FILE
        try:
            os.rmdir(real)
            return paramiko.SFTP_OK
        except OSError:
            return paramiko.SFTP_PERMISSION_DENIED


class SFTPServer:
    """SFTP server for Helen WiFi - provides encrypted file transfer.

    Uses paramiko to create an SFTP server that authenticates against
    the Helen WiFi user database. All users can access shared files.
    """

    def __init__(self, db, upload_folder, host="0.0.0.0", port=2223,
                 host_key_file=None):
        self.db = db
        self.upload_folder = upload_folder
        self.host = host
        self.port = port
        self._running = False
        self._server_socket = None
        self._connections = []
        self._lock = threading.Lock()
        self._host_key_file = host_key_file
        self._host_key = None

    @property
    def available(self):
        return _paramiko_available

    def _ensure_host_key(self):
        """Load or generate SSH host key."""
        if self._host_key:
            return
        if self._host_key_file and os.path.isfile(self._host_key_file):
            self._host_key = paramiko.RSAKey.from_private_key_file(self._host_key_file)
            return
        self._host_key = paramiko.RSAKey.generate(2048)
        if self._host_key_file:
            try:
                self._host_key.write_private_key_file(self._host_key_file)
                os.chmod(self._host_key_file, 0o600)
            except OSError:
                pass

    def start(self):
        """Start SFTP server in background thread."""
        if not _paramiko_available:
            logger.warning("SFTP server not started: paramiko not installed")
            return
        self._ensure_host_key()
        self._running = True
        threading.Thread(target=self._listen, daemon=True).start()
        logger.info(f"SFTP server started on {self.host}:{self.port}")

    def stop(self):
        """Stop SFTP server and close all connections."""
        self._running = False
        with self._lock:
            for conn in self._connections:
                try:
                    conn["transport"].close()
                except Exception:
                    pass
            self._connections.clear()
        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception:
                pass
        logger.info("SFTP server stopped")

    def _listen(self):
        """Accept incoming SFTP connections."""
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.settimeout(2)
        try:
            self._server_socket.bind((self.host, self.port))
            self._server_socket.listen(5)
        except OSError as e:
            logger.error(f"SFTP server bind failed: {e}")
            return

        while self._running:
            try:
                client_sock, addr = self._server_socket.accept()
                logger.info(f"SFTP connection from {addr[0]}:{addr[1]}")
                threading.Thread(
                    target=self._handle_client,
                    args=(client_sock, addr),
                    daemon=True
                ).start()
            except socket.timeout:
                continue
            except OSError:
                if self._running:
                    logger.error("SFTP accept error")
                break

    def _handle_client(self, client_sock, addr):
        """Handle a single SFTP client connection."""
        transport = None
        try:
            transport = paramiko.Transport(client_sock)
            transport.add_server_key(self._host_key)

            server_iface = _SFTPServerInterface(self.db)
            transport.start_server(server=server_iface)

            # Wait for channel
            channel = transport.accept(30)
            if channel is None:
                return

            username = server_iface.username or "anonymous"

            conn_info = {
                "transport": transport,
                "username": username,
                "ip": addr[0],
                "connected_at": time.time(),
            }
            with self._lock:
                self._connections.append(conn_info)

            # Set root path on the transport for the SFTP handler
            transport._root_path = self.upload_folder

            # Start SFTP subsystem
            transport.set_subsystem_handler(
                "sftp",
                paramiko.SFTPServer,
                sftp_si=_SFTPRequestHandler,
            )

            # Keep connection alive until client disconnects
            while self._running and transport.is_active():
                try:
                    transport.join(timeout=5)
                    if not transport.is_active():
                        break
                except Exception:
                    break

        except Exception as e:
            logger.error(f"SFTP session error from {addr[0]}: {e}")
        finally:
            if transport:
                transport.close()
            with self._lock:
                self._connections = [c for c in self._connections
                                     if c.get("transport") is not transport]

    def get_stats(self):
        """Return SFTP server stats for admin panel."""
        with self._lock:
            connections = [
                {"username": c["username"], "ip": c["ip"]}
                for c in self._connections
            ]
        return {
            "available": _paramiko_available,
            "running": self._running,
            "port": self.port,
            "connections": connections,
            "connection_count": len(connections),
        }
