"""
Helen WiFi - mDNS/DNS-SD Service Discovery
Uses zeroconf for automatic device discovery on the local network.
Devices find each other without knowing IP addresses (like AirDrop).
"""
import logging
import threading
import socket
import time

from zeroconf import ServiceBrowser, ServiceInfo, Zeroconf, IPVersion

logger = logging.getLogger("BRO.discovery")

# Service type for Helen WiFi
SERVICE_TYPE = "_helenwifi._tcp.local."
SERVICE_NAME_PREFIX = "HelenWiFi-"


class ServiceDiscovery:
    """mDNS/DNS-SD service discovery for automatic peer finding."""

    def __init__(self, server_id, host_ip, port, all_ips=None):
        self.server_id = server_id
        self.host_ip = host_ip
        self.port = port
        self.all_ips = all_ips or [host_ip]  # all interface IPs for multi-network
        self._zeroconf = None
        self._browser = None
        self._service_info = None
        self._discovered_peers = {}  # {name: {host, port, server_id, ...}}
        self._lock = threading.Lock()
        self._on_peer_found = None
        self._on_peer_lost = None

    def start(self, on_peer_found=None, on_peer_lost=None):
        """Start advertising this server and browsing for peers."""
        self._on_peer_found = on_peer_found
        self._on_peer_lost = on_peer_lost

        try:
            self._zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
        except Exception as e:
            logger.warning(f"Zeroconf init failed: {e}")
            return False

        # Register this server as a service
        self._register_service()

        # Browse for other Helen WiFi servers
        self._browser = ServiceBrowser(
            self._zeroconf, SERVICE_TYPE, self
        )

        logger.info(f"mDNS discovery started: {self.server_id}")
        return True

    def stop(self):
        """Stop discovery and unregister service."""
        if self._zeroconf:
            if self._service_info:
                try:
                    self._zeroconf.unregister_service(self._service_info)
                except Exception:
                    pass
            try:
                self._zeroconf.close()
            except Exception:
                pass
            self._zeroconf = None
        logger.info("mDNS discovery stopped")

    def _register_service(self):
        """Register this Helen WiFi server on all detected network interfaces."""
        service_name = f"{SERVICE_NAME_PREFIX}{self.server_id}.{SERVICE_TYPE}"

        # Pack all interface IPs for multi-network advertisement
        addresses = []
        for ip in self.all_ips:
            try:
                addresses.append(socket.inet_aton(ip))
            except OSError:
                continue
        if not addresses:
            try:
                addresses = [socket.inet_aton(self.host_ip)]
            except OSError:
                addresses = [socket.inet_aton("127.0.0.1")]

        self._service_info = ServiceInfo(
            type_=SERVICE_TYPE,
            name=service_name,
            addresses=addresses,
            port=self.port,
            properties={
                "server_id": self.server_id,
                "version": "1.0",
                "name": "Helen WiFi",
                "ips": ",".join(self.all_ips),
            },
        )

        try:
            self._zeroconf.register_service(self._service_info)
            logger.info(f"Registered mDNS on {len(addresses)} interface(s): {', '.join(self.all_ips)}")
        except Exception as e:
            logger.warning(f"Service registration failed: {e}")

    # --- ServiceBrowser callbacks ---

    def _get_service_info_safe(self, zc, type_, name):
        """Get service info in a real thread to avoid eventlet monkey-patch conflicts."""
        result = [None]

        def _fetch():
            try:
                result[0] = zc.get_service_info(type_, name, timeout=3000)
            except RuntimeError:
                # Eventlet monkey-patches can cause "Use AsyncServiceInfo" errors
                try:
                    info = ServiceInfo(type_, name)
                    if zc.get_service_info(type_, name, timeout=3000):
                        result[0] = info
                except Exception:
                    pass
            except Exception:
                pass

        import threading as _threading
        t = _threading.Thread(target=_fetch, daemon=True)
        t.start()
        t.join(timeout=5)
        return result[0]

    def add_service(self, zc, type_, name):
        """Called when a new Helen WiFi server is discovered."""
        info = self._get_service_info_safe(zc, type_, name)
        if not info:
            return

        props = {k.decode(): v.decode() if isinstance(v, bytes) else v
                 for k, v in info.properties.items()}
        peer_id = props.get("server_id", "")

        # Don't discover ourselves
        if peer_id == self.server_id:
            return

        addresses = info.parsed_addresses()
        if not addresses:
            return

        # Get all advertised IPs from properties (multi-network)
        all_ips = props.get("ips", "").split(",") if props.get("ips") else addresses
        peer_info = {
            "server_id": peer_id,
            "host": addresses[0],
            "port": info.port,
            "name": props.get("name", "Helen WiFi"),
            "version": props.get("version", "?"),
            "all_ips": all_ips,
        }

        with self._lock:
            self._discovered_peers[name] = peer_info

        logger.info(f"mDNS discovered peer: {peer_id} at {addresses[0]}:{info.port}")

        if self._on_peer_found:
            self._on_peer_found(peer_info)

    def remove_service(self, zc, type_, name):
        """Called when a Helen WiFi server goes offline."""
        with self._lock:
            peer_info = self._discovered_peers.pop(name, None)

        if peer_info:
            logger.info(f"mDNS peer lost: {peer_info.get('server_id', '?')}")
            if self._on_peer_lost:
                self._on_peer_lost(peer_info)

    def update_service(self, zc, type_, name):
        """Called when a service is updated."""
        # Re-add to refresh info
        self.add_service(zc, type_, name)

    def get_discovered_peers(self):
        """Return list of all discovered peers."""
        with self._lock:
            return list(self._discovered_peers.values())
