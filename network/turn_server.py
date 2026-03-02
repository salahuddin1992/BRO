"""
Helen WiFi - Local TURN/STUN Server
Provides a local TURN/STUN server for WebRTC calls without internet.
Uses aioice for ICE candidate gathering on LAN.
"""
import asyncio
import logging
import threading
import socket

logger = logging.getLogger("BRO.turn")

# Default STUN/TURN ports
STUN_PORT = 3478


class LocalTurnServer:
    """Lightweight local STUN-like server for LAN WebRTC NAT traversal."""

    def __init__(self, host="0.0.0.0", port=STUN_PORT):
        self.host = host
        self.port = port
        self._running = False
        self._thread = None
        self._sock = None

    def start(self):
        """Start the local TURN server in a background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info(f"Local STUN/TURN server started on {self.host}:{self.port}")

    def stop(self):
        """Stop the local TURN server."""
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass

    def _run(self):
        """STUN binding request handler (RFC 5389 simplified)."""
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.settimeout(1.0)
            self._sock.bind((self.host, self.port))
        except OSError as e:
            logger.warning(f"STUN server bind failed on port {self.port}: {e}")
            return

        while self._running:
            try:
                data, addr = self._sock.recvfrom(2048)
                if len(data) >= 20:
                    # Parse STUN binding request (message type 0x0001)
                    msg_type = int.from_bytes(data[0:2], "big")
                    if msg_type == 0x0001:
                        response = self._build_binding_response(data, addr)
                        self._sock.sendto(response, addr)
            except socket.timeout:
                continue
            except Exception:
                continue

        try:
            self._sock.close()
        except Exception:
            pass

    def _build_binding_response(self, request, addr):
        """Build a STUN Binding Success Response (RFC 5389).

        Returns the client's reflexive transport address so WebRTC
        peers on the same LAN can discover their own IP:port.
        """
        # Transaction ID from request (bytes 8-20)
        txn_id = request[8:20]

        # XOR-MAPPED-ADDRESS attribute (type 0x0020)
        ip_bytes = socket.inet_aton(addr[0])
        port = addr[1]

        # Magic cookie
        magic = 0x2112A442
        xor_port = port ^ (magic >> 16)
        magic_bytes = magic.to_bytes(4, "big")
        xor_ip = bytes(a ^ b for a, b in zip(ip_bytes, magic_bytes))

        # Attribute: type(2) + length(2) + reserved(1) + family(1) + port(2) + ip(4)
        attr_value = b'\x00\x01' + xor_port.to_bytes(2, "big") + xor_ip
        attr = (0x0020).to_bytes(2, "big") + len(attr_value).to_bytes(2, "big") + attr_value

        # STUN header: type(2) + length(2) + magic(4) + txn_id(12)
        msg_type = (0x0101).to_bytes(2, "big")  # Binding Success Response
        msg_len = len(attr).to_bytes(2, "big")
        header = msg_type + msg_len + magic_bytes + txn_id

        return header + attr

    def get_ice_server_config(self, server_ip):
        """Return ICE server config pointing to this local STUN server."""
        return {"urls": f"stun:{server_ip}:{self.port}"}


def get_local_ice_candidates(host_ip):
    """Generate local ICE candidates using aioice for LAN discovery."""
    try:
        from aioice import Candidate
        candidates = []
        # Host candidate - direct LAN connection
        candidates.append({
            "type": "host",
            "ip": host_ip,
            "protocol": "udp",
            "priority": 2130706431,  # Host candidate priority
        })
        return candidates
    except ImportError:
        return [{"type": "host", "ip": host_ip, "protocol": "udp", "priority": 2130706431}]
