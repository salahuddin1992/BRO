"""
Helen WiFi - Network Detector Unit Tests
Tests for network/detector.py: Interface detection, classification, fiber detection
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from network.detector import NetworkDetector


class TestNetworkDetector(unittest.TestCase):
    """Tests for NetworkDetector classification and utility methods."""

    def setUp(self):
        self.detector = NetworkDetector()

    # --- Interface Classification ---
    def test_classify_wifi(self):
        self.assertEqual(self.detector._classify("wlan0"), "WiFi")
        self.assertEqual(self.detector._classify("wlp2s0"), "WiFi")

    def test_classify_ethernet(self):
        self.assertEqual(self.detector._classify("eth0"), "Ethernet")
        self.assertEqual(self.detector._classify("enp3s0"), "Ethernet")
        self.assertEqual(self.detector._classify("eno1"), "Ethernet")

    def test_classify_fiber(self):
        # _classify checks FIBER_KEYWORDS first, so all fiber interfaces return "Fiber"
        self.assertEqual(self.detector._classify("gpon0"), "Fiber")
        self.assertEqual(self.detector._classify("epon0"), "Fiber")
        self.assertEqual(self.detector._classify("sfp0"), "Fiber")
        self.assertEqual(self.detector._classify("ont0"), "Fiber")

    def test_classify_vpn(self):
        self.assertEqual(self.detector._classify("tun0"), "VPN")
        self.assertEqual(self.detector._classify("wg0"), "WireGuard")

    def test_classify_docker(self):
        self.assertEqual(self.detector._classify("docker0"), "Docker")
        self.assertEqual(self.detector._classify("veth12345"), "Virtual")

    def test_classify_unknown(self):
        result = self.detector._classify("xyz99")
        self.assertEqual(result, "Unknown")

    # --- Fiber Detection ---
    def test_is_fiber_true(self):
        self.assertTrue(self.detector._is_fiber("gpon0"))
        self.assertTrue(self.detector._is_fiber("epon0"))
        self.assertTrue(self.detector._is_fiber("sfp0"))
        self.assertTrue(self.detector._is_fiber("ont0"))
        self.assertTrue(self.detector._is_fiber("fiber0"))
        self.assertTrue(self.detector._is_fiber("ftth0"))

    def test_is_fiber_false(self):
        self.assertFalse(self.detector._is_fiber("eth0"))
        self.assertFalse(self.detector._is_fiber("wlan0"))
        self.assertFalse(self.detector._is_fiber("docker0"))
        self.assertFalse(self.detector._is_fiber("tun0"))

    # --- Prefix to Mask ---
    def test_prefix_to_mask_24(self):
        mask = self.detector._prefix_to_mask(24)
        self.assertEqual(mask, "255.255.255.0")

    def test_prefix_to_mask_16(self):
        mask = self.detector._prefix_to_mask(16)
        self.assertEqual(mask, "255.255.0.0")

    def test_prefix_to_mask_32(self):
        mask = self.detector._prefix_to_mask(32)
        self.assertEqual(mask, "255.255.255.255")

    def test_prefix_to_mask_8(self):
        mask = self.detector._prefix_to_mask(8)
        self.assertEqual(mask, "255.0.0.0")

    # --- Detect All ---
    def test_detect_all_returns_list(self):
        result = self.detector.detect_all()
        self.assertIsInstance(result, list)

    def test_detect_all_interface_structure(self):
        result = self.detector.detect_all()
        if len(result) > 0:
            iface = result[0]
            self.assertIn("name", iface)
            self.assertIn("ip", iface)
            self.assertIn("type", iface)
            self.assertIn("is_fiber", iface)

    # --- Get All IPs ---
    def test_get_all_ips(self):
        self.detector.interfaces = [
            {"name": "eth0", "ip": "192.168.1.1", "type": "Ethernet", "is_fiber": False},
            {"name": "wlan0", "ip": "192.168.1.2", "type": "WiFi", "is_fiber": False},
        ]
        ips = self.detector.get_all_ips()
        self.assertIsInstance(ips, list)
        self.assertEqual(len(ips), 2)
        self.assertIn("192.168.1.1", ips)
        self.assertIn("192.168.1.2", ips)

    # --- Has Fiber ---
    def test_has_fiber_no_interfaces(self):
        self.detector.interfaces = []
        self.assertFalse(self.detector.has_fiber())

    def test_has_fiber_with_fiber(self):
        self.detector.interfaces = [
            {"name": "eth0", "ip": "192.168.1.1", "type": "Ethernet", "is_fiber": False},
            {"name": "gpon0", "ip": "10.0.0.1", "type": "Fiber", "is_fiber": True},
        ]
        self.assertTrue(self.detector.has_fiber())

    def test_has_fiber_without_fiber(self):
        self.detector.interfaces = [
            {"name": "eth0", "ip": "192.168.1.1", "type": "Ethernet", "is_fiber": False},
            {"name": "wlan0", "ip": "192.168.1.2", "type": "WiFi", "is_fiber": False},
        ]
        self.assertFalse(self.detector.has_fiber())

    # --- TYPES mapping ---
    def test_types_mapping_coverage(self):
        self.assertIn("wlan", NetworkDetector.TYPES)
        self.assertIn("eth", NetworkDetector.TYPES)
        self.assertIn("gpon", NetworkDetector.TYPES)
        self.assertIn("sfp", NetworkDetector.TYPES)
        self.assertIn("tun", NetworkDetector.TYPES)
        self.assertIn("docker", NetworkDetector.TYPES)

    def test_fiber_keywords(self):
        self.assertIn("fiber", NetworkDetector.FIBER_KEYWORDS)
        self.assertIn("gpon", NetworkDetector.FIBER_KEYWORDS)
        self.assertIn("sfp", NetworkDetector.FIBER_KEYWORDS)

    # --- Get Best Interface ---
    def test_get_best_interface_empty(self):
        self.detector.interfaces = []
        # detect_all will run on empty, result depends on system
        # Just verify it doesn't crash
        result = self.detector.get_best_interface()
        # Result is either None or a dict
        self.assertTrue(result is None or isinstance(result, dict))

    def test_get_best_interface_prefers_fiber(self):
        self.detector.interfaces = [
            {"name": "eth0", "ip": "192.168.1.1", "type": "Ethernet", "is_fiber": False},
            {"name": "gpon0", "ip": "10.0.0.1", "type": "Fiber", "is_fiber": True},
        ]
        best = self.detector.get_best_interface()
        self.assertEqual(best["name"], "gpon0")


if __name__ == "__main__":
    unittest.main()
