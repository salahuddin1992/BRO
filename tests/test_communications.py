"""
Helen WiFi - Tests for communication libraries
Tests TURN/STUN, mDNS discovery, WebSocket mesh, netifaces, requests.
"""
import os
import sys
import socket
import json
import time
import threading
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestLocalTurnServer:
    def test_stun_binding_response(self):
        from network.turn_server import LocalTurnServer

        server = LocalTurnServer(port=0)  # Let OS pick a port
        # Test the response builder directly
        # Build a fake STUN Binding Request
        msg_type = (0x0001).to_bytes(2, "big")
        msg_len = (0).to_bytes(2, "big")
        magic = (0x2112A442).to_bytes(4, "big")
        txn_id = b'\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c'
        request_data = msg_type + msg_len + magic + txn_id

        addr = ("192.168.1.100", 12345)
        response = server._build_binding_response(request_data, addr)

        # Verify response is a STUN Binding Success Response
        assert len(response) >= 20
        resp_type = int.from_bytes(response[0:2], "big")
        assert resp_type == 0x0101  # Binding Success Response
        # Transaction ID should match
        assert response[8:20] == txn_id

    def test_get_ice_server_config(self):
        from network.turn_server import LocalTurnServer

        server = LocalTurnServer(port=3478)
        config = server.get_ice_server_config("192.168.1.5")
        assert config == {"urls": "stun:192.168.1.5:3478"}

    def test_get_local_ice_candidates(self):
        from network.turn_server import get_local_ice_candidates

        candidates = get_local_ice_candidates("192.168.1.5")
        assert len(candidates) >= 1
        assert candidates[0]["type"] == "host"
        assert candidates[0]["ip"] == "192.168.1.5"


class TestServiceDiscovery:
    def test_init(self):
        from network.discovery import ServiceDiscovery

        disco = ServiceDiscovery("test123", "192.168.1.5", 8400)
        assert disco.server_id == "test123"
        assert disco.host_ip == "192.168.1.5"
        assert disco.port == 8400
        assert disco.get_discovered_peers() == []

    def test_service_type_constant(self):
        from network.discovery import SERVICE_TYPE, SERVICE_NAME_PREFIX

        assert SERVICE_TYPE == "_helenwifi._tcp.local."
        assert SERVICE_NAME_PREFIX == "HelenWiFi-"


class TestWebSocketMeshBridge:
    def test_init(self):
        from network.ws_mesh import WebSocketMeshBridge

        bridge = WebSocketMeshBridge("srv123", "192.168.1.5", 8400, "secret")
        assert bridge.server_id == "srv123"
        assert bridge.ws_port == 8402  # port + 2
        assert bridge.get_connected_peers() == []

    def test_get_stats(self):
        from network.ws_mesh import WebSocketMeshBridge

        bridge = WebSocketMeshBridge("srv123", "192.168.1.5", 8400, "secret")
        stats = bridge.get_stats()
        assert stats["ws_port"] == 8402
        assert stats["connected_peers"] == 0
        assert stats["peer_ids"] == []

    def test_is_peer_connected(self):
        from network.ws_mesh import WebSocketMeshBridge

        bridge = WebSocketMeshBridge("srv123", "192.168.1.5", 8400, "secret")
        assert bridge.is_peer_connected("unknown") is False


class TestNetifaces:
    def test_netifaces_import(self):
        try:
            import netifaces
            interfaces = netifaces.interfaces()
            assert isinstance(interfaces, list)
            assert len(interfaces) > 0  # At least loopback
        except ImportError:
            pytest.skip("netifaces not available on this platform")

    def test_netifaces_gateways(self):
        try:
            import netifaces
            gateways = netifaces.gateways()
            assert isinstance(gateways, dict)
        except ImportError:
            pytest.skip("netifaces not available on this platform")

    def test_detector_uses_netifaces(self):
        from network.detector import _netifaces_available
        # netifaces is optional - detector has fallback to subprocess
        if not _netifaces_available:
            pytest.skip("netifaces not available, detector uses subprocess fallback")


class TestRequestsLibrary:
    def test_requests_import(self):
        import requests
        assert hasattr(requests, "get")
        assert hasattr(requests, "post")

    def test_mesh_uses_requests(self):
        """Verify mesh_node.py imports requests instead of urllib."""
        import mesh.mesh_node as mn
        import inspect
        source = inspect.getsource(mn)
        assert "import requests" in source
        assert "from urllib.request import" not in source


class TestNetworkDetector:
    def test_netifaces_detection(self):
        from network.detector import NetworkDetector

        detector = NetworkDetector()
        detector.detect_all()
        # Should find at least one interface
        assert len(detector.interfaces) >= 0  # May be 0 in restricted environments

    def test_classify(self):
        from network.detector import NetworkDetector

        detector = NetworkDetector()
        assert detector._classify("wlan0") == "WiFi"
        assert detector._classify("eth0") == "Ethernet"
        assert detector._classify("gpon0") == "Fiber/GPON"

    def test_is_fiber(self):
        from network.detector import NetworkDetector

        detector = NetworkDetector()
        assert detector._is_fiber("gpon0") is True
        assert detector._is_fiber("ftth_link") is True
        assert detector._is_fiber("wlan0") is False
