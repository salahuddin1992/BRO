"""
Helen WiFi - SSH Server
Provides SSH access for remote terminal and command execution.

Connection Type: SSH (port 2222)
  - Transport: TCP with SSH protocol (encrypted)
  - Auth: Username/password from Helen WiFi user database
  - Features: Remote terminal, command execution
"""
import logging
import os
import socket
import threading

logger = logging.getLogger("BRO.ssh")

# Optional: paramiko for SSH server
try:
    import paramiko
    _paramiko_available = True
except ImportError:
    _paramiko_available = False
    logger.info("paramiko not installed - SSH server disabled")


class _SSHServerInterface(paramiko.ServerInterface if _paramiko_available else object):
    """SSH authentication handler using Helen WiFi user database."""

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
            logger.info(f"SSH auth success: {username}")
            return paramiko.AUTH_SUCCESSFUL
        logger.warning(f"SSH auth failed: {username}")
        return paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):
        return "password"

    def check_channel_shell_request(self, channel):
        return True

    def check_channel_pty_request(self, channel, term, width, height,
                                  pixelwidth, pixelheight, modes):
        return True


class SSHServer:
    """SSH server for Helen WiFi - provides remote terminal access.

    Uses paramiko to create an SSH server that authenticates against
    the Helen WiFi user database. Only admin/moderator users can access.
    """

    def __init__(self, db, host="0.0.0.0", port=2222, host_key_file=None):
        self.db = db
        self.host = host
        self.port = port
        self._running = False
        self._server_socket = None
        self._connections = []  # active SSH connections
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
            logger.info("SSH host key loaded from file")
            return
        # Generate new RSA key
        self._host_key = paramiko.RSAKey.generate(2048)
        if self._host_key_file:
            try:
                self._host_key.write_private_key_file(self._host_key_file)
                os.chmod(self._host_key_file, 0o600)
                logger.info(f"SSH host key saved to {self._host_key_file}")
            except OSError as e:
                logger.warning(f"Could not save SSH host key: {e}")

    def start(self):
        """Start SSH server in background thread."""
        if not _paramiko_available:
            logger.warning("SSH server not started: paramiko not installed")
            return
        self._ensure_host_key()
        self._running = True
        threading.Thread(target=self._listen, daemon=True).start()
        logger.info(f"SSH server started on {self.host}:{self.port}")

    def stop(self):
        """Stop SSH server and close all connections."""
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
        logger.info("SSH server stopped")

    def _listen(self):
        """Accept incoming SSH connections."""
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.settimeout(2)
        try:
            self._server_socket.bind((self.host, self.port))
            self._server_socket.listen(5)
        except OSError as e:
            logger.error(f"SSH server bind failed: {e}")
            return

        while self._running:
            try:
                client_sock, addr = self._server_socket.accept()
                logger.info(f"SSH connection from {addr[0]}:{addr[1]}")
                threading.Thread(
                    target=self._handle_client,
                    args=(client_sock, addr),
                    daemon=True
                ).start()
            except socket.timeout:
                continue
            except OSError:
                if self._running:
                    logger.error("SSH accept error")
                break

    def _handle_client(self, client_sock, addr):
        """Handle a single SSH client connection."""
        transport = None
        try:
            transport = paramiko.Transport(client_sock)
            transport.add_server_key(self._host_key)

            server_iface = _SSHServerInterface(self.db)
            transport.start_server(server=server_iface)

            # Wait for auth (timeout 30s)
            channel = transport.accept(30)
            if channel is None:
                logger.warning(f"SSH: no channel from {addr[0]}")
                return

            username = server_iface.username or "unknown"

            # Check role - only admin/moderator allowed
            user_info = self.db.get_user(username)
            if not user_info or user_info.get("role", "user") == "user":
                channel.send("Access denied: admin or moderator role required.\r\n".encode())
                channel.close()
                return

            conn_info = {
                "transport": transport,
                "channel": channel,
                "username": username,
                "ip": addr[0],
            }
            with self._lock:
                self._connections.append(conn_info)

            # Simple command shell
            channel.send(f"\r\nHelen WiFi SSH - Welcome {username}\r\n".encode())
            channel.send(b"Type 'help' for available commands, 'exit' to disconnect.\r\n\r\n")
            channel.send(b"helen> ")

            buf = b""
            while self._running and transport.is_active():
                try:
                    data = channel.recv(1024)
                    if not data:
                        break
                    buf += data
                    while b"\r" in buf or b"\n" in buf:
                        line, _, buf = buf.partition(b"\r" if b"\r" in buf else b"\n")
                        buf = buf.lstrip(b"\n")
                        cmd = line.decode("utf-8", errors="replace").strip()
                        if cmd:
                            response = self._execute_command(cmd, username)
                            channel.send(response.encode("utf-8"))
                        channel.send(b"helen> ")
                except socket.timeout:
                    continue
                except Exception:
                    break
        except Exception as e:
            logger.error(f"SSH session error from {addr[0]}: {e}")
        finally:
            if transport:
                transport.close()
            with self._lock:
                self._connections = [c for c in self._connections
                                     if c.get("transport") is not transport]

    def _execute_command(self, cmd, username):
        """Execute a Helen WiFi management command."""
        parts = cmd.split()
        if not parts:
            return "\r\n"
        command = parts[0].lower()

        if command == "help":
            return (
                "\r\nAvailable commands:\r\n"
                "  help          - Show this help\r\n"
                "  status        - Server status\r\n"
                "  users         - List online users\r\n"
                "  rooms         - List chat rooms\r\n"
                "  stats         - Show statistics\r\n"
                "  kick <user>   - Kick a user\r\n"
                "  ban <user>    - Ban a user\r\n"
                "  unban <user>  - Unban a user\r\n"
                "  exit          - Disconnect\r\n"
            )
        elif command == "status":
            user_count = self.db.count_users()
            msg_count = self.db.count_messages()
            file_count = self.db.count_files()
            return (
                f"\r\nServer Status:\r\n"
                f"  Users: {user_count}\r\n"
                f"  Messages: {msg_count}\r\n"
                f"  Files: {file_count}\r\n"
            )
        elif command == "users":
            users = self.db.get_all_users()
            if not users:
                return "\r\nNo users registered.\r\n"
            lines = "\r\nRegistered Users:\r\n"
            for u in users[:20]:
                role = u.get("role", "user")
                status = u.get("status", "offline")
                lines += f"  {u['username']:20s} role={role:10s} status={status}\r\n"
            return lines
        elif command == "rooms":
            rooms = self.db.get_rooms()
            if not rooms:
                return "\r\nNo rooms.\r\n"
            lines = "\r\nRooms:\r\n"
            for r in rooms:
                lines += f"  {r['name']:20s} members={r.get('member_count', 0)}\r\n"
            return lines
        elif command == "stats":
            return (
                f"\r\nStatistics:\r\n"
                f"  Users: {self.db.count_users()}\r\n"
                f"  Messages: {self.db.count_messages()}\r\n"
                f"  Files: {self.db.count_files()}\r\n"
                f"  Rooms: {len(self.db.get_rooms())}\r\n"
                f"  Banned: {self.db.count_banned()}\r\n"
            )
        elif command == "kick" and len(parts) > 1:
            target = parts[1]
            return f"\r\nKick request sent for: {target}\r\n"
        elif command == "ban" and len(parts) > 1:
            target = parts[1]
            self.db.ban_user(target)
            return f"\r\nUser banned: {target}\r\n"
        elif command == "unban" and len(parts) > 1:
            target = parts[1]
            self.db.unban_user(target)
            return f"\r\nUser unbanned: {target}\r\n"
        elif command == "exit":
            return "\r\nBye!\r\n"
        else:
            return f"\r\nUnknown command: {command}. Type 'help' for help.\r\n"

    def get_stats(self):
        """Return SSH server stats for admin panel."""
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
