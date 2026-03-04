"""
Helen WiFi - Full TURN/STUN Server
Supports: STUN Binding + TURN Relay with UDP/TCP/TLS
REST API time-limited credentials (static-auth-secret)
Multiple ports: 3478 (UDP/TCP), 5349 (TLS), 443 (TLS fallback)
"""
import hashlib
import hmac
import logging
import os
import random
import secrets
import socket
import ssl
import struct
import threading
import time
from base64 import b64encode

logger = logging.getLogger("BRO.turn")

# ── STUN/TURN Constants ─────────────────────────────────────────────────────
STUN_PORT = 3478
TURN_TLS_PORT = 5349
TURN_443_PORT = 443
TURN_443_FALLBACK_PORT = 8443  # fallback when 443 requires elevated privileges

MAGIC_COOKIE = 0x2112A442
MAGIC_BYTES = MAGIC_COOKIE.to_bytes(4, "big")

# STUN message types
BINDING_REQUEST = 0x0001
BINDING_RESPONSE = 0x0101
BINDING_ERROR = 0x0111

# TURN message types
ALLOCATE_REQUEST = 0x0003
ALLOCATE_RESPONSE = 0x0103
ALLOCATE_ERROR = 0x0113
REFRESH_REQUEST = 0x0004
REFRESH_RESPONSE = 0x0104
CREATE_PERMISSION_REQUEST = 0x0008
CREATE_PERMISSION_RESPONSE = 0x0108
CHANNEL_BIND_REQUEST = 0x0009
CHANNEL_BIND_RESPONSE = 0x0109
SEND_INDICATION = 0x0016
DATA_INDICATION = 0x0017

# STUN attributes
ATTR_MAPPED_ADDRESS = 0x0001
ATTR_USERNAME = 0x0006
ATTR_MESSAGE_INTEGRITY = 0x0008
ATTR_ERROR_CODE = 0x0009
ATTR_XOR_MAPPED_ADDRESS = 0x0020
ATTR_REALM = 0x0014
ATTR_NONCE = 0x0015
ATTR_XOR_PEER_ADDRESS = 0x0012
ATTR_DATA = 0x0013
ATTR_LIFETIME = 0x000D
ATTR_REQUESTED_TRANSPORT = 0x0019
ATTR_XOR_RELAYED_ADDRESS = 0x0016
ATTR_SOFTWARE = 0x8022
ATTR_CHANNEL_NUMBER = 0x000C

# Transport protocols
TRANSPORT_UDP = 17
TRANSPORT_TCP = 6

# Allocation defaults
DEFAULT_LIFETIME = 600         # 10 minutes
MAX_LIFETIME = 3600            # 1 hour
PERMISSION_LIFETIME = 300      # 5 minutes
CHANNEL_LIFETIME = 600         # 10 minutes

# Relay port range
RELAY_PORT_MIN = 49152
RELAY_PORT_MAX = 65535


class TurnCredentials:
    """Time-limited TURN credentials using static-auth-secret (RFC 5766 REST API)."""

    def __init__(self, secret):
        self.secret = secret.encode() if isinstance(secret, str) else secret

    def generate(self, username=None, ttl=86400):
        """Generate time-limited credentials.

        Returns (username, password) where:
        - username = "{timestamp}:{original_username}"
        - password = base64(HMAC-SHA1(secret, username))
        """
        timestamp = int(time.time()) + ttl
        if username:
            turn_username = f"{timestamp}:{username}"
        else:
            turn_username = f"{timestamp}:{secrets.token_hex(4)}"
        mac = hmac.new(self.secret, turn_username.encode(), hashlib.sha1)
        turn_password = b64encode(mac.digest()).decode()
        return turn_username, turn_password

    def verify(self, username, password):
        """Verify time-limited credentials."""
        try:
            parts = username.split(":", 1)
            if len(parts) != 2:
                return False
            timestamp = int(parts[0])
            if time.time() > timestamp:
                return False  # Expired
            expected_mac = hmac.new(self.secret, username.encode(), hashlib.sha1)
            expected_password = b64encode(expected_mac.digest()).decode()
            return hmac.compare_digest(password, expected_password)
        except (ValueError, TypeError):
            return False


