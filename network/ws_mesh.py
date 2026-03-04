"""
Helen WiFi - Eventlet-Compatible Mesh Communication
Persistent TCP connections between mesh nodes for real-time sync.
Uses eventlet green sockets (no asyncio conflict).
Length-prefixed JSON frames + optional zlib compression.
Smart reconnection with exponential backoff.
HMAC challenge-response authentication (secret never sent on wire).
"""
import hashlib
import hmac as hmac_mod
import json
import logging
import secrets as secrets_mod
import socket
import struct
import threading
import time
import zlib

import eventlet

logger = logging.getLogger("BRO.ws_mesh")

# Frame format: [1-byte flags][4-byte length][payload]
# Flags: 0x00 = plain, 0x01 = zlib compressed
HEADER_FORMAT = "!BI"  # 1-byte flag + 4-byte unsigned int
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
MAX_MESSAGE_SIZE = 10 * 1024 * 1024  # 10MB


class WebSocketMeshBridge:
    """Eventlet-compatible mesh communication using green TCP sockets.

    Replaces the previous asyncio+websockets implementation that conflicted
    with eventlet monkey-patching. Uses length-prefixed JSON over TCP
    for server-to-server communication (no browser involved).
    """

    def __init__(self, server_id, host, port, secret_key):
        self.server_id = server_id
        self.host = host
        self.port = port
        self.ws_port = port + 2  # Mesh port = server_port + 2 (e.g. 8402)
        self.secret_key = secret_key
        self._connections = {}  # {peer_id: socket}
        self._running = False
        self._on_message = None
        self._on_peer_connected = None
        self._on_peer_disconnected = None
        # Smart reconnection
        self._reconnect_peers = {}  # {(host, ws_port): {attempts, next_retry, peer_id}}
        self._max_reconnect_attempts = 10
        # Compression
        self._compress = True
        self._lock = threading.Lock()

    def start(self, on_message=None, on_peer_connected=None, on_peer_disconnected=None):
        """Start mesh bridge server using eventlet green threads."""
        self._on_message = on_message
        self._on_peer_connected = on_peer_connected
        self._on_peer_disconnected = on_peer_disconnected
        self._running = True
        eventlet.spawn(self._run_server)
        eventlet.spawn(self._reconnect_monitor)
        logger.info(f"Mesh bridge started on port {self.ws_port}")

    def stop(self):
        """Stop mesh bridge and close all connections."""
        self._running = False
        with self._lock:
            for peer_id, sock in list(self._connections.items()):
                try:
                    sock.close()
                except Exception:
                    pass
            self._connections.clear()

    # ═══════════════════════════════════════════════════════════════════════
    # Server (accept incoming peer connections)
    # ═══════════════════════════════════════════════════════════════════════

    def _run_server(self):
        """Listen for incoming mesh peer connections."""
        try:
            server = eventlet.listen(("0.0.0.0", self.ws_port))
            logger.info(f"Mesh bridge listening on :{self.ws_port}")
        except OSError as e:
            logger.warning(f"Mesh bridge bind failed on port {self.ws_port}: {e}")
            return

        while self._running:
            try:
                client_sock, addr = server.accept()
                eventlet.spawn(self._handle_incoming, client_sock, addr)
            except Exception:
                if not self._running:
                    break
                eventlet.sleep(0.1)
                continue

        try:
            server.close()
        except Exception:
            pass

    def _handle_incoming(self, sock, addr):
        """Handle an incoming connection from a peer server."""
        peer_id = None
        try:
            sock.settimeout(5.0)

            # Challenge-response auth: send challenge, expect HMAC response
            challenge = secrets_mod.token_hex(32)
            self._send_frame(sock, {"type": "challenge", "challenge": challenge})

            auth_data = self._recv_frame(sock)
            if not auth_data:
                sock.close()
                return

            # Verify HMAC response
            expected = hmac_mod.new(
                self.secret_key.encode(), challenge.encode(), hashlib.sha256
            ).hexdigest()
            if not hmac_mod.compare_digest(auth_data.get("response", ""), expected):
                logger.debug(f"Mesh auth failed from {addr}")
                sock.close()
                return

            peer_id = auth_data.get("server_id")
            if not peer_id or peer_id == self.server_id:
                sock.close()
                return

            # Store connection (replace old if exists)
            with self._lock:
                old = self._connections.get(peer_id)
                if old:
                    try:
                        old.close()
                    except Exception:
                        pass
                self._connections[peer_id] = sock

            logger.info(f"Mesh peer connected: {peer_id} from {addr[0]}")

            if self._on_peer_connected:
                self._on_peer_connected(peer_id)

            # Send welcome
            self._send_frame(sock, {
                "type": "welcome",
                "server_id": self.server_id,
            })

            # Main listen loop
            sock.settimeout(30.0)
            self._listen_loop(sock, peer_id)

        except Exception as e:
            logger.debug(f"Mesh incoming connection error: {e}")
        finally:
            self._cleanup_peer(peer_id, sock)

    # ═══════════════════════════════════════════════════════════════════════
    # Client (connect to peer servers)
    # ═══════════════════════════════════════════════════════════════════════

    def connect_to_peer(self, host, port):
        """Initiate a connection to a peer server."""
        ws_port = port + 2
        eventlet.spawn(self._connect_to, host, ws_port)

    def _connect_to(self, host, ws_port):
        """Establish outgoing connection to a peer."""
        peer_id = None
        sock = None
        try:
            sock = eventlet.connect((host, ws_port))
            sock.settimeout(5.0)

            # Challenge-response: receive challenge, send HMAC response
            challenge_msg = self._recv_frame(sock)
            if not challenge_msg or challenge_msg.get("type") != "challenge":
                raise ConnectionError("No challenge received")

            challenge = challenge_msg.get("challenge", "")
            response = hmac_mod.new(
                self.secret_key.encode(), challenge.encode(), hashlib.sha256
            ).hexdigest()
            self._send_frame(sock, {
                "response": response,
                "server_id": self.server_id,
            })

            # Wait for welcome
            welcome = self._recv_frame(sock)
            if not welcome:
                raise ConnectionError("No welcome received")

            peer_id = welcome.get("server_id")
            if not peer_id:
                raise ConnectionError("No server_id in welcome")

            # Store connection
            with self._lock:
                old = self._connections.get(peer_id)
                if old:
                    try:
                        old.close()
                    except Exception:
                        pass
                self._connections[peer_id] = sock

            logger.info(f"Mesh connected to peer: {peer_id} at {host}:{ws_port}")

            if self._on_peer_connected:
                self._on_peer_connected(peer_id)

            # Main listen loop
            sock.settimeout(30.0)
            self._listen_loop(sock, peer_id)

        except Exception as e:
            logger.debug(f"Mesh connect to {host}:{ws_port} failed: {e}")
        finally:
            self._cleanup_peer(peer_id, sock)
            # Schedule reconnection
            if self._running:
                self._schedule_reconnect(host, ws_port, peer_id)

    # ═══════════════════════════════════════════════════════════════════════
    # Common listen loop & cleanup
    # ═══════════════════════════════════════════════════════════════════════

    def _listen_loop(self, sock, peer_id):
        """Read messages from a connected peer until disconnect."""
        while self._running:
            data = self._recv_frame(sock)
            if data is None:
                break
            data["_from_peer"] = peer_id
            if self._on_message:
                try:
                    self._on_message(data)
                except Exception as e:
                    logger.debug(f"Message handler error: {e}")

    def _cleanup_peer(self, peer_id, sock):
        """Clean up after a peer disconnects."""
        if peer_id:
            with self._lock:
                # Only remove if this is still the active socket for this peer
                if self._connections.get(peer_id) is sock:
                    self._connections.pop(peer_id, None)
            logger.info(f"Mesh peer disconnected: {peer_id}")
            if self._on_peer_disconnected:
                self._on_peer_disconnected(peer_id)
        if sock:
            try:
                sock.close()
            except Exception:
                pass

    # ═══════════════════════════════════════════════════════════════════════
    # Reconnection with exponential backoff
    # ═══════════════════════════════════════════════════════════════════════

    def _reconnect_monitor(self):
        """Periodically attempt to reconnect to lost peers."""
        while self._running:
            eventlet.sleep(5)
            now = time.time()
            for key, info in list(self._reconnect_peers.items()):
                if info["attempts"] >= self._max_reconnect_attempts:
                    self._reconnect_peers.pop(key, None)
                    continue
                if now < info.get("next_retry", 0):
                    continue
                # Already connected?
                peer_id = info.get("peer_id")
                if peer_id and peer_id in self._connections:
                    self._reconnect_peers.pop(key, None)
                    continue
                host, ws_port = key
                info["attempts"] += 1
                # Exponential backoff: 2^attempts seconds, max 120s
                delay = min(2 ** info["attempts"], 120)
                info["next_retry"] = now + delay
                logger.debug(f"Reconnect attempt {info['attempts']} to {host}:{ws_port}")
                eventlet.spawn(self._connect_to, host, ws_port)

    def _schedule_reconnect(self, host, ws_port, peer_id=None):
        """Schedule a peer for reconnection."""
        key = (host, ws_port)
        if key not in self._reconnect_peers:
            self._reconnect_peers[key] = {
                "attempts": 0,
                "next_retry": time.time() + 2,
                "peer_id": peer_id,
            }

    # ═══════════════════════════════════════════════════════════════════════
    # Frame protocol: [1-byte flag][4-byte length][payload]
    # Flag 0x00 = plain JSON, Flag 0x01 = zlib compressed
    # ═══════════════════════════════════════════════════════════════════════

    def _send_frame(self, sock, data):
        """Send a JSON message with length-prefix framing."""
        try:
            payload = json.dumps(data).encode("utf-8")
            flag = 0x00
            # Compress large payloads
            if self._compress and len(payload) > 512:
                compressed = zlib.compress(payload)
                if len(compressed) < len(payload):
                    payload = compressed
                    flag = 0x01
            header = struct.pack(HEADER_FORMAT, flag, len(payload))
            sock.sendall(header + payload)
            return True
        except Exception as e:
            logger.debug(f"Send error: {e}")
            return False

    def _recv_frame(self, sock):
        """Receive a length-prefixed JSON message."""
        try:
            header = self._recv_exact(sock, HEADER_SIZE)
            if not header:
                return None
            flag, msg_len = struct.unpack(HEADER_FORMAT, header)
            if msg_len > MAX_MESSAGE_SIZE:
                logger.warning(f"Message too large: {msg_len} bytes")
                return None
            payload = self._recv_exact(sock, msg_len)
            if not payload:
                return None
            if flag == 0x01:
                payload = zlib.decompress(payload)
            return json.loads(payload.decode("utf-8"))
        except (socket.timeout, ConnectionResetError, BrokenPipeError):
            return None
        except Exception as e:
            logger.debug(f"Recv error: {e}")
            return None

    @staticmethod
    def _recv_exact(sock, n):
        """Receive exactly n bytes from socket."""
        buf = b""
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        return buf

    # ═══════════════════════════════════════════════════════════════════════
    # Public API (same interface as before)
    # ═══════════════════════════════════════════════════════════════════════

    def send_to_peer(self, peer_id, data):
        """Send a message to a specific peer."""
        with self._lock:
            sock = self._connections.get(peer_id)
        if sock:
            return self._send_frame(sock, data)
        return False

    def broadcast_to_peers(self, data):
        """Send a message to all connected peers."""
        with self._lock:
            peers = list(self._connections.items())
        for peer_id, sock in peers:
            self._send_frame(sock, data)

    def get_connected_peers(self):
        """Return list of connected peer IDs."""
        with self._lock:
            return list(self._connections.keys())

    def is_peer_connected(self, peer_id):
        """Check if a peer is connected."""
        return peer_id in self._connections

    def get_stats(self):
        """Return mesh bridge stats."""
        return {
            "ws_port": self.ws_port,
            "connected_peers": len(self._connections),
            "peer_ids": list(self._connections.keys()),
            "pending_reconnects": len(self._reconnect_peers),
            "compression": self._compress,
        }
