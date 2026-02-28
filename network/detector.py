"""
Network Auto-Detection Module - Universal Router & Cable Support
================================================================
Detects ALL network interfaces including every type of fiber optic connection.

Supported Fiber Optic:
  FTTH, FTTB, FTTP, FTTC, FTTN, FTTX routers
  GPON, EPON, XG-PON, XGS-PON, 10G-EPON, NG-PON2 routers
  SFP, SFP+, SFP28, QSFP, QSFP+, QSFP28, XFP, CFP modules
  ONT, ONU, OLT terminals
  Optical Network Routers, Fiber Edge Routers, Carrier Fiber Routers, Fiber Gateways

Supported Copper/Wireless:
  WiFi, Ethernet, DSL/ADSL/VDSL, 4G/LTE/5G, VPN, Bridge, Bond, USB, Satellite

Works on ALL platforms: Linux, Windows, macOS, BSD, embedded systems
"""
import socket
import struct
import subprocess
import platform
import logging
import json
import re
from datetime import datetime

logger = logging.getLogger("BRO.network")


class NetworkInterface:
    """Represents a detected network interface with full metadata."""

    def __init__(self, name, ip, netmask, mac, interface_type, gateway=None,
                 speed=None, mtu=None, duplex=None, fiber_type=None):
        self.name = name
        self.ip = ip
        self.netmask = netmask
        self.mac = mac
        self.interface_type = interface_type
        self.gateway = gateway
        self.speed = speed  # Link speed in Mbps
        self.mtu = mtu  # MTU size
        self.duplex = duplex  # full/half
        self.fiber_type = fiber_type  # Specific fiber type if detected
        self.is_active = True
        self.is_fiber = self._check_fiber()
        self.detected_at = datetime.utcnow().isoformat()

    def _check_fiber(self):
        """Check if this interface is a fiber optic connection."""
        fiber_keywords = [
            "fiber", "fibre", "optical", "optic", "pon", "gpon", "epon",
            "xgpon", "xgspon", "ftth", "fttb", "fttp", "fttc", "fttn",
            "sfp", "ont", "onu", "olt", "xfp", "cfp", "qsfp",
        ]
        name_lower = (self.name or "").lower()
        type_lower = (self.interface_type or "").lower()
        combined = name_lower + " " + type_lower
        return any(kw in combined for kw in fiber_keywords)

    def to_dict(self):
        result = {
            "name": self.name,
            "ip": self.ip,
            "netmask": self.netmask,
            "mac": self.mac,
            "type": self.interface_type,
            "gateway": self.gateway,
            "active": self.is_active,
            "is_fiber": self.is_fiber,
            "detected_at": self.detected_at,
        }
        if self.speed:
            result["speed"] = self.speed
        if self.mtu:
            result["mtu"] = self.mtu
        if self.duplex:
            result["duplex"] = self.duplex
        if self.fiber_type:
            result["fiber_type"] = self.fiber_type
        return result