class Allocation:
    """TURN relay allocation."""

    def __init__(self, client_addr, relay_sock, relay_addr, transport, lifetime=DEFAULT_LIFETIME):
        self.client_addr = client_addr      # (ip, port) of the client
        self.relay_sock = relay_sock        # UDP socket for relaying
        self.relay_addr = relay_addr        # (ip, port) of the relay
        self.transport = transport          # UDP or TCP
        self.lifetime = lifetime
        self.created_at = time.time()
        self.refreshed_at = time.time()
        self.permissions = {}               # {peer_ip: expiry_time}
        self.channels = {}                  # {channel_number: {peer_addr, expiry}}
        self.channel_by_addr = {}           # {peer_addr: channel_number}

    @property
    def expired(self):
        return time.time() > self.refreshed_at + self.lifetime

    def refresh(self, lifetime=DEFAULT_LIFETIME):
        self.lifetime = min(lifetime, MAX_LIFETIME)
        self.refreshed_at = time.time()

    def add_permission(self, peer_ip):
        self.permissions[peer_ip] = time.time() + PERMISSION_LIFETIME

    def has_permission(self, peer_ip):
        expiry = self.permissions.get(peer_ip, 0)
        return time.time() < expiry

    def bind_channel(self, channel_number, peer_addr):
        self.channels[channel_number] = {
            "peer_addr": peer_addr,
            "expiry": time.time() + CHANNEL_LIFETIME,
        }
        self.channel_by_addr[peer_addr] = channel_number

    def close(self):
        try:
            self.relay_sock.close()
        except Exception:
            pass


