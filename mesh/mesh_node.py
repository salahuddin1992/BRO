"""
Mesh Networking - UDP auto-discovery + HTTP inter-server communication
Enables cross-server calls, messages, and user sync.
"""
import socket
import json
import threading
import time
import logging
from datetime import datetime

import msgpack
import requests

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

logger = logging.getLogger("BRO.mesh")


class MeshNode:
    def __init__(self, server_id, host, port, mesh_port=8401):
        self.server_id = server_id
        self.host = host
        self.port = port            # HTTP server port
        self.mesh_port = mesh_port  # UDP discovery port
        self.peers = {}             # {peer_id: {server_id, host, port, mesh_port, last_seen, ...}}
        self.remote_users = {}      # {server_id: [{sid, username}]}
        self._local_users = []      # cached for periodic sync
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

    # --- UDP Discovery ---

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
                # Try msgpack first, fallback to JSON for compatibility
                try:
                    msg = msgpack.unpackb(data, raw=False)
                except Exception:
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
                if self._local_users:
                    threading.Thread(target=self._sync_to_peer,
                                     args=(self.peers[sid], self._local_users),
                                     daemon=True).start()

        elif msg.get("type") == "leave":
            with self._lock:
                self.peers.pop(sid, None)
                self.remote_users.pop(sid, None)

    def _broadcast(self):
        tick = 0
        while self._running:
            self._send_broadcast({
                "type": "announce",
                "server_id": self.server_id,
                "host": self.host,
                "port": self.port,
                "mesh_port": self.mesh_port,
                "peer_count": len(self.peers),
            })
            # Periodic user sync every 10s
            tick += 1
            if tick % 2 == 0 and self._local_users:
                self._do_sync(self._local_users)
            time.sleep(5)

    def _send_broadcast(self, msg):
        data = msgpack.packb(msg, use_bin_type=True)
        for addr in ("255.255.255.255", "<broadcast>"):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.sendto(data, (addr, self.mesh_port))
                sock.close()
                return
            except OSError:
                try:
                    sock.close()
                except Exception:
                    pass
                continue

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
                    self.remote_users.pop(pid, None)

    # --- Inter-server HTTP Communication ---

    def sync_users(self, local_users):
        """Send local user list to all mesh peers (async)"""
        self._local_users = local_users
        threading.Thread(target=self._do_sync, args=(local_users,), daemon=True).start()

    def _do_sync(self, local_users):
        with self._lock:
            peers = list(self.peers.values())
        for peer in peers:
            self._sync_to_peer(peer, local_users)

    def _sync_to_peer(self, peer, local_users):
        try:
            url = f"http://{peer['host']}:{peer['port']}/api/mesh/sync-users"
            requests.post(url, json={
                "server_id": self.server_id,
                "host": self.host,
                "port": self.port,
                "users": local_users,
            }, headers={"X-Mesh-Secret": config.SECRET_KEY}, timeout=3)
        except Exception:
            pass

    def forward_to_peer(self, target_server_id, event, data):
        """Forward a socket event to a specific peer server"""
        with self._lock:
            peer = self.peers.get(target_server_id)
        if not peer:
            return False
        try:
            url = f"http://{peer['host']}:{peer['port']}/api/mesh/forward"
            requests.post(url, json={"event": event, "data": data},
                          headers={"X-Mesh-Secret": config.SECRET_KEY}, timeout=5)
            return True
        except Exception as e:
            logger.warning(f"Forward to {target_server_id} failed: {e}")
            return False

    def broadcast_to_peers(self, event, data):
        """Forward a broadcast event to all peers (async)"""
        threading.Thread(target=self._do_broadcast_forward, args=(event, data), daemon=True).start()

    def _do_broadcast_forward(self, event, data):
        with self._lock:
            peers = list(self.peers.values())
        for peer in peers:
            try:
                url = f"http://{peer['host']}:{peer['port']}/api/mesh/broadcast"
                requests.post(url, json={"event": event, "data": data},
                              headers={"X-Mesh-Secret": config.SECRET_KEY}, timeout=3)
            except Exception:
                pass

    # --- Remote User Management ---

    def update_remote_users(self, server_id, users):
        with self._lock:
            self.remote_users[server_id] = users

    def touch_peer(self, server_id, host, port):
        """Update last_seen for a peer (or auto-add if unknown)"""
        with self._lock:
            if server_id in self.peers:
                self.peers[server_id]["last_seen"] = datetime.utcnow().isoformat()
            else:
                self.peers[server_id] = {
                    "server_id": server_id,
                    "host": host,
                    "port": port,
                    "mesh_port": self.mesh_port,
                    "last_seen": datetime.utcnow().isoformat(),
                    "peer_count": 0,
                }

    def find_user_server(self, target_sid):
        """Find which peer server has a user by their SID"""
        with self._lock:
            for srv_id, users in self.remote_users.items():
                for u in users:
                    if u.get("sid") == target_sid:
                        return srv_id
        return None

    def get_all_remote_users(self):
        """Get all users from all remote servers"""
        with self._lock:
            result = []
            for srv_id, users in self.remote_users.items():
                for u in users:
                    result.append({**u, "server_id": srv_id, "remote": True})
            return result

    # --- Manual Connect ---

    def connect_to(self, host, port):
        """Manually connect to a peer (HTTP first, UDP fallback)"""
        # Try HTTP discovery
        try:
            url = f"http://{host}:{port}/api/mesh/info"
            resp = requests.get(url, headers={"X-Mesh-Secret": config.SECRET_KEY}, timeout=3)
            info = resp.json()
            sid = info["server_id"]
            with self._lock:
                self.peers[sid] = {
                    "server_id": sid,
                    "host": host,
                    "port": info.get("port", port),
                    "mesh_port": info.get("mesh_port", self.mesh_port),
                    "last_seen": datetime.utcnow().isoformat(),
                    "peer_count": 0,
                }
            logger.info(f"Manual connect: {sid} at {host}:{port}")
            if self._local_users:
                threading.Thread(target=self._sync_to_peer,
                                 args=(self.peers[sid], self._local_users),
                                 daemon=True).start()
            return True
        except Exception:
            pass
        # Fallback: UDP announce
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
            sock.sendto(msgpack.packb(msg, use_bin_type=True), (host, int(port)))
            sock.close()
            return True
        except OSError:
            return False

    def get_peer_list(self):
        with self._lock:
            return list(self.peers.values())

    def get_stats(self):
        with self._lock:
            remote_count = sum(len(u) for u in self.remote_users.values())
            return {
                "peer_count": len(self.peers),
                "peers": list(self.peers.values()),
                "remote_users_count": remote_count,
            }
