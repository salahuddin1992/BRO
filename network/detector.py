"""
Network Detector - Auto-detect interfaces including Fiber Optic
Uses psutil for cross-platform network interface detection.
"""
import socket
import struct
import subprocess
import platform
import json
import logging

import psutil

logger = logging.getLogger("BRO.network")


class NetworkDetector:
    # Interface name -> type mapping
    TYPES = {
        "wlan": "WiFi", "wifi": "WiFi", "wl": "WiFi", "ath": "WiFi", "wlp": "WiFi",
        "eth": "Ethernet", "en": "Ethernet", "eno": "Ethernet", "enp": "Ethernet", "ens": "Ethernet",
        "br": "Bridge", "bond": "Bonded",
        "ppp": "PPPoE/DSL", "dsl": "DSL", "vdsl": "VDSL",
        "tun": "VPN", "tap": "VPN", "wg": "WireGuard",
        "rmnet": "Cellular", "wwan": "Cellular",
        "docker": "Docker", "veth": "Virtual",
        # Fiber Optic
        "pon": "Fiber/PON", "gpon": "Fiber/GPON", "epon": "Fiber/EPON",
        "xgpon": "Fiber/XG-PON", "xgspon": "Fiber/XGS-PON",
        "sfp": "Fiber/SFP", "ont": "Fiber/ONT", "onu": "Fiber/ONU",
        "fiber": "Fiber", "fibre": "Fiber", "optical": "Fiber",
        "ftth": "Fiber/FTTH",
    }

    FIBER_KEYWORDS = ["fiber", "fibre", "optical", "pon", "gpon", "epon", "sfp", "ont", "onu", "ftth"]

    def __init__(self):
        self.interfaces = []

    def detect_all(self):
        self.interfaces = []
        # Try psutil first (cross-platform, no subprocess needed)
        self._detect_psutil()
        # Fallback to OS-specific subprocess detection
        if not self.interfaces:
            system = platform.system().lower()
            if system == "linux":
                self._detect_linux()
            elif system == "windows":
                self._detect_windows()
            elif system == "darwin":
                self._detect_macos()
        if not self.interfaces:
            self._detect_fallback()
        return self.interfaces

    def _detect_psutil(self):
        """Detect network interfaces using psutil (cross-platform, always available)."""
        try:
            addrs = psutil.net_if_addrs()
            stats = psutil.net_if_stats()
            gateway = self._gateway_linux() if platform.system().lower() == "linux" else None

            for iface_name, addr_list in addrs.items():
                if iface_name == "lo" or iface_name.startswith("lo"):
                    continue
                # Check if interface is up
                iface_stats = stats.get(iface_name)
                if iface_stats and not iface_stats.isup:
                    continue
                ip = None
                netmask = "255.255.255.0"
                mac = ""
                for addr in addr_list:
                    if addr.family == socket.AF_INET:
                        ip = addr.address
                        netmask = addr.netmask or "255.255.255.0"
                    elif addr.family == psutil.AF_LINK:
                        mac = addr.address or ""
                if not ip or ip.startswith("127."):
                    continue
                self.interfaces.append({
                    "name": iface_name,
                    "ip": ip,
                    "netmask": netmask,
                    "mac": mac,
                    "type": self._classify(iface_name),
                    "gateway": gateway,
                    "is_fiber": self._is_fiber(iface_name),
                    "active": True,
                })
        except Exception as e:
            logger.debug(f"psutil detection failed: {e}")

    def _detect_linux(self):
        try:
            r = subprocess.run(["ip", "-j", "addr", "show"], capture_output=True, text=True, timeout=5)
            if r.returncode != 0:
                return
            gateway = self._gateway_linux()
            for iface in json.loads(r.stdout):
                name = iface.get("ifname", "")
                if name == "lo":
                    continue
                for addr in iface.get("addr_info", []):
                    if addr.get("family") == "inet":
                        self.interfaces.append({
                            "name": name,
                            "ip": addr.get("local", ""),
                            "netmask": self._prefix_to_mask(addr.get("prefixlen", 24)),
                            "mac": iface.get("address", ""),
                            "type": self._classify(name),
                            "gateway": gateway,
                            "is_fiber": self._is_fiber(name),
                            "active": True,
                        })
        except Exception:
            pass

    def _detect_windows(self):
        try:
            r = subprocess.run(
                ["powershell", "-Command",
                 "Get-NetIPAddress -AddressFamily IPv4 | Select InterfaceAlias,IPAddress,PrefixLength | ConvertTo-Json"],
                capture_output=True, text=True, timeout=10
            )
            if r.returncode != 0:
                return
            data = json.loads(r.stdout)
            if isinstance(data, dict):
                data = [data]
            for item in data:
                ip = item.get("IPAddress", "")
                if ip.startswith("127."):
                    continue
                name = item.get("InterfaceAlias", "")
                self.interfaces.append({
                    "name": name,
                    "ip": ip,
                    "netmask": self._prefix_to_mask(item.get("PrefixLength", 24)),
                    "mac": "",
                    "type": self._classify(name),
                    "gateway": None,
                    "is_fiber": self._is_fiber(name),
                    "active": True,
                })
        except Exception:
            pass

    def _detect_macos(self):
        try:
            r = subprocess.run(["ifconfig"], capture_output=True, text=True, timeout=5)
            if r.returncode != 0:
                return
            current = None
            for line in r.stdout.split("\n"):
                if line and not line[0].isspace():
                    current = line.split(":")[0]
                elif current and "inet " in line:
                    parts = line.strip().split()
                    ip = parts[parts.index("inet") + 1]
                    if not ip.startswith("127."):
                        self.interfaces.append({
                            "name": current, "ip": ip, "netmask": "", "mac": "",
                            "type": self._classify(current), "gateway": None,
                            "is_fiber": self._is_fiber(current), "active": True,
                        })
        except Exception:
            pass

    def _detect_fallback(self):
        try:
            # Local-only: use UDP broadcast address to find local IP without external connection
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(2)
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
            s.close()
            self.interfaces.append({
                "name": "auto", "ip": ip, "netmask": "255.255.255.0", "mac": "",
                "type": "Auto", "gateway": None, "is_fiber": False, "active": True,
            })
        except Exception:
            # Final fallback: use hostname
            try:
                ip = socket.gethostbyname(socket.gethostname())
                if ip and not ip.startswith("127."):
                    self.interfaces.append({
                        "name": "auto", "ip": ip, "netmask": "255.255.255.0", "mac": "",
                        "type": "Auto", "gateway": None, "is_fiber": False, "active": True,
                    })
            except Exception:
                pass

    def _classify(self, name):
        n = name.lower()
        # Check specific prefix types first (longest prefix wins)
        for prefix, itype in sorted(self.TYPES.items(), key=lambda x: -len(x[0])):
            if n.startswith(prefix):
                return itype
        # Fallback: check fiber keywords anywhere in name (Windows adapter names)
        if any(kw in n for kw in self.FIBER_KEYWORDS):
            return "Fiber"
        return "Unknown"

    def _is_fiber(self, name):
        return any(kw in name.lower() for kw in self.FIBER_KEYWORDS)

    def _gateway_linux(self):
        try:
            r = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True, timeout=3)
            parts = r.stdout.strip().split()
            return parts[parts.index("via") + 1] if "via" in parts else None
        except Exception:
            return None

    def _prefix_to_mask(self, prefix):
        try:
            bits = (0xFFFFFFFF << (32 - int(prefix))) & 0xFFFFFFFF
            return socket.inet_ntoa(struct.pack(">I", bits))
        except Exception:
            return "255.255.255.0"

    def get_best_interface(self):
        if not self.interfaces:
            self.detect_all()
        # Fiber > WiFi > Ethernet > any
        for pref in ["Fiber", "WiFi", "Ethernet"]:
            for i in self.interfaces:
                if pref in i["type"]:
                    return i
        return self.interfaces[0] if self.interfaces else None

    def get_all_ips(self):
        return [i["ip"] for i in self.interfaces]

    def get_broadcast_addresses(self):
        """Calculate the broadcast address for each interface's subnet."""
        broadcasts = []
        for iface in self.interfaces:
            ip = iface.get("ip", "")
            mask = iface.get("netmask", "255.255.255.0")
            if not ip or not mask:
                continue
            try:
                ip_int = struct.unpack(">I", socket.inet_aton(ip))[0]
                mask_int = struct.unpack(">I", socket.inet_aton(mask))[0]
                bcast_int = ip_int | (~mask_int & 0xFFFFFFFF)
                bcast = socket.inet_ntoa(struct.pack(">I", bcast_int))
                if bcast not in broadcasts:
                    broadcasts.append(bcast)
            except Exception:
                continue
        return broadcasts

    def has_fiber(self):
        return any(i["is_fiber"] for i in self.interfaces)

    def to_dict_list(self):
        if not self.interfaces:
            self.detect_all()
        return self.interfaces
