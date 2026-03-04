"""
Mesh Networking - UDP auto-discovery + HTTP inter-server communication
Enables cross-server calls, messages, and user sync.
"""
import hashlib
import hmac as hmac_mod
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
    def __init__(self, server_id, host, port, mesh_port=8401, interfaces=None):
        self.server_id = server_id
        self.host = host
        self.port = port            # HTTP server port
        self.mesh_port = mesh_port  # UDP discovery port
        self.interfaces = interfaces or []  # all detected network interfaces
        self.peers = {}             # {peer_id: {server_id, host, port, mesh_port, last_seen, ...}}
        self.remote_users = {}      # {server_id: [{sid, username}]}
        self._local_users = []      # cached for periodic sync
        self._running = False
        self._lock = threading.Lock()
        # Use HTTPS when TLS certificates are available
        self._use_tls = config.TLS_AVAILABLE
        self._scheme = "https" if self._use_tls else "http"

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
                signed_data, addr = sock.recvfrom(65535)
                # Verify HMAC signature
                data = self._verify_message(signed_data)
                if data is None:
                    continue  # reject unsigned/tampered messages
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
                    "all_ips": msg.get("all_ips", [msg.get("host", addr[0])]),
                    "reachable_ip": addr[0],  # IP that actually delivered the packet
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
            all_ips = [i["ip"] for i in self.interfaces] if self.interfaces else [self.host]
            self._send_broadcast({
                "type": "announce",
                "server_id": self.server_id,
                "host": self.host,
                "port": self.port,
                "mesh_port": self.mesh_port,
                "peer_count": len(self.peers),
                "all_ips": all_ips,
            })
            # Periodic user sync every 10s
            tick += 1
            if tick % 2 == 0 and self._local_users:
                self._do_sync(self._local_users)
            time.sleep(5)

    def _get_broadcast_addresses(self):
        """Calculate broadcast addresses for all detected subnets."""
        import struct as _struct
        broadcasts = set()
        for iface in self.interfaces:
            ip = iface.get("ip", "")
            mask = iface.get("netmask", "255.255.255.0")
            if not ip or not mask:
                continue
            try:
                ip_int = _struct.unpack(">I", socket.inet_aton(ip))[0]
                mask_int = _struct.unpack(">I", socket.inet_aton(mask))[0]
                bcast_int = ip_int | (~mask_int & 0xFFFFFFFF)
                bcast = socket.inet_ntoa(_struct.pack(">I", bcast_int))
                broadcasts.add(bcast)
            except Exception:
                continue
        # Always include global broadcast as fallback
        broadcasts.add("255.255.255.255")
        return list(broadcasts)

    def _sign_message(self, data):
        """Sign message data with HMAC-SHA256 using the shared secret."""
        mac = hmac_mod.new(config.SECRET_KEY.encode(), data, hashlib.sha256).digest()
        return mac + data

    def _verify_message(self, signed_data):
        """Verify HMAC signature and return the payload if valid."""
        if len(signed_data) < 32:
            return None
        received_mac = signed_data[:32]
        payload = signed_data[32:]
        expected_mac = hmac_mod.new(config.SECRET_KEY.encode(), payload, hashlib.sha256).digest()
        if hmac_mod.compare_digest(received_mac, expected_mac):
            return payload
        return None

    def _send_broadcast(self, msg):
        data = msgpack.packb(msg, use_bin_type=True)
        signed = self._sign_message(data)
        # Broadcast to every subnet's broadcast address (multi-network)
        targets = self._get_broadcast_addresses()
        for addr in targets:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.sendto(signed, (addr, self.mesh_port))
                sock.close()
            except OSError:
                try:
                    sock.close()
                except Exception:
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

    def _mesh_auth_headers(self, body_json=None):
        """Generate HMAC-based auth header instead of sending raw secret."""
        ts = str(int(time.time()))
        payload = ts.encode()
        if body_json:
            payload += json.dumps(body_json, sort_keys=True).encode()
        sig = hmac_mod.new(config.SECRET_KEY.encode(), payload, hashlib.sha256).hexdigest()
        return {"X-Mesh-Timestamp": ts, "X-Mesh-Signature": sig}

    def _sync_to_peer(self, peer, local_users):
        # Use reachable_ip (the IP that delivered UDP) if available, fallback to host
        host = peer.get("reachable_ip", peer["host"])
        try:
            url = f"{self._scheme}://{host}:{peer['port']}/api/mesh/sync-users"
            body = {
                "server_id": self.server_id,
                "host": self.host,
                "port": self.port,
                "users": local_users,
            }
            requests.post(url, json=body, headers=self._mesh_auth_headers(body),
                          timeout=3, verify=False)
        except Exception:
            pass

    def forward_to_peer(self, target_server_id, event, data):
        """Forward a socket event to a specific peer server"""
        with self._lock:
            peer = self.peers.get(target_server_id)
        if not peer:
            return False
        host = peer.get("reachable_ip", peer["host"])
        try:
            url = f"{self._scheme}://{host}:{peer['port']}/api/mesh/forward"
            body = {"event": event, "data": data}
            requests.post(url, json=body, headers=self._mesh_auth_headers(body),
                          timeout=5, verify=False)
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
            host = peer.get("reachable_ip", peer["host"])
            try:
                url = f"{self._scheme}://{host}:{peer['port']}/api/mesh/broadcast"
                body = {"event": event, "data": data}
                requests.post(url, json=body, headers=self._mesh_auth_headers(body),
                              timeout=3, verify=False)
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
            url = f"{self._scheme}://{host}:{port}/api/mesh/info"
            resp = requests.get(url, headers=self._mesh_auth_headers(), timeout=3, verify=False)
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
                    "all_ips": [host],
                    "reachable_ip": host,
                }
            logger.info(f"Manual connect: {sid} at {host}:{port}")
            if self._local_users:
                threading.Thread(target=self._sync_to_peer,
                                 args=(self.peers[sid], self._local_users),
                                 daemon=True).start()
            return True
        except Exception:
            pass
        # Fallback: UDP announce to all subnets
        all_ips = [i["ip"] for i in self.interfaces] if self.interfaces else [self.host]
        msg = {
            "type": "announce",
            "server_id": self.server_id,
            "host": self.host,
            "port": self.port,
            "mesh_port": self.mesh_port,
            "peer_count": len(self.peers),
            "all_ips": all_ips,
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
