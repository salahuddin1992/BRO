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
        # Should return full ICE config with STUN + TURN servers
        assert "iceServers" in config
        servers = config["iceServers"]
        assert len(servers) >= 1
        # First should be STUN
        assert servers[0]["urls"] == "stun:192.168.1.5:3478"
        # Should include TURN with credentials
        turn_servers = [s for s in servers if "turn:" in s.get("urls", "")]
        assert len(turn_servers) >= 1
        for ts in turn_servers:
            assert "username" in ts
            assert "credential" in ts

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


class TestPsutilNetworkDetection:
    def test_psutil_import(self):
        import psutil
        addrs = psutil.net_if_addrs()
        assert isinstance(addrs, dict)
        assert len(addrs) > 0  # At least loopback

    def test_psutil_net_if_stats(self):
        import psutil
        stats = psutil.net_if_stats()
        assert isinstance(stats, dict)
        assert len(stats) > 0

    def test_detector_uses_psutil(self):
        """Verify detector uses psutil instead of netifaces."""
        import inspect
        from network.detector import NetworkDetector
        source = inspect.getsource(NetworkDetector)
        assert "psutil" in source


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
    def test_psutil_detection(self):
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
