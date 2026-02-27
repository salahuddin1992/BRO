"""
Mesh Networking Module
Enables multiple BRO servers to discover each other and form
an interconnected mesh network. Supports up to 100+ servers.
"""
import socket
import json
import threading
import time
import logging
import hashlib
import secrets
from datetime import datetime

logger = logging.getLogger("BRO.mesh")


class MeshNode:
    """
    A mesh network node that can discover and connect to other BRO servers.
    Creates a decentralized mesh where any server can relay to any other.
    """

    def __init__(self, server_id, host, port, mesh_port=8401):
        self.server_id = server_id
        self.host = host
        self.port = port
        self.mesh_port = mesh_port
        self.token = secrets.token_hex(16)
        self.peers = {}  # {server_id: peer_info}
        self.routes = {}  # {server_id: next_hop_id}
        self._running = False
        self._lock = threading.Lock()
        self._discovery_thread = None
        self._heartbeat_thread = None
        self._listener_thread = None

    def start(self):
        """Start mesh networking."""
        self._running = True
        self._listener_thread = threading.Thread(
            target=self._listen, daemon=True
        )
        self._discovery_thread = threading.Thread(
            target=self._broadcast_presence, daemon=True
        )
        self._heartbeat_thread = threading.Thread(
            target=self._check_heartbeats, daemon=True
        )
        self._listener_thread.start()
        self._discovery_thread.start()
        self._heartbeat_thread.start()
        logger.info(f"Mesh node started: {self.server_id} on port {self.mesh_port}")

    def stop(self):
        """Stop mesh networking."""
        self._running = False
        self._broadcast_message({
            "type": "mesh_leave",
            "server_id": self.server_id,
        })
        logger.info(f"Mesh node stopped: {self.server_id}")

    def _listen(self):
        """Listen for mesh discovery and control messages via UDP."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except OSError:
            pass
        sock.settimeout(1.0)
        try:
            sock.bind(("", self.mesh_port))
        except OSError as e:
            logger.error(f"Cannot bind mesh port {self.mesh_port}: {e}")
            return

        while self._running:
            try:
                data, addr = sock.recvfrom(4096)
                msg = json.loads(data.decode("utf-8"))
                self._handle_mesh_message(msg, addr)
            except socket.timeout:
                continue
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            except Exception as e:
                logger.error(f"Mesh listener error: {e}")
                continue
        sock.close()

    def _broadcast_presence(self):
        """Periodically broadcast presence to discover other servers."""
        while self._running:
            self._broadcast_message({
                "type": "mesh_announce",
                "server_id": self.server_id,
                "host": self.host,
                "port": self.port,
                "mesh_port": self.mesh_port,
                "token": self.token,
                "timestamp": datetime.utcnow().isoformat(),
                "peer_count": len(self.peers),
            })
            time.sleep(5)

    def _broadcast_message(self, msg):
        """Send a UDP broadcast message."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            data = json.dumps(msg).encode("utf-8")
            sock.sendto(data, ("<broadcast>", self.mesh_port))
            sock.close()
        except OSError as e:
            logger.debug(f"Broadcast failed: {e}")
            # Try sending to known peers directly
            for peer_id, peer in self.peers.items():
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    data = json.dumps(msg).encode("utf-8")
                    sock.sendto(data, (peer["host"], peer["mesh_port"]))
                    sock.close()
                except OSError:
                    pass

    def _handle_mesh_message(self, msg, addr):
        """Process incoming mesh messages."""
        msg_type = msg.get("type")
        sender_id = msg.get("server_id")

        if sender_id == self.server_id:
            return

        if msg_type == "mesh_announce":
            self._handle_announce(msg, addr)
        elif msg_type == "mesh_leave":
            self._handle_leave(sender_id)
        elif msg_type == "mesh_relay":
            self._handle_relay(msg)
        elif msg_type == "mesh_route_update":
            self._handle_route_update(msg)

    def _handle_announce(self, msg, addr):
        """Handle peer announcement."""
        peer_id = msg["server_id"]
        with self._lock:
            is_new = peer_id not in self.peers
            self.peers[peer_id] = {
                "server_id": peer_id,
                "host": msg.get("host", addr[0]),
                "port": msg["port"],
                "mesh_port": msg.get("mesh_port", self.mesh_port),
                "token": msg.get("token"),
                "last_seen": datetime.utcnow().isoformat(),
                "peer_count": msg.get("peer_count", 0),
            }
            self.routes[peer_id] = peer_id

        if is_new:
            logger.info(f"New mesh peer discovered: {peer_id} at {addr[0]}:{msg['port']}")
            self._share_peer_list(peer_id)

    def _handle_leave(self, peer_id):
        """Handle peer leaving the mesh."""
        with self._lock:
            self.peers.pop(peer_id, None)
            self.routes.pop(peer_id, None)
            routes_to_remove = [
                k for k, v in self.routes.items() if v == peer_id
            ]
            for k in routes_to_remove:
                del self.routes[k]
        logger.info(f"Mesh peer left: {peer_id}")

    def _handle_relay(self, msg):
        """Handle relayed message - forward to target or process locally."""
        target_id = msg.get("target_id")
        if target_id == self.server_id:
            logger.debug(f"Received relayed message from {msg.get('origin_id')}")
            return msg.get("payload")
        elif target_id in self.routes:
            next_hop = self.routes[target_id]
            if next_hop in self.peers:
                peer = self.peers[next_hop]
                self._send_to_peer(peer, msg)

    def _handle_route_update(self, msg):
        """Update routing table from peer's known routes."""
        sender_id = msg.get("server_id")
        known_peers = msg.get("peers", [])
        with self._lock:
            for peer_info in known_peers:
                pid = peer_info.get("server_id")
                if pid and pid != self.server_id and pid not in self.peers:
                    self.peers[pid] = peer_info
                    self.routes[pid] = sender_id

    def _share_peer_list(self, target_peer_id):
        """Share known peers with a newly discovered peer."""
        if target_peer_id not in self.peers:
            return
        peer = self.peers[target_peer_id]
        peer_list = [
            {"server_id": p["server_id"], "host": p["host"],
             "port": p["port"], "mesh_port": p.get("mesh_port", self.mesh_port)}
            for p in self.peers.values()
            if p["server_id"] != target_peer_id
        ]
        msg = {
            "type": "mesh_route_update",
            "server_id": self.server_id,
            "peers": peer_list,
        }
        self._send_to_peer(peer, msg)

    def _send_to_peer(self, peer, msg):
        """Send a UDP message to a specific peer."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            data = json.dumps(msg).encode("utf-8")
            sock.sendto(data, (peer["host"], peer.get("mesh_port", self.mesh_port)))
            sock.close()
        except OSError as e:
            logger.debug(f"Failed to send to peer {peer.get('server_id')}: {e}")

    def _check_heartbeats(self):
        """Remove peers that haven't been seen recently."""
        while self._running:
            time.sleep(15)
            now = datetime.utcnow()
            with self._lock:
                stale = []
                for pid, peer in self.peers.items():
                    try:
                        last = datetime.fromisoformat(peer["last_seen"])
                        if (now - last).total_seconds() > 30:
                            stale.append(pid)
                    except (ValueError, KeyError):
                        stale.append(pid)
                for pid in stale:
                    del self.peers[pid]
                    self.routes.pop(pid, None)
                    logger.info(f"Mesh peer timed out: {pid}")

    def relay_message(self, target_id, payload):
        """Send a message to another server through the mesh."""
        if target_id in self.routes:
            next_hop = self.routes[target_id]
            if next_hop in self.peers:
                msg = {
                    "type": "mesh_relay",
                    "server_id": self.server_id,
                    "origin_id": self.server_id,
                    "target_id": target_id,
                    "payload": payload,
                    "timestamp": datetime.utcnow().isoformat(),
                }
                self._send_to_peer(self.peers[next_hop], msg)
                return True
        return False

    def connect_to_server(self, host, port):
        """Manually connect to a known server."""
        msg = {
            "type": "mesh_announce",
            "server_id": self.server_id,
            "host": self.host,
            "port": self.port,
            "mesh_port": self.mesh_port,
            "token": self.token,
            "timestamp": datetime.utcnow().isoformat(),
            "peer_count": len(self.peers),
        }
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            data = json.dumps(msg).encode("utf-8")
            sock.sendto(data, (host, port))
            sock.close()
            return True
        except OSError as e:
            logger.error(f"Manual connect failed to {host}:{port}: {e}")
            return False

    def get_peer_list(self):
        """Return list of all known peers."""
        with self._lock:
            return [
                {**p, "route": self.routes.get(p["server_id"])}
                for p in self.peers.values()
            ]

    def get_stats(self):
        """Return mesh network statistics."""
        with self._lock:
            return {
                "server_id": self.server_id,
                "peer_count": len(self.peers),
                "route_count": len(self.routes),
                "peers": list(self.peers.keys()),
            }
