"""
Helen WiFi - SFU (Selective Forwarding Unit) Media Relay
Lightweight SFU for reliable media delivery.
Clients connect to SFU instead of directly to each other.
Eliminates P2P NAT traversal issues.

Architecture:
  Client A --[upstream]--> SFU --[downstream]--> Client B
  Client B --[upstream]--> SFU --[downstream]--> Client A

Benefits over P2P:
  - No NAT/CGNAT/Enterprise WiFi issues
  - Server always reachable via TURN if needed
  - N connections instead of N*(N-1)/2
  - Easy recording, monitoring, transcoding
"""
import logging
import threading
import time
import uuid
from collections import defaultdict

logger = logging.getLogger("BRO.sfu")

# Maximum participants per SFU room (prevents server overload)
MAX_ROOM_SIZE = 20


class SFURoom:
    """Represents a media room in the SFU.

    Each participant has:
    - An upstream: their media sent to SFU
    - Downstreams: SFU forwarding other participants' media to them
    """

    def __init__(self, room_id):
        self.room_id = room_id
        self.created_at = time.time()
        self.participants = {}  # {sid: ParticipantInfo}
        self._lock = threading.Lock()

    def add_participant(self, sid, username, media_types=None):
        """Add a participant to the room. Returns participant list or None if full."""
        with self._lock:
            if len(self.participants) >= MAX_ROOM_SIZE:
                logger.warning(f"SFU room {self.room_id}: rejected {username} (room full: {MAX_ROOM_SIZE})")
                return None
            self.participants[sid] = {
                "sid": sid,
                "username": username,
                "joined_at": time.time(),
                "media_types": media_types or ["audio"],
                "upstream_ready": False,
                "muted": False,
                "video_enabled": True,
            }
        logger.info(f"SFU room {self.room_id}: {username} joined ({len(self.participants)} participants)")
        return list(self.participants.keys())

    def remove_participant(self, sid):
        """Remove a participant from the room."""
        with self._lock:
            info = self.participants.pop(sid, None)
        if info:
            logger.info(f"SFU room {self.room_id}: {info['username']} left ({len(self.participants)} participants)")
        return info

    def get_other_participants(self, sid):
        """Get list of other participants in the room."""
        with self._lock:
            return [p for s, p in self.participants.items() if s != sid]

    def set_upstream_ready(self, sid):
        """Mark participant's upstream as ready."""
        with self._lock:
            if sid in self.participants:
                self.participants[sid]["upstream_ready"] = True

    def is_empty(self):
        return len(self.participants) == 0

    def get_stats(self):
        return {
            "room_id": self.room_id,
            "participants": len(self.participants),
            "created_at": self.created_at,
            "members": [
                {"sid": s[:8], "username": p["username"],
                 "media": p["media_types"], "upstream_ready": p["upstream_ready"]}
                for s, p in self.participants.items()
            ],
        }