class NetworkDetector:
    """
    Universal network interface detector.
    Works with ANY router, cable, or connection type including all fiber optics.
    """

    # Comprehensive interface type mapping - covers every known prefix
    INTERFACE_TYPE_MAP = {
        # WiFi interfaces
        "wlan": "WiFi",
        "wifi": "WiFi",
        "wl": "WiFi",
        "ath": "WiFi",
        "ra": "WiFi",
        "iwl": "WiFi",          # Intel WiFi
        "mlan": "WiFi",         # Marvell WiFi
        "wlp": "WiFi",          # systemd predictable naming
        "wlx": "WiFi",          # systemd USB WiFi
        # Ethernet interfaces
        "eth": "Ethernet",
        "en": "Ethernet",
        "em": "Ethernet",
        "eno": "Ethernet",
        "enp": "Ethernet",
        "ens": "Ethernet",
        "enx": "Ethernet",      # systemd USB Ethernet
        "igb": "Ethernet",      # Intel Gigabit
        "ixgbe": "Ethernet",    # Intel 10G
        "mlx": "Ethernet",      # Mellanox
        "i40e": "Ethernet",     # Intel 40G
        "ice": "Ethernet",      # Intel 100G
        # Fiber Optic interfaces - COMPREHENSIVE
        "pon": "Fiber/PON",
        "gpon": "Fiber/GPON",
        "epon": "Fiber/EPON",
        "xgpon": "Fiber/XG-PON",
        "xgspon": "Fiber/XGS-PON",
        "10gpon": "Fiber/10G-PON",
        "ngpon": "Fiber/NG-PON2",
        "ont": "Fiber/ONT",
        "onu": "Fiber/ONU",
        "olt": "Fiber/OLT",
        "sfp": "Fiber/SFP",
        "xfp": "Fiber/XFP",
        "cfp": "Fiber/CFP",
        "qsfp": "Fiber/QSFP",
        "fiber": "Fiber",
        "fibre": "Fiber",
        "ftth": "Fiber/FTTH",
        "fttb": "Fiber/FTTB",
        "fttp": "Fiber/FTTP",
        "fttx": "Fiber/FTTx",
        "optical": "Fiber/Optical",
        "optic": "Fiber/Optical",
        "fo": "Fiber/Optical",      # Fiber Optic shorthand
        "optif": "Fiber/Optical",   # Some embedded fiber interfaces
        # Bridge / Bond
        "br": "Bridge",
        "bridge": "Bridge",
        "bond": "Bonded",
        "team": "Team",
        # VPN / Tunnel
        "tun": "VPN/Tunnel",
        "tap": "VPN/Tunnel",
        "wg": "WireGuard VPN",
        "ovpn": "OpenVPN",
        "ipsec": "IPsec VPN",
        "gre": "GRE Tunnel",
        "vti": "VTI Tunnel",
        # DSL interfaces
        "ppp": "PPPoE/DSL",
        "dsl": "DSL",
        "adsl": "ADSL",
        "vdsl": "VDSL",
        "nas": "DSL/NAS",
        # Cellular
        "rmnet": "Cellular",
        "wwan": "Cellular/4G/5G",
        "lte": "LTE",
        "5g": "5G NR",
        "qmi": "Cellular/QMI",
        "mbim": "Cellular/MBIM",
        # Virtual / Container
        "docker": "Docker",
        "veth": "Virtual",
        "virbr": "Virtual Bridge",
        "vbox": "VirtualBox",
        "vmnet": "VMware",
        "vnet": "Virtual",
        # USB
        "usb": "USB Tethering",
        "rndis": "USB RNDIS",
        "ncm": "USB NCM",
        # Loopback
        "lo": "Loopback",
        # InfiniBand (data center fiber)
        "ib": "InfiniBand",
        "mlx4": "InfiniBand",
        "mlx5": "InfiniBand",
    }

    # Windows adapter name keywords for fiber detection
    WINDOWS_FIBER_KEYWORDS = [
        "fiber", "fibre", "optical", "gpon", "epon", "pon", "sfp",
        "ont", "onu", "olt", "ftth", "fttb", "fttp", "fttx",
        "xg-pon", "xgs-pon", "10g", "25g", "40g", "100g",
        "single mode", "multi mode", "singlemode", "multimode",
        "wavelength", "transceiver", "optic",
    ]

    # Windows adapter name keywords for other types
    WINDOWS_TYPE_KEYWORDS = {
        "wireless": "WiFi",
        "wi-fi": "WiFi",
        "wifi": "WiFi",
        "wlan": "WiFi",
        "802.11": "WiFi",
        "ethernet": "Ethernet",
        "local area": "Ethernet",
        "gigabit": "Ethernet",
        "realtek": "Ethernet",
        "intel": "Ethernet",
        "broadcom": "Ethernet",
        "vpn": "VPN/Tunnel",
        "tunnel": "VPN/Tunnel",
        "tap-windows": "VPN/Tunnel",
        "wireguard": "WireGuard VPN",
        "pppoe": "PPPoE/DSL",
        "dsl": "DSL",
        "adsl": "ADSL",
        "mobile": "Cellular",
        "cellular": "Cellular",
        "lte": "LTE",
        "bluetooth": "Bluetooth",
        "loopback": "Loopback",
        "hyper-v": "Virtual",
        "vmware": "VMware",
        "virtualbox": "VirtualBox",
        "docker": "Docker",
    }

    def __init__(self):
        self.interfaces = []
        self.system = platform.system().lower()
        self.fiber_detected = False

    def detect_all(self):
        """Detect all network interfaces on the system."""
        self.interfaces = []
        self.fiber_detected = False
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

        # Check fiber status
        self.fiber_detected = any(i.is_fiber for i in self.interfaces)
        if self.fiber_detected:
            logger.info("Fiber optic connection detected - enabling optimizations")

        return self.interfaces

    def _detect_linux(self):
        """Detect interfaces on Linux with full fiber support."""
        try:
            result = subprocess.run(
                ["ip", "-j", "addr", "show"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                interfaces = json.loads(result.stdout)
                gateway = self._get_default_gateway()
                for iface in interfaces:
                    name = iface.get("ifname", "")
                    if name == "lo":
                        continue
                    mac = iface.get("address", "")
                    mtu = iface.get("mtu")
                    for addr_info in iface.get("addr_info", []):
                        if addr_info.get("family") == "inet":
                            ip = addr_info.get("local", "")
                            prefix = addr_info.get("prefixlen", 24)
                            netmask = self._prefix_to_netmask(prefix)
                            itype = self._classify_interface(name)
                            speed = self._get_link_speed_linux(name)
                            fiber_type = self._detect_fiber_type_linux(name, speed, mtu)
                            ni = NetworkInterface(
                                name, ip, netmask, mac, itype, gateway,
                                speed=speed, mtu=mtu, fiber_type=fiber_type,
                            )
                            self.interfaces.append(ni)
                return
        except (FileNotFoundError, json.JSONDecodeError):
            pass

        self._detect_generic()

    def _detect_windows(self):
        """Detect interfaces on Windows with full fiber support."""
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
                gateway = self._get_default_gateway_windows()
                for item in data:
                    name = item.get("InterfaceAlias", "")
                    ip = item.get("IPAddress", "")
                    prefix = item.get("PrefixLength", 24)
                    if ip.startswith("127."):
                        continue
                    netmask = self._prefix_to_netmask(prefix)
                    itype = self._classify_interface_windows(name)
                    speed = self._get_link_speed_windows(name)
                    fiber_type = self._detect_fiber_type_windows(name, speed)
                    ni = NetworkInterface(
                        name, ip, netmask, "", itype, gateway,
                        speed=speed, fiber_type=fiber_type,
                    )
                    self.interfaces.append(ni)
                return
        except (FileNotFoundError, json.JSONDecodeError):
            pass

        self._detect_generic()

    def _detect_macos(self):
        """Detect interfaces on macOS with fiber support."""
        try:
            result = subprocess.run(
                ["ifconfig"], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                gateway = self._get_default_gateway_macos()
                current_iface = None
                current_mac = ""
                for line in result.stdout.split("\n"):
                    if line and not line.startswith("\t") and not line.startswith(" "):
                        current_iface = line.split(":")[0]
                        current_mac = ""
                    elif current_iface and "ether " in line:
                        parts = line.strip().split()
                        idx = parts.index("ether") + 1
                        current_mac = parts[idx] if idx < len(parts) else ""
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
                            if netmask.startswith("0x"):
                                netmask = self._hex_to_netmask(netmask)
                        itype = self._classify_interface(current_iface)
                        ni = NetworkInterface(
                            current_iface, ip, netmask, current_mac, itype, gateway
                        )
                        self.interfaces.append(ni)
                return
        except FileNotFoundError:
            pass

        self._detect_generic()

    def _detect_generic(self):
        """Fallback: detect using socket - works on ANY system."""
        try:
            hostname = socket.gethostname()
            ip = socket.gethostbyname(hostname)
            if ip and not ip.startswith("127."):
                ni = NetworkInterface("default", ip, "255.255.255.0", "", "Auto-detected")
                self.interfaces.append(ni)
        except socket.error:
            pass

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(2)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            if ip and not any(i.ip == ip for i in self.interfaces):
                ni = NetworkInterface("primary", ip, "255.255.255.0", "", "Auto-detected")
                self.interfaces.append(ni)
        except (socket.error, OSError):
            pass

        # Try secondary DNS for redundancy
        if not self.interfaces:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.settimeout(2)
                s.connect(("1.1.1.1", 80))
                ip = s.getsockname()[0]
                s.close()
                ni = NetworkInterface("primary", ip, "255.255.255.0", "", "Auto-detected")
                self.interfaces.append(ni)
            except (socket.error, OSError):
                pass

    def _classify_interface(self, name):
        """Classify interface type from its name - supports all types."""
        name_lower = name.lower()
        # Check exact prefix matches (longer prefixes first for accuracy)
        sorted_prefixes = sorted(self.INTERFACE_TYPE_MAP.keys(), key=len, reverse=True)
        for prefix in sorted_prefixes:
            if name_lower.startswith(prefix):
                return self.INTERFACE_TYPE_MAP[prefix]
        # Check keyword matches
        if "wireless" in name_lower or "wi-fi" in name_lower or "wifi" in name_lower:
            return "WiFi"
        if "ethernet" in name_lower or "local area" in name_lower:
            return "Ethernet"
        if "vpn" in name_lower or "tunnel" in name_lower:
            return "VPN/Tunnel"
        if any(kw in name_lower for kw in ["fiber", "fibre", "optical", "optic", "sfp", "pon"]):
            return "Fiber"
        if any(kw in name_lower for kw in ["ont", "onu", "olt"]):
            return "Fiber/ONT"
        return "Unknown"

    def _classify_interface_windows(self, name):
        """Classify Windows interface - checks adapter name keywords."""
        name_lower = name.lower()
        # Check fiber keywords first (highest priority)
        for kw in self.WINDOWS_FIBER_KEYWORDS:
            if kw in name_lower:
                return "Fiber"
        # Check other Windows keywords
        for kw, itype in self.WINDOWS_TYPE_KEYWORDS.items():
            if kw in name_lower:
                return itype
        # Try standard prefix matching
        return self._classify_interface(name)

    def _detect_fiber_type_linux(self, name, speed, mtu):
        """Detect specific fiber optic type on Linux."""
        name_lower = name.lower()
        # Check interface name
        for prefix in ["gpon", "epon", "xgpon", "xgspon", "10gpon", "ngpon"]:
            if prefix in name_lower:
                return prefix.upper()
        for prefix in ["sfp", "xfp", "cfp", "qsfp"]:
            if prefix in name_lower:
                return prefix.upper()
        for prefix in ["ont", "onu", "olt"]:
            if prefix in name_lower:
                return prefix.upper()
        if "ftth" in name_lower:
            return "FTTH"

        # Check ethtool for transceiver info
        try:
            result = subprocess.run(
                ["ethtool", "-m", name],
                capture_output=True, text=True, timeout=3
            )
            output = result.stdout.lower()
            if "transceiver" in output or "sfp" in output or "optical" in output:
                if "10gbase" in output or "10g" in output:
                    return "SFP+ (10G)"
                if "25gbase" in output or "25g" in output:
                    return "SFP28 (25G)"
                return "SFP"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Check by ethtool port type
        try:
            result = subprocess.run(
                ["ethtool", name],
                capture_output=True, text=True, timeout=3
            )
            output = result.stdout.lower()
            if "fibre" in output or "fiber" in output:
                if speed and speed >= 10000:
                    return "SFP+ (10G)"
                return "SFP"
            if "port: fibre" in output:
                return "Fiber"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Detect by MTU and speed combination
        if mtu and mtu >= 9000:
            if speed and speed >= 10000:
                return "Fiber (10G+ Jumbo)"
            elif speed and speed >= 1000:
                return "Fiber/Gigabit"

        return None

    def _detect_fiber_type_windows(self, name, speed):
        """Detect specific fiber optic type on Windows."""
        name_lower = name.lower()
        for kw in self.WINDOWS_FIBER_KEYWORDS:
            if kw in name_lower:
                if "gpon" in name_lower:
                    return "GPON"
                if "epon" in name_lower:
                    return "EPON"
                if "xg-pon" in name_lower or "xgpon" in name_lower:
                    return "XG-PON"
                if "xgs-pon" in name_lower or "xgspon" in name_lower:
                    return "XGS-PON"
                if "sfp+" in name_lower or "sfp28" in name_lower:
                    return "SFP+"
                if "sfp" in name_lower:
                    return "SFP"
                if "ont" in name_lower:
                    return "ONT"
                if "onu" in name_lower:
                    return "ONU"
                if "ftth" in name_lower:
                    return "FTTH"
                if speed and speed >= 10000:
                    return "Fiber (10G+)"
                return "Fiber"

        # Check by speed - fiber is typically 1G+ with specific adapter names
        if speed and speed >= 10000:
            return "Fiber (10G+)"

        return None

    def _get_link_speed_linux(self, name):
        """Get interface link speed on Linux (in Mbps)."""
        try:
            with open(f"/sys/class/net/{name}/speed", "r") as f:
                speed = int(f.read().strip())
                if speed > 0:
                    return speed
        except (FileNotFoundError, ValueError, PermissionError, OSError):
            pass
        return None

    def _get_link_speed_windows(self, name):
        """Get interface link speed on Windows (in Mbps)."""
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 f"(Get-NetAdapter -Name '{name}' -ErrorAction SilentlyContinue).LinkSpeed"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                speed_str = result.stdout.strip().lower()
                match = re.search(r"([\d.]+)\s*(gbps|mbps|kbps)", speed_str)
                if match:
                    val = float(match.group(1))
                    unit = match.group(2)
                    if unit == "gbps":
                        return int(val * 1000)
                    elif unit == "mbps":
                        return int(val)
                    elif unit == "kbps":
                        return int(val / 1000)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return None

    def _prefix_to_netmask(self, prefix):
        """Convert CIDR prefix to netmask string."""
        try:
            prefix = int(prefix)
            bits = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF
            return socket.inet_ntoa(struct.pack(">I", bits))
        except (ValueError, struct.error):
            return "255.255.255.0"

    def _hex_to_netmask(self, hex_str):
        """Convert hex netmask (macOS format) to dotted notation."""
        try:
            val = int(hex_str, 16)
            return socket.inet_ntoa(struct.pack(">I", val))
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

    def _get_default_gateway_windows(self):
        """Get default gateway on Windows."""
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 "(Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | "
                 "Select-Object -First 1).NextHop"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return None

    def _get_default_gateway_macos(self):
        """Get default gateway on macOS."""
        try:
            result = subprocess.run(
                ["route", "-n", "get", "default"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.split("\n"):
                    if "gateway:" in line:
                        return line.split("gateway:")[1].strip()
        except FileNotFoundError:
            pass
        return None

    def get_best_interface(self):
        """Return the best available network interface.
        Priority: Fiber > WiFi > Ethernet > Bridge > any active > first
        """
        if not self.interfaces:
            self.detect_all()
        # Fiber first (highest speed)
        for iface in self.interfaces:
            if iface.is_fiber and iface.is_active:
                return iface
        # Then WiFi/Ethernet/Bridge
        for pref in ["WiFi", "Ethernet", "Bridge"]:
            for iface in self.interfaces:
                if iface.interface_type == pref and iface.is_active:
                    return iface
        # Any active
        for iface in self.interfaces:
            if iface.is_active:
                return iface
        return self.interfaces[0] if self.interfaces else None

    def get_all_ips(self):
        """Return all detected IP addresses."""
        if not self.interfaces:
            self.detect_all()
        return [i.ip for i in self.interfaces if i.is_active]

    def get_fiber_interfaces(self):
        """Return only fiber optic interfaces."""
        if not self.interfaces:
            self.detect_all()
        return [i for i in self.interfaces if i.is_fiber]

    def get_optimal_mtu(self):
        """Get optimal MTU based on detected connection type.
        Fiber connections support jumbo frames (9000 MTU).
        """
        if self.fiber_detected:
            return 9000  # Jumbo frames for fiber
        return 1500  # Standard MTU

    def get_optimal_buffer_size(self):
        """Get optimal socket buffer size based on connection type."""
        if self.fiber_detected:
            return 1048576  # 1MB for fiber
        return 65535  # 64KB default

    def to_dict_list(self):
        """Return all interfaces as dicts."""
        if not self.interfaces:
            self.detect_all()
        return [i.to_dict() for i in self.interfaces]
