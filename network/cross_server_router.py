"""
Helen WiFi - Cross-Server Signal Router
Routes WebRTC signaling and other events between users across servers.

Problem: Previously, sio.emit(room=target_sid) only works locally.
If the user is on a remote server, the signal never arrives.

Solution: CrossServerRouter decides automatically:
  1. If user is local → emit directly
  2. If user is on a known remote server → forward via mesh
  3. If neither works → try chain relay via multi_bridge

Signals routed:
  - webrtc_offer / webrtc_answer / webrtc_ice (1-to-1 calls)
  - screen_offer / screen_answer / screen_ice (screen sharing)
  - group_call_offer / group_call_answer / group_call_ice (group calls)
  - voice_room_offer / voice_room_answer / voice_room_ice (voice rooms)
  - screen_share_started / screen_share_stopped (notifications)
  - group_call_invite (group call invitations)
  - group_call_peer_joined / group_call_peer_left (peer events)
  - voice_room_updated (voice room state changes)
"""
import logging
import threading
import time

logger = logging.getLogger("BRO.xrouter")


# All WebRTC signaling events that need cross-server routing
ROUTABLE_EVENTS = frozenset({
    # 1-to-1 calls
    "webrtc_offer", "webrtc_answer", "webrtc_ice",
    # Screen sharing
    "screen_offer", "screen_answer", "screen_ice",
    "screen_share_started", "screen_share_stopped",
    # Group calls
    "group_call_offer", "group_call_answer", "group_call_ice",
    "group_call_invite",
    "group_call_peer_joined", "group_call_peer_left",
    # Voice rooms
    "voice_room_offer", "voice_room_answer", "voice_room_ice",
    "voice_room_updated",
    # Cross-server call management
    "incoming_call", "call_accepted", "call_rejected", "call_ended",
    # File sharing notifications
    "file_shared",
    # Chat
    "chat_message", "dm_message",
})


class DeliveryStats:
    """Track delivery statistics for diagnostics."""

    def __init__(self):
        self._lock = threading.Lock()
        self.local = 0
        self.mesh = 0
        self.relay = 0
        self.failed = 0
        self.total = 0

    def record(self, method):
        with self._lock:
            self.total += 1
            if method == "local":
                self.local += 1
            elif method == "mesh":
                self.mesh += 1
            elif method == "relay":
                self.relay += 1
            else:
                self.failed += 1

    def to_dict(self):
        with self._lock:
            return {
                "total": self.total,
                "local": self.local,
                "mesh": self.mesh,
                "relay": self.relay,
                "failed": self.failed,
            }