class SFUManager:
    """Manages SFU rooms and coordinates media relay for group calls.

    Two modes:
    1. **Real SFU** (when aiortc available): Server terminates WebRTC and
       relays media. Each participant has 1 connection to the server.
       Scales to large groups.
    2. **Signaling relay** (fallback): Server coordinates P2P WebRTC
       between participants. Each participant connects to every other.
       Good for groups up to 4-5.

    Architecture (Real SFU):
      Client A --[WebRTC]--> Server --[relay]--> Client B, C, D
      Client B --[WebRTC]--> Server --[relay]--> Client A, C, D
      N connections total (not N*(N-1)/2)
    """

    def __init__(self, sio):
        self.sio = sio
        self._rooms = {}            # {room_id: SFURoom}
        self._participant_rooms = {}  # {sid: room_id}
        self._lock = threading.Lock()

        # Negotiation tracking (for signaling relay fallback)
        self._pending_negotiations = {}  # {negotiation_id: {offer_sid, answer_sid, state}}
        self._NEGOTIATION_TIMEOUT = 30  # seconds

        # Dominant speaker tracking: {room_id: {sid: audio_level}}
        self._audio_levels = defaultdict(lambda: defaultdict(float))
        self._dominant_speaker = {}  # {room_id: sid}

        # Real SFU media relay (aiortc)
        self._media_bridge = None
        self._init_media_bridge()

        self._setup_handlers()

        # Start cleanup thread for stale negotiations
        t = threading.Thread(target=self._cleanup_loop, daemon=True)
        t.start()

    def _init_media_bridge(self):
        """Initialize the server-side media relay if aiortc is available."""
        try:
            from network.media_relay import SFUMediaBridge, AIORTC_AVAILABLE
            if AIORTC_AVAILABLE:
                self._media_bridge = SFUMediaBridge()
                self._media_bridge.start(
                    on_renegotiate=self._on_media_renegotiate,
                    on_ice_candidate=self._on_media_ice,
                )
                logger.info("SFU using real media relay (aiortc)")
            else:
                logger.info("SFU using signaling relay (aiortc not available)")
        except Exception as e:
            logger.info(f"SFU using signaling relay fallback: {e}")

    @property
    def has_media_relay(self):
        """Whether the real media relay is active."""
        return self._media_bridge is not None and self._media_bridge.available

    @property
    def is_available(self):
        """Whether this SFU can accept new cross-server rooms."""
        return len(self._rooms) < 50  # Max concurrent SFU rooms

    def get_capacity(self):
        """Return current capacity info for cross-server negotiation scoring."""
        return {"active_rooms": len(self._rooms), "has_media_relay": self.has_media_relay, "available": self.is_available}

    def _on_media_renegotiate(self, room_id, sid, sdp_dict):
        """Called by media bridge when server needs to renegotiate with client."""
        self.sio.emit("sfu_server_offer", {
            "sdp": sdp_dict["sdp"],
            "type": sdp_dict["type"],
            "room_id": room_id,
        }, room=sid)

    def _on_media_ice(self, room_id, sid, candidate_dict):
        """Called by media bridge when server generates an ICE candidate."""
        self.sio.emit("sfu_server_ice", {
            "candidate": candidate_dict,
            "room_id": room_id,
        }, room=sid)

    def _setup_handlers(self):
        """Register SFU-specific Socket.IO events."""
        sio = self.sio

        @sio.on("sfu_join")
        def on_sfu_join(data):
            """Client wants to join an SFU room."""
            from flask import request
            sid = request.sid
            room_id = data.get("room_id")
            username = data.get("username", sid[:6])
            media_types = data.get("media_types", ["audio"])

            if not room_id:
                return

            room = self._get_or_create_room(room_id)
            existing_participants = room.add_participant(sid, username, media_types)
            if existing_participants is None:
                # Room is full
                sio.emit("sfu_error", {
                    "room_id": room_id,
                    "error": "room_full",
                    "max_size": MAX_ROOM_SIZE,
                }, room=sid)
                return
            self._participant_rooms[sid] = room_id
            sio.enter_room(sid, f"sfu_{room_id}")

            # Tell the new participant about existing members and SFU mode
            others = room.get_other_participants(sid)
            sio.emit("sfu_room_state", {
                "room_id": room_id,
                "participants": [
                    {"sid": p["sid"], "username": p["username"],
                     "media_types": p["media_types"]}
                    for p in others
                ],
                "sfu_mode": True,
                "server_relay": self.has_media_relay,  # True = real SFU
                "ice_policy": "relay",  # Force relay for SFU
            }, room=sid)

            # Tell existing participants about new member
            for p in others:
                sio.emit("sfu_peer_joined", {
                    "room_id": room_id,
                    "sid": sid,
                    "username": username,
                    "media_types": media_types,
                }, room=p["sid"])

            # Initiate negotiations between new participant and existing ones
            for p in others:
                self._initiate_negotiation(room_id, sid, p["sid"])

        @sio.on("sfu_leave")
        def on_sfu_leave(data):
            """Client leaves SFU room."""
            from flask import request
            self._handle_leave(request.sid)

        @sio.on("sfu_offer")
        def on_sfu_offer(data):
            """Client sends SDP offer.

            Real SFU mode: offer goes to server media relay.
            Fallback mode: offer is relayed to target peer.
            """
            from flask import request
            sid = request.sid
            room_id = data.get("room_id")

            if self.has_media_relay and room_id:
                # Real SFU: handle offer server-side
                room = self._rooms.get(room_id)
                username = ""
                if room:
                    p = room.participants.get(sid)
                    if p:
                        username = p["username"]
                answer = self._media_bridge.handle_offer(
                    room_id, sid, username, data.get("sdp")
                )
                if answer:
                    sio.emit("sfu_answer", {
                        "sdp": answer["sdp"],
                        "type": answer["type"],
                        "sender": "__server__",
                        "room_id": room_id,
                    }, room=sid)
            else:
                # Fallback: relay offer to target peer
                target = data.get("target")
                if target:
                    sio.emit("sfu_offer", {
                        "sdp": data.get("sdp"),
                        "type": data.get("type", "offer"),
                        "sender": sid,
                        "negotiation_id": data.get("negotiation_id"),
                        "room_id": room_id,
                    }, room=target)

        @sio.on("sfu_answer")
        def on_sfu_answer(data):
            """Client sends SDP answer.

            Real SFU mode: answer goes to server media relay (renegotiation).
            Fallback mode: answer is relayed to target peer.
            """
            from flask import request
            sid = request.sid
            room_id = data.get("room_id")

            if self.has_media_relay and data.get("sender") == "__server__":
                # This shouldn't happen (server sends answers, not receives)
                pass
            elif self.has_media_relay and room_id:
                # Client answering a server-initiated renegotiation
                self._media_bridge.handle_answer(
                    room_id, sid, data.get("sdp")
                )
            else:
                # Fallback: relay answer to target peer
                target = data.get("target")
                if target:
                    sio.emit("sfu_answer", {
                        "sdp": data.get("sdp"),
                        "type": data.get("type", "answer"),
                        "sender": sid,
                        "negotiation_id": data.get("negotiation_id"),
                        "room_id": room_id,
                    }, room=target)

        @sio.on("sfu_ice")
        def on_sfu_ice(data):
            """Client sends ICE candidate.

            Real SFU mode: candidate goes to server media relay.
            Fallback mode: candidate is relayed to target peer.
            """
            from flask import request
            sid = request.sid
            room_id = data.get("room_id")

            if self.has_media_relay and room_id:
                # Real SFU: add candidate to server-side PC
                candidate = data.get("candidate")
                if candidate and isinstance(candidate, dict):
                    self._media_bridge.add_ice_candidate(
                        room_id, sid, candidate
                    )
            else:
                # Fallback: relay to target peer
                target = data.get("target")
                if target:
                    sio.emit("sfu_ice", {
                        "candidate": data.get("candidate"),
                        "sender": sid,
                        "room_id": room_id,
                    }, room=target)

        @sio.on("sfu_server_answer")
        def on_sfu_server_answer(data):
            """Client responds to server-initiated renegotiation offer."""
            from flask import request
            sid = request.sid
            room_id = data.get("room_id")
            if self.has_media_relay and room_id:
                self._media_bridge.handle_answer(
                    room_id, sid, data.get("sdp")
                )

        @sio.on("sfu_media_state")
        def on_media_state(data):
            """Client reports media state change (mute/unmute, video on/off)."""
            from flask import request
            sid = request.sid
            room_id = self._participant_rooms.get(sid)
            if not room_id:
                return
            room = self._rooms.get(room_id)
            if not room:
                return

            with room._lock:
                p = room.participants.get(sid)
                if p:
                    if "muted" in data:
                        p["muted"] = data["muted"]
                    if "video_enabled" in data:
                        p["video_enabled"] = data["video_enabled"]

            # Broadcast state change to other participants
            for other in room.get_other_participants(sid):
                sio.emit("sfu_peer_media_state", {
                    "sid": sid,
                    "muted": data.get("muted"),
                    "video_enabled": data.get("video_enabled"),
                }, room=other["sid"])

        @sio.on("sfu_upstream_ready")
        def on_upstream_ready(data):
            """Client reports upstream media is ready."""
            from flask import request
            sid = request.sid
            room_id = self._participant_rooms.get(sid)
            if room_id:
                room = self._rooms.get(room_id)
                if room:
                    room.set_upstream_ready(sid)

        @sio.on("sfu_audio_level")
        def on_audio_level(data):
            """Client reports audio level for dominant speaker detection."""
            from flask import request
            sid = request.sid
            room_id = self._participant_rooms.get(sid)
            if not room_id:
                return
            level = data.get("level", 0)
            self._audio_levels[room_id][sid] = level
            # Determine dominant speaker
            levels = self._audio_levels[room_id]
            if levels:
                dominant = max(levels, key=levels.get)
                if levels[dominant] > 0.01 and self._dominant_speaker.get(room_id) != dominant:
                    self._dominant_speaker[room_id] = dominant
                    room = self._rooms.get(room_id)
                    if room:
                        username = room.participants.get(dominant, {}).get("username", "")
                        sio.emit("sfu_dominant_speaker", {
                            "sid": dominant,
                            "username": username,
                            "room_id": room_id,
                        }, room=f"sfu_{room_id}")

        @sio.on("sfu_quality_request")
        def on_quality_request(data):
            """Client requests quality adjustment (bandwidth adaptation)."""
            from flask import request
            sid = request.sid
            room_id = self._participant_rooms.get(sid)
            if not room_id:
                return
            quality = data.get("quality", "medium")  # low, medium, high
            target = data.get("target")
            if target:
                sio.emit("sfu_quality_hint", {
                    "quality": quality,
                    "from_sid": sid,
                    "room_id": room_id,
                }, room=target)

    def _get_or_create_room(self, room_id):
        """Get or create an SFU room."""
        with self._lock:
            if room_id not in self._rooms:
                self._rooms[room_id] = SFURoom(room_id)
            return self._rooms[room_id]

    def _initiate_negotiation(self, room_id, new_sid, existing_sid):
        """Start WebRTC negotiation between two participants.

        The existing participant creates the offer (they know about the room).
        """
        negotiation_id = str(uuid.uuid4())[:10]
        self._pending_negotiations[negotiation_id] = {
            "room_id": room_id,
            "offer_sid": existing_sid,    # Existing creates offer
            "answer_sid": new_sid,        # New participant answers
            "state": "pending",
            "created_at": time.time(),
        }

        # Tell the existing participant to create an offer for the new one
        self.sio.emit("sfu_create_offer", {
            "target": new_sid,
            "negotiation_id": negotiation_id,
            "room_id": room_id,
        }, room=existing_sid)

    def _handle_leave(self, sid):
        """Handle participant leaving."""
        room_id = self._participant_rooms.pop(sid, None)
        if not room_id:
            return

        room = self._rooms.get(room_id)
        if not room:
            return

        info = room.remove_participant(sid)
        self.sio.leave_room(sid, f"sfu_{room_id}")

        # Clean up media bridge connection
        if self.has_media_relay:
            try:
                self._media_bridge.remove_participant(room_id, sid)
            except Exception:
                pass

        if info:
            # Notify remaining participants
            for p in room.get_other_participants(sid):
                self.sio.emit("sfu_peer_left", {
                    "room_id": room_id,
                    "sid": sid,
                    "username": info["username"],
                }, room=p["sid"])

        # Clean up empty rooms
        if room.is_empty():
            with self._lock:
                self._rooms.pop(room_id, None)

    def handle_disconnect(self, sid):
        """Handle socket disconnect."""
        self._handle_leave(sid)

    def get_room_stats(self, room_id):
        """Get stats for a specific room."""
        room = self._rooms.get(room_id)
        if room:
            return room.get_stats()
        return None

    def _cleanup_loop(self):
        """Periodically clean up stale negotiations."""
        while True:
            time.sleep(15)
            now = time.time()
            stale = [nid for nid, info in self._pending_negotiations.items()
                     if now - info.get("created_at", 0) > self._NEGOTIATION_TIMEOUT]
            for nid in stale:
                self._pending_negotiations.pop(nid, None)
            if stale:
                logger.debug(f"Cleaned {len(stale)} stale SFU negotiations")

    def get_stats(self):
        """Get overall SFU statistics."""
        stats = {
            "active_rooms": len(self._rooms),
            "total_participants": sum(len(r.participants) for r in self._rooms.values()),
            "rooms": [r.get_stats() for r in self._rooms.values()],
            "pending_negotiations": len(self._pending_negotiations),
            "mode": "server_relay" if self.has_media_relay else "signaling_relay",
        }
        if self._media_bridge:
            stats["media_bridge"] = self._media_bridge.get_stats()
        return stats
