"""Tests for the SFU (Selective Forwarding Unit) media relay."""
import threading
import time
import pytest
from unittest.mock import MagicMock, patch


class TestSFURoom:
    """Test SFURoom participant management."""

    def test_create_room(self):
        from network.sfu import SFURoom
        room = SFURoom("test-room")
        assert room.room_id == "test-room"
        assert room.is_empty()

    def test_add_participant(self):
        from network.sfu import SFURoom
        room = SFURoom("test-room")
        participants = room.add_participant("sid1", "Alice", ["audio", "video"])
        assert not room.is_empty()
        assert "sid1" in participants

    def test_remove_participant(self):
        from network.sfu import SFURoom
        room = SFURoom("test-room")
        room.add_participant("sid1", "Alice")
        info = room.remove_participant("sid1")
        assert info is not None
        assert info["username"] == "Alice"
        assert room.is_empty()

    def test_remove_nonexistent_participant(self):
        from network.sfu import SFURoom
        room = SFURoom("test-room")
        info = room.remove_participant("sid1")
        assert info is None

    def test_get_other_participants(self):
        from network.sfu import SFURoom
        room = SFURoom("test-room")
        room.add_participant("sid1", "Alice")
        room.add_participant("sid2", "Bob")
        room.add_participant("sid3", "Charlie")
        others = room.get_other_participants("sid1")
        assert len(others) == 2
        usernames = {p["username"] for p in others}
        assert usernames == {"Bob", "Charlie"}

    def test_set_upstream_ready(self):
        from network.sfu import SFURoom
        room = SFURoom("test-room")
        room.add_participant("sid1", "Alice")
        assert not room.participants["sid1"]["upstream_ready"]
        room.set_upstream_ready("sid1")
        assert room.participants["sid1"]["upstream_ready"]

    def test_get_stats(self):
        from network.sfu import SFURoom
        room = SFURoom("test-room")
        room.add_participant("sid1", "Alice", ["audio"])
        room.add_participant("sid2", "Bob", ["audio", "video"])
        stats = room.get_stats()
        assert stats["room_id"] == "test-room"
        assert stats["participants"] == 2
        assert len(stats["members"]) == 2

    def test_media_types_default(self):
        from network.sfu import SFURoom
        room = SFURoom("test-room")
        room.add_participant("sid1", "Alice")
        assert room.participants["sid1"]["media_types"] == ["audio"]

    def test_multiple_join_leave(self):
        from network.sfu import SFURoom
        room = SFURoom("test-room")
        room.add_participant("sid1", "Alice")
        room.add_participant("sid2", "Bob")
        room.add_participant("sid3", "Charlie")
        assert len(room.participants) == 3
        room.remove_participant("sid2")
        assert len(room.participants) == 2
        others = room.get_other_participants("sid1")
        assert len(others) == 1
        assert others[0]["username"] == "Charlie"


class TestMediaBridgeAvailability:
    """Test media relay availability detection."""

    def test_aiortc_import(self):
        """aiortc should be importable."""
        import aiortc
        assert hasattr(aiortc, "RTCPeerConnection")

    def test_media_relay_import(self):
        """MediaRelay should be importable from aiortc contrib."""
        from aiortc.contrib.media import MediaRelay
        relay = MediaRelay()
        assert relay is not None

    def test_media_bridge_module_import(self):
        """SFUMediaBridge should be importable."""
        from network.media_relay import SFUMediaBridge, AIORTC_AVAILABLE
        assert AIORTC_AVAILABLE is True

    def test_media_bridge_init(self):
        """SFUMediaBridge should initialize without starting."""
        from network.media_relay import SFUMediaBridge
        bridge = SFUMediaBridge()
        assert not bridge.available

    def test_media_bridge_stats_before_start(self):
        """Stats should work even before starting."""
        from network.media_relay import SFUMediaBridge
        bridge = SFUMediaBridge()
        stats = bridge.get_stats()
        assert stats["available"] is False
        assert stats["rooms"] == 0

    def test_media_bridge_start_stop(self):
        """Media bridge should start and stop cleanly."""
        from network.media_relay import SFUMediaBridge
        bridge = SFUMediaBridge()
        bridge.start()
        assert bridge.available
        stats = bridge.get_stats()
        assert stats["available"] is True
        bridge.stop()

    def test_media_bridge_double_start(self):
        """Starting twice should be safe."""
        from network.media_relay import SFUMediaBridge
        bridge = SFUMediaBridge()
        bridge.start()
        bridge.start()  # Should not raise
        assert bridge.available
        bridge.stop()


class TestSFUManagerMode:
    """Test SFU manager mode detection."""

    def test_sfu_manager_init(self):
        """SFU manager should initialize with a mock sio."""
        sio = MagicMock()
        sio.on = MagicMock(return_value=lambda f: f)
        from network.sfu import SFUManager
        mgr = SFUManager(sio)
        assert mgr is not None

    def test_sfu_has_media_relay(self):
        """SFU should detect media relay availability."""
        sio = MagicMock()
        sio.on = MagicMock(return_value=lambda f: f)
        from network.sfu import SFUManager
        mgr = SFUManager(sio)
        # Should have media relay since aiortc is installed
        assert mgr.has_media_relay is True

    def test_sfu_stats_include_mode(self):
        """SFU stats should include the mode."""
        sio = MagicMock()
        sio.on = MagicMock(return_value=lambda f: f)
        from network.sfu import SFUManager
        mgr = SFUManager(sio)
        stats = mgr.get_stats()
        assert "mode" in stats
        assert stats["mode"] in ("server_relay", "signaling_relay")

    def test_sfu_stats_include_media_bridge(self):
        """SFU stats should include media bridge info."""
        sio = MagicMock()
        sio.on = MagicMock(return_value=lambda f: f)
        from network.sfu import SFUManager
        mgr = SFUManager(sio)
        stats = mgr.get_stats()
        if mgr.has_media_relay:
            assert "media_bridge" in stats

    def test_sfu_room_creation(self):
        """SFU should create rooms on demand."""
        sio = MagicMock()
        sio.on = MagicMock(return_value=lambda f: f)
        from network.sfu import SFUManager
        mgr = SFUManager(sio)
        room = mgr._get_or_create_room("test-room")
        assert room is not None
        assert room.room_id == "test-room"

    def test_sfu_handle_disconnect(self):
        """SFU should handle disconnect gracefully."""
        sio = MagicMock()
        sio.on = MagicMock(return_value=lambda f: f)
        from network.sfu import SFUManager
        mgr = SFUManager(sio)
        # Should not raise even for unknown sid
        mgr.handle_disconnect("unknown-sid")


class TestPeerState:
    """Test PeerState data class."""

    def test_peer_state_creation(self):
        from network.media_relay import PeerState
        pc = MagicMock()
        state = PeerState("sid1", "Alice", pc)
        assert state.sid == "sid1"
        assert state.username == "Alice"
        assert state.pc is pc
        assert state.tracks == {}
        assert state.subscriptions == []
        assert not state.renegotiation_needed
