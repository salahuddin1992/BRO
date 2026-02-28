"""
Mesh Networking - UDP auto-discovery between servers
"""
import socket
import json
import threading
import time
import logging
from datetime import datetime

logger = logging.getLogger("BRO.mesh")


class MeshNode:
    def __init__(self, server_id, host, port, mesh_port=8401):
        self.server_id = server_id
        self.host = host
        self.port = port
        self.mesh_port = mesh_port
        self.peers = {}   # {peer_id: {server_id, host, port, last_seen, peer_count}}
        self._running = False
        self._lock = threading.Lock()

    def start(self):
        self._running = True
        threading.Thread(target=self._listen, daemon=True).start()
        threading.Thread(target=self._broadcast, daemon=True).start()
        threading.Thread(target=self._cleanup, daemon=True).start()
        logger.info(f"Mesh started on port {self.mesh_port}")

    def stop(self):
        self._running = False
        self._send_broadcast({"type": "leave", "server_id": self.server_id})

    def _listen(self):
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
            logger.error(f"Mesh bind failed: {e}")
            return

        while self._running:
            try:
                data, addr = sock.recvfrom(65535)
                msg = json.loads(data.decode())
                self._handle(msg, addr)
            except socket.timeout:
                continue
            except Exception:
                continue
        sock.close()

    def _handle(self, msg, addr):
        sid = msg.get("server_id")
        if sid == self.server_id:
            return

        if msg.get("type") == "announce":
            with self._lock:
                is_new = sid not in self.peers
                self.peers[sid] = {
                    "server_id": sid,
                    "host": msg.get("host", addr[0]),
                    "port": msg["port"],
                    "mesh_port": msg.get("mesh_port", self.mesh_port),
                    "last_seen": datetime.utcnow().isoformat(),
                    "peer_count": msg.get("peer_count", 0),
                }
            if is_new:
                logger.info(f"Mesh peer: {sid} at {addr[0]}")

        elif msg.get("type") == "leave":
            with self._lock:
                self.peers.pop(sid, None)

    def _broadcast(self):
        while self._running:
            self._send_broadcast({
                "type": "announce",
                "server_id": self.server_id,
                "host": self.host,
                "port": self.port,
                "mesh_port": self.mesh_port,
                "peer_count": len(self.peers),
            })
            time.sleep(5)

    def _send_broadcast(self, msg):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(json.dumps(msg).encode(), ("<broadcast>", self.mesh_port))
            sock.close()
        except OSError:
            pass

    def _cleanup(self):
        while self._running:
            time.sleep(15)
            now = datetime.utcnow()
            with self._lock:
                stale = []
                for pid, p in self.peers.items():
                    try:
                        last = datetime.fromisoformat(p["last_seen"])
                        if (now - last).total_seconds() > 30:
                            stale.append(pid)
                    except Exception:
                        stale.append(pid)
                for pid in stale:
                    del self.peers[pid]

    def connect_to(self, host, port):
        msg = {
            "type": "announce",
            "server_id": self.server_id,
            "host": self.host,
            "port": self.port,
            "mesh_port": self.mesh_port,
            "peer_count": len(self.peers),
        }
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(json.dumps(msg).encode(), (host, port))
            sock.close()
            return True
        except OSError:
            return False

    def get_peer_list(self):
        with self._lock:
            return list(self.peers.values())

    def get_stats(self):
        with self._lock:
            return {"peer_count": len(self.peers), "peers": list(self.peers.keys())}
