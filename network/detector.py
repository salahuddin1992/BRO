"""
Network Auto-Detection Module
Detects all network interfaces and router types automatically.
Supports: WiFi, Ethernet, DSL, ADSL, VDSL, Fiber, GPON, EPON,
          4G, LTE, 5G, Cellular, VPN, and all router types.
"""
import socket
import struct
import subprocess
import platform
import logging
import json
from datetime import datetime

logger = logging.getLogger("BRO.network")


class NetworkInterface:
    """Represents a detected network interface."""

    def __init__(self, name, ip, netmask, mac, interface_type, gateway=None):
        self.name = name
        self.ip = ip
        self.netmask = netmask
        self.mac = mac
        self.interface_type = interface_type
        self.gateway = gateway
        self.is_active = True
        self.detected_at = datetime.utcnow().isoformat()

    def to_dict(self):
        return {
            "name": self.name,
            "ip": self.ip,
            "netmask": self.netmask,
            "mac": self.mac,
            "type": self.interface_type,
            "gateway": self.gateway,
            "active": self.is_active,
            "detected_at": self.detected_at,
        }


class NetworkDetector:
    """
    Automatically detects all available network interfaces.
    Works across WiFi, Ethernet, Fiber, DSL, Cellular, VPN, etc.
    """

    INTERFACE_TYPE_MAP = {
        "wlan": "WiFi",
        "wifi": "WiFi",
        "wl": "WiFi",
        "ath": "WiFi",
        "ra": "WiFi",
        "eth": "Ethernet",
        "en": "Ethernet",
        "em": "Ethernet",
        "eno": "Ethernet",
        "enp": "Ethernet",
        "ens": "Ethernet",
        "br": "Bridge",
        "bond": "Bonded",
        "tun": "VPN/Tunnel",
        "tap": "VPN/Tunnel",
        "wg": "WireGuard VPN",
        "ppp": "PPPoE/DSL",
        "docker": "Docker",
        "veth": "Virtual",
        "lo": "Loopback",
        "usb": "USB Tethering",
        "rmnet": "Cellular",
        "wwan": "Cellular/4G/5G",
        "lte": "LTE",
    }

    def __init__(self):
        self.interfaces = []
        self.system = platform.system().lower()

    def detect_all(self):
        """Detect all network interfaces on the system."""
        self.interfaces = []
        try:
            if self.system == "linux":
                self._detect_linux()
            elif self.system == "windows":
                self._detect_windows()
            elif self.system == "darwin":
                self._detect_macos()
            else:
                self._detect_generic()
        except Exception as e:
            logger.error(f"Network detection error: {e}")
            self._detect_generic()
        return self.interfaces

    def _detect_linux(self):
        """Detect interfaces on Linux."""
        try:
            result = subprocess.run(
                ["ip", "-j", "addr", "show"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                interfaces = json.loads(result.stdout)
                for iface in interfaces:
                    name = iface.get("ifname", "")
                    if name == "lo":
                        continue
                    mac = iface.get("address", "")
                    for addr_info in iface.get("addr_info", []):
                        if addr_info.get("family") == "inet":
                            ip = addr_info.get("local", "")
                            prefix = addr_info.get("prefixlen", 24)
                            netmask = self._prefix_to_netmask(prefix)
                            itype = self._classify_interface(name)
                            gateway = self._get_default_gateway()
                            ni = NetworkInterface(name, ip, netmask, mac, itype, gateway)
                            self.interfaces.append(ni)
                return
        except (FileNotFoundError, json.JSONDecodeError):
            pass

        self._detect_generic()

    def _detect_windows(self):
        """Detect interfaces on Windows."""
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 "Get-NetIPAddress -AddressFamily IPv4 | "
                 "Select-Object InterfaceAlias,IPAddress,PrefixLength | "
                 "ConvertTo-Json"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                if isinstance(data, dict):
                    data = [data]
                for item in data:
                    name = item.get("InterfaceAlias", "")
                    ip = item.get("IPAddress", "")
                    prefix = item.get("PrefixLength", 24)
                    if ip.startswith("127."):
                        continue
                    netmask = self._prefix_to_netmask(prefix)
                    itype = self._classify_interface(name)
                    ni = NetworkInterface(name, ip, netmask, "", itype)
                    self.interfaces.append(ni)
                return
        except (FileNotFoundError, json.JSONDecodeError):
            pass

        self._detect_generic()

    def _detect_macos(self):
        """Detect interfaces on macOS."""
        try:
            result = subprocess.run(
                ["ifconfig"], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                current_iface = None
                for line in result.stdout.split("\n"):
                    if line and not line.startswith("\t") and not line.startswith(" "):
                        current_iface = line.split(":")[0]
                    elif current_iface and "inet " in line:
                        parts = line.strip().split()
                        ip_idx = parts.index("inet") + 1
                        ip = parts[ip_idx]
                        if ip.startswith("127."):
                            continue
                        netmask = ""
                        if "netmask" in parts:
                            nm_idx = parts.index("netmask") + 1
                            netmask = parts[nm_idx]
                        itype = self._classify_interface(current_iface)
                        ni = NetworkInterface(current_iface, ip, netmask, "", itype)
                        self.interfaces.append(ni)
                return
        except FileNotFoundError:
            pass

        self._detect_generic()

    def _detect_generic(self):
        """Fallback: detect using socket."""
        try:
            hostname = socket.gethostname()
            ip = socket.gethostbyname(hostname)
            if ip and not ip.startswith("127."):
                ni = NetworkInterface("default", ip, "255.255.255.0", "", "Unknown")
                self.interfaces.append(ni)
        except socket.error:
            pass

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            if ip and not any(i.ip == ip for i in self.interfaces):
                ni = NetworkInterface("primary", ip, "255.255.255.0", "", "Auto-detected")
                self.interfaces.append(ni)
        except socket.error:
            pass

    def _classify_interface(self, name):
        """Classify interface type from its name."""
        name_lower = name.lower()
        for prefix, itype in self.INTERFACE_TYPE_MAP.items():
            if name_lower.startswith(prefix):
                return itype
        if "wireless" in name_lower or "wi-fi" in name_lower or "wifi" in name_lower:
            return "WiFi"
        if "ethernet" in name_lower or "local area" in name_lower:
            return "Ethernet"
        if "vpn" in name_lower or "tunnel" in name_lower:
            return "VPN/Tunnel"
        return "Unknown"

    def _prefix_to_netmask(self, prefix):
        """Convert CIDR prefix to netmask string."""
        try:
            prefix = int(prefix)
            bits = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF
            return socket.inet_ntoa(struct.pack(">I", bits))
        except (ValueError, struct.error):
            return "255.255.255.0"

    def _get_default_gateway(self):
        """Get default gateway on Linux."""
        try:
            result = subprocess.run(
                ["ip", "route", "show", "default"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split()
                if "via" in parts:
                    return parts[parts.index("via") + 1]
        except FileNotFoundError:
            pass
        return None

    def get_best_interface(self):
        """Return the best available network interface."""
        if not self.interfaces:
            self.detect_all()
        for pref in ["WiFi", "Ethernet", "Bridge"]:
            for iface in self.interfaces:
                if iface.interface_type == pref and iface.is_active:
                    return iface
        return self.interfaces[0] if self.interfaces else None

    def get_all_ips(self):
        """Return all detected IP addresses."""
        if not self.interfaces:
            self.detect_all()
        return [i.ip for i in self.interfaces if i.is_active]

    def to_dict_list(self):
        """Return all interfaces as dicts."""
        if not self.interfaces:
            self.detect_all()
        return [i.to_dict() for i in self.interfaces]