class CrossServerRouter:
    """
    Intelligent signal router that transparently handles local and remote delivery.

    Usage:
        router = CrossServerRouter(sio, mesh_node, ws_mesh_bridge, server_id)
        router.route("webrtc_offer", data, target_sid)
    """

    def __init__(self, sio, mesh_node, ws_mesh_bridge, server_id, clients_ref=None):
        """
        Args:
            sio: Flask-SocketIO instance
            mesh_node: MeshNode instance for HTTP-based mesh forwarding
            ws_mesh_bridge: WebSocketMeshBridge for persistent connections
            server_id: This server's unique ID
            clients_ref: Reference to BROServer.clients dict for local user lookup
        """
        self.sio = sio
        self.mesh = mesh_node
        self.ws_mesh = ws_mesh_bridge
        self.server_id = server_id
        self.clients = clients_ref or {}
        self.stats = DeliveryStats()
        self._lock = threading.Lock()

        logger.info("CrossServerRouter initialized for server %s", server_id)

    def route(self, event, data, target_sid=None, target_username=None):
        """
        Route an event to the target user, whether local or remote.

        Args:
            event: Socket.IO event name
            data: Event data dict
            target_sid: Target user's socket ID (preferred)
            target_username: Target username (used if sid not found locally)

        Returns:
            True if delivery succeeded (or was attempted via mesh), False if failed
        """
        # Try local delivery first
        if target_sid and self._is_local(target_sid):
            try:
                self.sio.emit(event, data, room=target_sid)
                self.stats.record("local")
                return True
            except Exception as e:
                logger.error("Local emit failed for %s: %s", event, e)

        # Try to find user locally by username
        if target_username:
            local_sid = self._find_local_sid(target_username)
            if local_sid:
                try:
                    self.sio.emit(event, data, room=local_sid)
                    self.stats.record("local")
                    return True
                except Exception as e:
                    logger.error("Local emit by username failed for %s: %s", event, e)

        # Try mesh forwarding (HTTP-based)
        if target_sid and self.mesh:
            remote_server = self.mesh.find_user_server(target_sid)
            if remote_server:
                try:
                    self.mesh.forward_to_peer(
                        remote_server,
                        "xrouter_deliver",
                        {
                            "event": event,
                            "data": data,
                            "target_sid": target_sid,
                            "target_username": target_username,
                            "source_server": self.server_id,
                        },
                    )
                    self.stats.record("mesh")
                    return True
                except Exception as e:
                    logger.error("Mesh forward failed for %s to %s: %s", event, remote_server, e)

        # Try mesh forwarding by username
        if target_username and self.mesh:
            for srv_id, users in self.mesh.remote_users.items():
                for u in users:
                    if u.get("username") == target_username:
                        try:
                            self.mesh.forward_to_peer(
                                srv_id,
                                "xrouter_deliver",
                                {
                                    "event": event,
                                    "data": data,
                                    "target_sid": u.get("sid"),
                                    "target_username": target_username,
                                    "source_server": self.server_id,
                                },
                            )
                            self.stats.record("mesh")
                            return True
                        except Exception as e:
                            logger.error("Mesh forward by username failed: %s", e)

        # Try chain relay via ws_mesh bridge
        if self.ws_mesh and (target_sid or target_username):
            try:
                relay_data = {
                    "type": "xrouter_relay",
                    "event": event,
                    "data": data,
                    "target_sid": target_sid,
                    "target_username": target_username,
                    "source_server": self.server_id,
                    "hops": 0,
                    "max_hops": 3,
                }
                self.ws_mesh.broadcast_to_peers(relay_data)
                self.stats.record("relay")
                return True
            except Exception as e:
                logger.error("Relay broadcast failed for %s: %s", event, e)

        # All methods failed
        self.stats.record("failed")
        logger.warning(
            "Failed to route %s to sid=%s user=%s",
            event, target_sid, target_username,
        )
        return False

    def broadcast_to_room_members(self, event, data, room_id, member_usernames, exclude_sid=None):
        """
        Broadcast an event to all members of a room across all servers.

        Args:
            event: Socket.IO event name
            data: Event data
            room_id: Room ID for context
            member_usernames: List of usernames in the room
            exclude_sid: Optional SID to exclude (usually the sender)
        """
        for username in member_usernames:
            # Find local SID
            local_sid = self._find_local_sid(username)
            if local_sid and local_sid != exclude_sid:
                try:
                    self.sio.emit(event, data, room=local_sid)
                    self.stats.record("local")
                    continue
                except Exception:
                    pass

            # Try remote delivery
            if self.mesh:
                for srv_id, users in self.mesh.remote_users.items():
                    for u in users:
                        if u.get("username") == username and u.get("sid") != exclude_sid:
                            try:
                                self.mesh.forward_to_peer(
                                    srv_id,
                                    "xrouter_deliver",
                                    {
                                        "event": event,
                                        "data": data,
                                        "target_sid": u.get("sid"),
                                        "target_username": username,
                                        "source_server": self.server_id,
                                    },
                                )
                                self.stats.record("mesh")
                            except Exception as e:
                                logger.error("Room broadcast mesh error: %s", e)

    def handle_incoming_delivery(self, payload):
        """
        Handle an incoming xrouter_deliver message from a remote server.
        Delivers the enclosed event to the local target user.
        """
        event = payload.get("event")
        data = payload.get("data")
        target_sid = payload.get("target_sid")
        target_username = payload.get("target_username")

        if not event or not data:
            return False

        # Try delivery by SID first
        if target_sid and self._is_local(target_sid):
            try:
                self.sio.emit(event, data, room=target_sid)
                self.stats.record("local")
                return True
            except Exception as e:
                logger.error("Incoming delivery by SID failed: %s", e)

        # Try by username
        if target_username:
            local_sid = self._find_local_sid(target_username)
            if local_sid:
                try:
                    self.sio.emit(event, data, room=local_sid)
                    self.stats.record("local")
                    return True
                except Exception as e:
                    logger.error("Incoming delivery by username failed: %s", e)

        logger.warning(
            "Could not deliver incoming %s to sid=%s user=%s",
            event, target_sid, target_username,
        )
        return False

    def handle_relay(self, payload):
        """
        Handle a relay message that's being chain-forwarded.
        If the target is local, deliver. Otherwise, forward with hop count.
        """
        target_sid = payload.get("target_sid")
        target_username = payload.get("target_username")
        hops = payload.get("hops", 0)
        max_hops = payload.get("max_hops", 3)

        # Check if target is local
        if target_sid and self._is_local(target_sid):
            return self.handle_incoming_delivery(payload)
        if target_username:
            local_sid = self._find_local_sid(target_username)
            if local_sid:
                payload["target_sid"] = local_sid
                return self.handle_incoming_delivery(payload)

        # Forward if we haven't exceeded hop limit
        if hops < max_hops and self.ws_mesh:
            payload["hops"] = hops + 1
            try:
                self.ws_mesh.broadcast_to_peers(payload)
                return True
            except Exception as e:
                logger.error("Relay forward failed: %s", e)

        return False

    def get_stats(self):
        """Get router statistics."""
        return self.stats.to_dict()

    # ---------- internal helpers ----------

    def _is_local(self, sid):
        """Check if a SID belongs to a locally connected user."""
        return sid in self.clients

    def _find_local_sid(self, username):
        """Find the local SID for a username."""
        for sid, info in self.clients.items():
            if info.get("username") == username:
                return sid
        return None