class LocalTurnServer:
    """Full TURN/STUN server with relay support.

    Listeners:
    - UDP on port 3478 (STUN + TURN)
    - TCP on port 3478 (STUN + TURN)
    - TLS on port 5349 (STUN + TURN over TLS)
    - TLS on port 443  (TURN over TLS - firewall bypass)
    """

    def __init__(self, host="0.0.0.0", port=STUN_PORT, secret_key=None,
                 tls_cert=None, tls_key=None, relay_ip=None):
        self.host = host
        self.port = port
        self.secret_key = secret_key or secrets.token_hex(32)
        self.credentials = TurnCredentials(self.secret_key)
        self.tls_cert = tls_cert
        self.tls_key = tls_key
        self.relay_ip = relay_ip  # IP to use for relay addresses
        self._running = False
        self._threads = []
        self._udp_sock = None  # Main UDP socket for relay responses

        # Allocations: {(client_ip, client_port): Allocation}
        self._allocations = {}
        self._alloc_lock = threading.Lock()

        # Realm and nonce for auth
        self._realm = "helenwifi"
        self._nonces = {}  # {nonce: expiry_time}

        # Stats
        self._stats = {
            "stun_requests": 0,
            "turn_allocations": 0,
            "turn_relayed_bytes": 0,
            "active_allocations": 0,
        }

    def start(self):
        """Start all TURN server listeners."""
        if self._running:
            return
        self._running = True

        # UDP listener on 3478
        t1 = threading.Thread(target=self._run_udp, args=(self.port,), daemon=True)
        t1.start()
        self._threads.append(t1)
        logger.info(f"Local STUN/TURN server started on {self.host}:{self.port}")

        # TCP listener on 3478
        t2 = threading.Thread(target=self._run_tcp, args=(self.port, False), daemon=True)
        t2.start()
        self._threads.append(t2)
        logger.info(f"TURN/TCP listener on {self.host}:{self.port}")

        # TLS listener on 5349 (if certs available)
        if self.tls_cert and self.tls_key and os.path.isfile(self.tls_cert):
            t3 = threading.Thread(target=self._run_tcp, args=(TURN_TLS_PORT, True), daemon=True)
            t3.start()
            self._threads.append(t3)
            logger.info(f"TURN/TLS listener on {self.host}:{TURN_TLS_PORT}")

            # TLS listener on 443 (firewall bypass), fallback to 8443 if no permission
            self._turn_443_actual_port = TURN_443_PORT
            try:
                t4 = threading.Thread(target=self._run_tcp, args=(TURN_443_PORT, True), daemon=True)
                t4.start()
                self._threads.append(t4)
                logger.info(f"TURN/TLS-443 listener on {self.host}:{TURN_443_PORT}")
            except Exception as e:
                logger.warning(f"Could not bind TURN on port 443: {e} — trying {TURN_443_FALLBACK_PORT}")
                try:
                    self._turn_443_actual_port = TURN_443_FALLBACK_PORT
                    t4 = threading.Thread(target=self._run_tcp, args=(TURN_443_FALLBACK_PORT, True), daemon=True)
                    t4.start()
                    self._threads.append(t4)
                    logger.info(f"TURN/TLS-443 fallback listener on {self.host}:{TURN_443_FALLBACK_PORT}")
                except Exception as e2:
                    logger.warning(f"TURN 443 fallback also failed: {e2}")

        # Cleanup thread for expired allocations
        tc = threading.Thread(target=self._cleanup_loop, daemon=True)
        tc.start()
        self._threads.append(tc)

    def stop(self):
        """Stop all listeners."""
        self._running = False
        with self._alloc_lock:
            for alloc in self._allocations.values():
                alloc.close()
            self._allocations.clear()

    # ═══════════════════════════════════════════════════════════════════════
    # UDP Listener (STUN + TURN)
    # ═══════════════════════════════════════════════════════════════════════

    def _run_udp(self, port):
        """Main UDP listener for STUN binding and TURN relay."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # Increase UDP buffer size
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2 * 1024 * 1024)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 2 * 1024 * 1024)
            except Exception:
                pass
            sock.settimeout(1.0)
            sock.bind((self.host, port))
            self._udp_sock = sock  # Store for relay responses
        except OSError as e:
            logger.warning(f"STUN/TURN UDP bind failed on port {port}: {e}")
            return

        while self._running:
            try:
                data, addr = sock.recvfrom(65535)
                if len(data) < 20:
                    continue
                # Check if it's a STUN/TURN message (first two bits must be 0)
                if data[0] & 0xC0 != 0:
                    # Could be ChannelData (first two bits = 01)
                    if data[0] & 0xC0 == 0x40:
                        self._handle_channel_data(data, addr, sock)
                    continue
                msg_type = int.from_bytes(data[0:2], "big")
                response = self._handle_stun_message(msg_type, data, addr, "udp")
                if response:
                    sock.sendto(response, addr)
            except socket.timeout:
                continue
            except Exception:
                continue

        try:
            sock.close()
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════════════════
    # TCP Listener (STUN + TURN over TCP/TLS)
    # ═══════════════════════════════════════════════════════════════════════

    def _run_tcp(self, port, use_tls):
        """TCP/TLS listener for STUN/TURN."""
        try:
            server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_sock.settimeout(1.0)
            server_sock.bind((self.host, port))
            server_sock.listen(64)
        except OSError as e:
            logger.warning(f"TURN TCP bind failed on port {port}: {e}")
            return

        if use_tls:
            try:
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                ctx.load_cert_chain(self.tls_cert, self.tls_key)
                ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            except Exception as e:
                logger.warning(f"TLS setup failed: {e}")
                server_sock.close()
                return

        while self._running:
            try:
                client_sock, addr = server_sock.accept()
                if use_tls:
                    try:
                        client_sock = ctx.wrap_socket(client_sock, server_side=True)
                    except ssl.SSLError:
                        client_sock.close()
                        continue
                t = threading.Thread(target=self._handle_tcp_client,
                                     args=(client_sock, addr), daemon=True)
                t.start()
            except socket.timeout:
                continue
            except Exception:
                continue

        try:
            server_sock.close()
        except Exception:
            pass

    def _handle_tcp_client(self, sock, addr):
        """Handle a single TCP/TLS STUN/TURN client."""
        sock.settimeout(30.0)
        try:
            while self._running:
                # TURN over TCP uses a 2-byte length prefix
                header = self._tcp_recv(sock, 2)
                if not header:
                    break
                length = int.from_bytes(header, "big")
                if length < 20 or length > 65535:
                    break
                data = self._tcp_recv(sock, length)
                if not data:
                    break

                msg_type = int.from_bytes(data[0:2], "big")
                response = self._handle_stun_message(msg_type, data, addr, "tcp")
                if response:
                    # TCP: prepend 2-byte length
                    sock.sendall(len(response).to_bytes(2, "big") + response)
        except (socket.timeout, ConnectionResetError, BrokenPipeError):
            pass
        except Exception:
            pass
        finally:
            try:
                sock.close()
            except Exception:
                pass

    @staticmethod
    def _tcp_recv(sock, n):
        """Receive exactly n bytes from TCP socket."""
        buf = b""
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        return buf

    # ═══════════════════════════════════════════════════════════════════════
    # STUN/TURN Message Handler
    # ═══════════════════════════════════════════════════════════════════════

    def _handle_stun_message(self, msg_type, data, addr, transport):
        """Route STUN/TURN message to appropriate handler."""
        txn_id = data[8:20]

        if msg_type == BINDING_REQUEST:
            self._stats["stun_requests"] += 1
            return self._build_binding_response(data, addr)

        elif msg_type == ALLOCATE_REQUEST:
            return self._handle_allocate(data, addr, txn_id, transport)

        elif msg_type == REFRESH_REQUEST:
            return self._handle_refresh(data, addr, txn_id)

        elif msg_type == CREATE_PERMISSION_REQUEST:
            return self._handle_create_permission(data, addr, txn_id)

        elif msg_type == CHANNEL_BIND_REQUEST:
            return self._handle_channel_bind(data, addr, txn_id)

        elif msg_type == SEND_INDICATION:
            self._handle_send_indication(data, addr)
            return None  # Indications get no response

        return None

    # ═══════════════════════════════════════════════════════════════════════
    # STUN Binding
    # ═══════════════════════════════════════════════════════════════════════

    def _build_binding_response(self, request, addr):
        """Build a STUN Binding Success Response (RFC 5389)."""
        txn_id = request[8:20]
        ip_bytes = socket.inet_aton(addr[0])
        port = addr[1]
        xor_port = port ^ (MAGIC_COOKIE >> 16)
        xor_ip = bytes(a ^ b for a, b in zip(ip_bytes, MAGIC_BYTES))

        # XOR-MAPPED-ADDRESS
        attr_value = b'\x00\x01' + xor_port.to_bytes(2, "big") + xor_ip
        attrs = self._build_attr(ATTR_XOR_MAPPED_ADDRESS, attr_value)

        # SOFTWARE
        sw = b"HelenWiFi-TURN/2.0"
        attrs += self._build_attr(ATTR_SOFTWARE, sw)

        return self._build_response(BINDING_RESPONSE, txn_id, attrs)

    # ═══════════════════════════════════════════════════════════════════════
    # TURN Allocate
    # ═══════════════════════════════════════════════════════════════════════

    def _handle_allocate(self, data, addr, txn_id, transport):
        """Handle TURN Allocate Request (RFC 5766)."""
        # Parse attributes for auth
        attrs = self._parse_attributes(data)
        username_attr = attrs.get(ATTR_USERNAME)
        integrity = attrs.get(ATTR_MESSAGE_INTEGRITY)

        # First request without auth -> send 401 with nonce/realm
        if not username_attr or not integrity:
            nonce = secrets.token_hex(16)
            self._nonces[nonce] = time.time() + 300  # 5min validity
            return self._build_error_response(ALLOCATE_ERROR, txn_id, 401,
                                               "Unauthorized", nonce=nonce)

        # Verify credentials
        username = username_attr.decode("utf-8", errors="replace").rstrip('\x00')
        nonce_attr = attrs.get(ATTR_NONCE, b"").decode("utf-8", errors="replace").rstrip('\x00')
        if nonce_attr not in self._nonces or time.time() > self._nonces.get(nonce_attr, 0):
            nonce = secrets.token_hex(16)
            self._nonces[nonce] = time.time() + 300
            return self._build_error_response(ALLOCATE_ERROR, txn_id, 438,
                                               "Stale Nonce", nonce=nonce)

        # Check if allocation already exists
        with self._alloc_lock:
            if addr in self._allocations:
                alloc = self._allocations[addr]
                if not alloc.expired:
                    return self._build_error_response(ALLOCATE_ERROR, txn_id, 437,
                                                       "Allocation Mismatch")

        # Get requested transport
        req_transport = attrs.get(ATTR_REQUESTED_TRANSPORT)
        proto = TRANSPORT_UDP
        if req_transport and len(req_transport) >= 1:
            proto = req_transport[0]

        # Get requested lifetime
        lifetime = DEFAULT_LIFETIME
        if ATTR_LIFETIME in attrs and len(attrs[ATTR_LIFETIME]) >= 4:
            lifetime = int.from_bytes(attrs[ATTR_LIFETIME][:4], "big")
            lifetime = min(lifetime, MAX_LIFETIME)

        # Create relay socket
        relay_ip = self.relay_ip or self._get_relay_ip()
        relay_sock, relay_port = self._create_relay_socket()
        if not relay_sock:
            return self._build_error_response(ALLOCATE_ERROR, txn_id, 508,
                                               "Insufficient Capacity")

        relay_addr = (relay_ip, relay_port)

        # Create allocation
        alloc = Allocation(addr, relay_sock, relay_addr, transport, lifetime)
        with self._alloc_lock:
            self._allocations[addr] = alloc
        self._stats["turn_allocations"] += 1

        # Start relay listener
        t = threading.Thread(target=self._relay_listener, args=(alloc,), daemon=True)
        t.start()

        logger.info(f"TURN allocation: {addr} -> relay {relay_addr} (lifetime={lifetime}s)")

        # Build success response
        resp_attrs = b""

        # XOR-RELAYED-ADDRESS
        r_ip_bytes = socket.inet_aton(relay_ip)
        r_xor_port = relay_port ^ (MAGIC_COOKIE >> 16)
        r_xor_ip = bytes(a ^ b for a, b in zip(r_ip_bytes, MAGIC_BYTES))
        resp_attrs += self._build_attr(ATTR_XOR_RELAYED_ADDRESS,
                                        b'\x00\x01' + r_xor_port.to_bytes(2, "big") + r_xor_ip)

        # XOR-MAPPED-ADDRESS
        c_ip_bytes = socket.inet_aton(addr[0])
        c_xor_port = addr[1] ^ (MAGIC_COOKIE >> 16)
        c_xor_ip = bytes(a ^ b for a, b in zip(c_ip_bytes, MAGIC_BYTES))
        resp_attrs += self._build_attr(ATTR_XOR_MAPPED_ADDRESS,
                                        b'\x00\x01' + c_xor_port.to_bytes(2, "big") + c_xor_ip)

        # LIFETIME
        resp_attrs += self._build_attr(ATTR_LIFETIME, lifetime.to_bytes(4, "big"))

        return self._build_response(ALLOCATE_RESPONSE, txn_id, resp_attrs)

    # ═══════════════════════════════════════════════════════════════════════
    # TURN Refresh
    # ═══════════════════════════════════════════════════════════════════════

    def _handle_refresh(self, data, addr, txn_id):
        """Handle TURN Refresh Request."""
        with self._alloc_lock:
            alloc = self._allocations.get(addr)
        if not alloc:
            return self._build_error_response(REFRESH_RESPONSE + 0x10, txn_id, 437,
                                               "Allocation Mismatch")

        attrs = self._parse_attributes(data)
        lifetime = DEFAULT_LIFETIME
        if ATTR_LIFETIME in attrs and len(attrs[ATTR_LIFETIME]) >= 4:
            lifetime = int.from_bytes(attrs[ATTR_LIFETIME][:4], "big")

        if lifetime == 0:
            # Delete allocation
            with self._alloc_lock:
                alloc = self._allocations.pop(addr, None)
            if alloc:
                alloc.close()
            lifetime = 0
        else:
            lifetime = min(lifetime, MAX_LIFETIME)
            alloc.refresh(lifetime)

        resp_attrs = self._build_attr(ATTR_LIFETIME, lifetime.to_bytes(4, "big"))
        return self._build_response(REFRESH_RESPONSE, txn_id, resp_attrs)

    # ═══════════════════════════════════════════════════════════════════════
    # TURN CreatePermission
    # ═══════════════════════════════════════════════════════════════════════

    def _handle_create_permission(self, data, addr, txn_id):
        """Handle TURN CreatePermission Request."""
        with self._alloc_lock:
            alloc = self._allocations.get(addr)
        if not alloc:
            return self._build_error_response(CREATE_PERMISSION_RESPONSE + 0x10, txn_id, 437,
                                               "Allocation Mismatch")

        attrs = self._parse_attributes(data)
        peer_addr_attr = attrs.get(ATTR_XOR_PEER_ADDRESS)
        if peer_addr_attr and len(peer_addr_attr) >= 8:
            peer_ip = self._decode_xor_address(peer_addr_attr, data[8:20])[0]
            alloc.add_permission(peer_ip)
            logger.debug(f"Permission created: {addr} -> {peer_ip}")

        return self._build_response(CREATE_PERMISSION_RESPONSE, txn_id, b"")

    # ═══════════════════════════════════════════════════════════════════════
    # TURN ChannelBind
    # ═══════════════════════════════════════════════════════════════════════

    def _handle_channel_bind(self, data, addr, txn_id):
        """Handle TURN ChannelBind Request."""
        with self._alloc_lock:
            alloc = self._allocations.get(addr)
        if not alloc:
            return self._build_error_response(CHANNEL_BIND_RESPONSE + 0x10, txn_id, 437,
                                               "Allocation Mismatch")

        attrs = self._parse_attributes(data)
        channel_attr = attrs.get(ATTR_CHANNEL_NUMBER)
        peer_attr = attrs.get(ATTR_XOR_PEER_ADDRESS)

        if not channel_attr or not peer_attr:
            return self._build_error_response(CHANNEL_BIND_RESPONSE + 0x10, txn_id, 400,
                                               "Bad Request")

        channel_number = int.from_bytes(channel_attr[:2], "big")
        peer_ip, peer_port = self._decode_xor_address(peer_attr, data[8:20])

        if channel_number < 0x4000 or channel_number > 0x7FFE:
            return self._build_error_response(CHANNEL_BIND_RESPONSE + 0x10, txn_id, 400,
                                               "Bad Request")

        alloc.bind_channel(channel_number, (peer_ip, peer_port))
        alloc.add_permission(peer_ip)

        return self._build_response(CHANNEL_BIND_RESPONSE, txn_id, b"")

    # ═══════════════════════════════════════════════════════════════════════
    # TURN Send/Data Indication
    # ═══════════════════════════════════════════════════════════════════════

    def _handle_send_indication(self, data, addr):
        """Handle TURN Send Indication - relay data to peer."""
        with self._alloc_lock:
            alloc = self._allocations.get(addr)
        if not alloc:
            return

        attrs = self._parse_attributes(data)
        peer_attr = attrs.get(ATTR_XOR_PEER_ADDRESS)
        payload = attrs.get(ATTR_DATA)

        if not peer_attr or not payload:
            return

        peer_ip, peer_port = self._decode_xor_address(peer_attr, data[8:20])

        if not alloc.has_permission(peer_ip):
            return

        try:
            alloc.relay_sock.sendto(payload, (peer_ip, peer_port))
            self._stats["turn_relayed_bytes"] += len(payload)
        except Exception:
            pass

    def _handle_channel_data(self, data, addr, sock):
        """Handle ChannelData message - fast relay path."""
        if len(data) < 4:
            return
        with self._alloc_lock:
            alloc = self._allocations.get(addr)
        if not alloc:
            return

        channel_number = int.from_bytes(data[0:2], "big")
        length = int.from_bytes(data[2:4], "big")
        payload = data[4:4 + length]

        channel = alloc.channels.get(channel_number)
        if not channel:
            return

        peer_addr = channel["peer_addr"]
        try:
            alloc.relay_sock.sendto(payload, peer_addr)
            self._stats["turn_relayed_bytes"] += len(payload)
        except Exception:
            pass

    def _relay_listener(self, alloc):
        """Listen on relay socket and forward data back to client."""
        alloc.relay_sock.settimeout(1.0)
        while self._running and not alloc.expired:
            try:
                data, peer_addr = alloc.relay_sock.recvfrom(65535)
                if not alloc.has_permission(peer_addr[0]):
                    continue

                # Check for channel binding - use fast ChannelData
                channel_num = alloc.channel_by_addr.get(peer_addr)
                if channel_num:
                    # ChannelData format
                    channel_data = (channel_num.to_bytes(2, "big") +
                                    len(data).to_bytes(2, "big") + data)
                    # Send back to client via original server socket
                    # (for UDP, we need the server socket - use a helper)
                    self._send_to_client(alloc.client_addr, channel_data)
                else:
                    # Data Indication
                    txn_id = secrets.token_bytes(12)
                    peer_ip_bytes = socket.inet_aton(peer_addr[0])
                    xor_port = peer_addr[1] ^ (MAGIC_COOKIE >> 16)
                    xor_ip = bytes(a ^ b for a, b in zip(peer_ip_bytes, MAGIC_BYTES))
                    peer_attr = self._build_attr(ATTR_XOR_PEER_ADDRESS,
                                                  b'\x00\x01' + xor_port.to_bytes(2, "big") + xor_ip)
                    data_attr = self._build_attr(ATTR_DATA, data)
                    indication = self._build_response(DATA_INDICATION, txn_id, peer_attr + data_attr)
                    self._send_to_client(alloc.client_addr, indication)

                self._stats["turn_relayed_bytes"] += len(data)
            except socket.timeout:
                continue
            except Exception:
                continue

    def _send_to_client(self, client_addr, data):
        """Send data back to client through the main TURN UDP socket."""
        try:
            if self._udp_sock:
                self._udp_sock.sendto(data, client_addr)
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════════════════
    # Helper Methods
    # ═══════════════════════════════════════════════════════════════════════

    def _create_relay_socket(self):
        """Create a UDP socket for relaying on a random port."""
        for _ in range(50):  # Try up to 50 times
            port = random.randint(RELAY_PORT_MIN, RELAY_PORT_MAX)
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind((self.host, port))
                return sock, port
            except OSError:
                try:
                    sock.close()
                except Exception:
                    pass
                continue
        return None, 0

    def _get_relay_ip(self):
        """Get the best IP address for relay."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(1)
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def _parse_attributes(self, data):
        """Parse STUN/TURN attributes from message."""
        attrs = {}
        if len(data) < 20:
            return attrs
        msg_len = int.from_bytes(data[2:4], "big")
        pos = 20
        end = min(20 + msg_len, len(data))
        while pos + 4 <= end:
            attr_type = int.from_bytes(data[pos:pos + 2], "big")
            attr_len = int.from_bytes(data[pos + 2:pos + 4], "big")
            if pos + 4 + attr_len > end:
                break
            attrs[attr_type] = data[pos + 4:pos + 4 + attr_len]
            # STUN attributes are padded to 4-byte boundaries
            pos += 4 + attr_len
            if pos % 4:
                pos += 4 - (pos % 4)
        return attrs

    def _decode_xor_address(self, attr_value, txn_id):
        """Decode XOR-MAPPED-ADDRESS or XOR-PEER-ADDRESS."""
        if len(attr_value) < 8:
            return ("0.0.0.0", 0)
        family = attr_value[1]
        xor_port = int.from_bytes(attr_value[2:4], "big")
        port = xor_port ^ (MAGIC_COOKIE >> 16)
        if family == 0x01:  # IPv4
            xor_ip = attr_value[4:8]
            ip_bytes = bytes(a ^ b for a, b in zip(xor_ip, MAGIC_BYTES))
            ip = socket.inet_ntoa(ip_bytes)
        else:
            ip = "0.0.0.0"
        return (ip, port)

    @staticmethod
    def _build_attr(attr_type, value):
        """Build a STUN attribute."""
        attr = attr_type.to_bytes(2, "big") + len(value).to_bytes(2, "big") + value
        # Pad to 4-byte boundary
        pad = (4 - len(value) % 4) % 4
        return attr + b'\x00' * pad

    @staticmethod
    def _build_response(msg_type, txn_id, attrs):
        """Build a STUN response message."""
        header = (msg_type.to_bytes(2, "big") +
                  len(attrs).to_bytes(2, "big") +
                  MAGIC_BYTES + txn_id)
        return header + attrs

    def _build_error_response(self, msg_type, txn_id, code, reason, nonce=None):
        """Build a STUN error response with optional realm/nonce."""
        # ERROR-CODE attribute
        cls = code // 100
        num = code % 100
        reason_bytes = reason.encode()
        error_value = b'\x00\x00' + bytes([cls]) + bytes([num]) + reason_bytes
        attrs = self._build_attr(ATTR_ERROR_CODE, error_value)

        # REALM
        attrs += self._build_attr(ATTR_REALM, self._realm.encode())

        # NONCE
        if nonce:
            attrs += self._build_attr(ATTR_NONCE, nonce.encode())

        return self._build_response(msg_type, txn_id, attrs)

    def _cleanup_loop(self):
        """Periodically clean up expired allocations and nonces."""
        while self._running:
            try:
                time.sleep(30)
            except Exception:
                break

            now = time.time()

            # Clean expired allocations
            with self._alloc_lock:
                expired = [addr for addr, alloc in self._allocations.items() if alloc.expired]
                for addr in expired:
                    alloc = self._allocations.pop(addr)
                    alloc.close()
                    logger.debug(f"Allocation expired: {addr}")
                self._stats["active_allocations"] = len(self._allocations)

            # Clean expired nonces
            expired_nonces = [n for n, exp in self._nonces.items() if now > exp]
            for n in expired_nonces:
                self._nonces.pop(n, None)

    # ═══════════════════════════════════════════════════════════════════════
    # REST API for ICE Server Config
    # ═══════════════════════════════════════════════════════════════════════

    def get_ice_server_config(self, server_ip, username=None):
        """Return ICE server configuration with TURN credentials."""
        turn_user, turn_pass = self.credentials.generate(username)

        servers = [
            # STUN
            {"urls": f"stun:{server_ip}:{self.port}"},
            # TURN UDP
            {"urls": f"turn:{server_ip}:{self.port}?transport=udp",
             "username": turn_user, "credential": turn_pass},
            # TURN TCP
            {"urls": f"turn:{server_ip}:{self.port}?transport=tcp",
             "username": turn_user, "credential": turn_pass},
        ]

        # TLS endpoints
        if self.tls_cert and os.path.isfile(self.tls_cert):
            servers.extend([
                # TURN TLS on 5349
                {"urls": f"turns:{server_ip}:{TURN_TLS_PORT}?transport=tcp",
                 "username": turn_user, "credential": turn_pass},
                # TURN TLS on 443 (firewall bypass) — uses actual bound port
                {"urls": f"turns:{server_ip}:{getattr(self, '_turn_443_actual_port', TURN_443_PORT)}?transport=tcp",
                 "username": turn_user, "credential": turn_pass},
            ])

        return {"iceServers": servers}

    def get_stats(self):
        """Get TURN server statistics."""
        with self._alloc_lock:
            self._stats["active_allocations"] = len(self._allocations)
        return dict(self._stats)


def get_local_ice_candidates(host_ip):
    """Generate local ICE candidates for LAN discovery."""
    try:
        from aioice import Candidate
        candidates = []
        candidates.append({
            "type": "host",
            "ip": host_ip,
            "protocol": "udp",
            "priority": 2130706431,
        })
        return candidates
    except ImportError:
        return [{"type": "host", "ip": host_ip, "protocol": "udp", "priority": 2130706431}]
