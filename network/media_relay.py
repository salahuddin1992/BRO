"""
Helen WiFi - Real SFU Media Relay using aiortc

Server-side WebRTC that terminates media from each participant
and forwards (relays) it to all others in the room.

Architecture:
  Client A --[WebRTC]--> Server PC-A --[relay]--> Server PC-B --[WebRTC]--> Client B
  Client B --[WebRTC]--> Server PC-B --[relay]--> Server PC-A --[WebRTC]--> Client A

Benefits over signaling-only SFU:
  - N connections total (not N*(N-1)/2)
  - Server controls bandwidth per-subscriber
  - Easy to add recording, transcoding later
  - Works reliably behind NATs (all connections are to server)

Threading:
  aiortc uses asyncio. The main server uses eventlet/gevent.
  This module runs its own asyncio event loop in a dedicated thread
  and provides a synchronous API for the SFU signaling layer.
"""
import asyncio
import logging
import threading
import time

logger = logging.getLogger("BRO.media_relay")

try:
    from aiortc import RTCPeerConnection, RTCSessionDescription
    from aiortc.contrib.media import MediaRelay
    AIORTC_AVAILABLE = True
except ImportError:
    AIORTC_AVAILABLE = False
    logger.warning("aiortc not available - server-side SFU media relay disabled")


class PeerState:
    """State for a single participant's server-side PeerConnection."""

    __slots__ = ("sid", "username", "pc", "tracks", "subscriptions",
                 "renegotiation_needed", "joined_at")

    def __init__(self, sid, username, pc):
        self.sid = sid
        self.username = username
        self.pc = pc
        self.tracks = {}           # {kind: MediaStreamTrack}  upstream from client
        self.subscriptions = []    # relay.subscribe() results added to this PC
        self.renegotiation_needed = False
        self.joined_at = time.time()


class SFUMediaBridge:
    """Real SFU media relay using aiortc.

    Provides a synchronous API (callable from eventlet/gevent threads)
    that internally dispatches to an asyncio event loop running in a
    dedicated thread.
    """

    def __init__(self):
        self._loop = None
        self._thread = None
        self._relay = None          # aiortc MediaRelay instance
        self._rooms = {}            # {room_id: {sid: PeerState}}
        self._lock = threading.Lock()
        self._started = False
        self._on_renegotiate = None  # callback(room_id, sid, sdp_dict)
        self._on_ice_candidate = None  # callback(room_id, sid, candidate_dict)

    # ═══════════════════════════════════════════════════════════════════════
    # Lifecycle
    # ═══════════════════════════════════════════════════════════════════════

    def start(self, on_renegotiate=None, on_ice_candidate=None):
        """Start the media bridge.

        Args:
            on_renegotiate: Called when the server needs to renegotiate with a
                client after adding new tracks.  Signature: (room_id, sid, sdp_dict)
            on_ice_candidate: Called when the server generates an ICE candidate.
                Signature: (room_id, sid, candidate_dict)
        """
        if self._started:
            return
        if not AIORTC_AVAILABLE:
            logger.warning("Cannot start SFU media bridge: aiortc not installed")
            return

        self._on_renegotiate = on_renegotiate
        self._on_ice_candidate = on_ice_candidate
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="SFU-MediaRelay"
        )
        self._thread.start()
        self._run_sync(self._init())
        self._started = True
        logger.info("SFU Media Bridge started (aiortc)")

    def stop(self):
        """Stop the media bridge and close all connections."""
        if not self._started:
            return
        self._started = False
        try:
            self._run_sync(self._close_all())
        except Exception:
            pass
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        logger.info("SFU Media Bridge stopped")

    @property
    def available(self):
        return self._started and AIORTC_AVAILABLE

    # ═══════════════════════════════════════════════════════════════════════
    # Synchronous public API (called from SFU signaling in eventlet/gevent)
    # ═══════════════════════════════════════════════════════════════════════

    def handle_offer(self, room_id, sid, username, sdp):
        """Process SDP offer from a participant.

        Returns dict {"sdp": ..., "type": "answer"} or None on failure.
        """
        return self._run_sync(
            self._handle_offer(room_id, sid, username, sdp)
        )

    def handle_answer(self, room_id, sid, sdp):
        """Process SDP answer from a participant (during renegotiation)."""
        return self._run_sync(
            self._handle_answer(room_id, sid, sdp)
        )

    def add_ice_candidate(self, room_id, sid, candidate_data):
        """Add an ICE candidate for a participant's server-side PC."""
        return self._run_sync(
            self._add_ice_candidate(room_id, sid, candidate_data)
        )

    def remove_participant(self, room_id, sid):
        """Remove a participant and clean up their connections."""
        return self._run_sync(
            self._remove_participant(room_id, sid)
        )

    def get_stats(self):
        """Get media bridge statistics."""
        with self._lock:
            rooms_info = {}
            for room_id, room in self._rooms.items():
                rooms_info[room_id] = {
                    "participants": len(room),
                    "members": [
                        {
                            "sid": s[:8],
                            "username": state.username,
                            "tracks": list(state.tracks.keys()),
                            "subscriptions": len(state.subscriptions),
                        }
                        for s, state in room.items()
                    ],
                }
            return {
                "available": self.available,
                "rooms": len(self._rooms),
                "total_participants": sum(len(r) for r in self._rooms.values()),
                "rooms_detail": rooms_info,
            }

    # ═══════════════════════════════════════════════════════════════════════
    # Event loop management
    # ═══════════════════════════════════════════════════════════════════════

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _run_sync(self, coro, timeout=15):
        """Run an async coroutine from synchronous code."""
        if not self._loop or not self._loop.is_running():
            return None
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=timeout)
        except asyncio.TimeoutError:
            logger.error("Media relay async operation timed out")
            return None
        except Exception as e:
            logger.error(f"Media relay async error: {e}")
            return None

    async def _init(self):
        self._relay = MediaRelay()

    async def _close_all(self):
        with self._lock:
            all_rooms = dict(self._rooms)
            self._rooms.clear()
        for room_id, room in all_rooms.items():
            for sid, state in room.items():
                try:
                    await state.pc.close()
                except Exception:
                    pass

    # ═══════════════════════════════════════════════════════════════════════
    # Async implementation
    # ═══════════════════════════════════════════════════════════════════════

    async def _handle_offer(self, room_id, sid, username, sdp):
        """Create a server-side PC for the participant and generate an answer."""
        pc = RTCPeerConnection()

        with self._lock:
            if room_id not in self._rooms:
                self._rooms[room_id] = {}

            # Close existing PC if reconnecting
            old_state = self._rooms[room_id].get(sid)
            if old_state:
                try:
                    await old_state.pc.close()
                except Exception:
                    pass

            state = PeerState(sid, username, pc)
            self._rooms[room_id][sid] = state

        # Track arrival handler: relay new tracks to all other participants
        @pc.on("track")
        async def on_track(track):
            logger.info(
                f"SFU received {track.kind} from {username} ({sid[:8]}) "
                f"in room {room_id}"
            )
            state.tracks[track.kind] = track
            # Relay this track to every other participant in the room
            await self._relay_track_to_others(room_id, sid, track)

        @pc.on("connectionstatechange")
        async def on_state():
            logger.debug(f"SFU PC [{sid[:8]}]: {pc.connectionState}")
            if pc.connectionState in ("failed", "closed"):
                await self._remove_participant(room_id, sid)

        @pc.on("icecandidate")
        async def on_ice(candidate):
            if candidate and self._on_ice_candidate:
                self._on_ice_candidate(room_id, sid, {
                    "candidate": candidate.candidate,
                    "sdpMid": candidate.sdpMid,
                    "sdpMLineIndex": candidate.sdpMLineIndex,
                })

        # Set remote description (client's offer)
        await pc.setRemoteDescription(
            RTCSessionDescription(sdp=sdp, type="offer")
        )

        # Subscribe this new PC to all existing tracks from other participants
        with self._lock:
            room = self._rooms.get(room_id, {})
            for other_sid, other_state in room.items():
                if other_sid != sid:
                    for kind, track in other_state.tracks.items():
                        try:
                            relayed = self._relay.subscribe(track)
                            pc.addTrack(relayed)
                            state.subscriptions.append(relayed)
                        except Exception as e:
                            logger.debug(
                                f"Relay {kind} from {other_sid[:8]} to {sid[:8]} "
                                f"failed: {e}"
                            )

        # Create and set answer
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        logger.info(
            f"SFU created answer for {username} ({sid[:8]}) in room {room_id}"
        )

        return {
            "sdp": pc.localDescription.sdp,
            "type": "answer",
        }

    async def _handle_answer(self, room_id, sid, sdp):
        """Process answer from client (during server-initiated renegotiation)."""
        with self._lock:
            room = self._rooms.get(room_id, {})
            state = room.get(sid)
        if not state:
            return

        await state.pc.setRemoteDescription(
            RTCSessionDescription(sdp=sdp, type="answer")
        )
        state.renegotiation_needed = False
        logger.debug(f"SFU set answer from {sid[:8]} (renegotiation complete)")

    async def _add_ice_candidate(self, room_id, sid, candidate_data):
        """Add ICE candidate for participant's server-side PC."""
        with self._lock:
            room = self._rooms.get(room_id, {})
            state = room.get(sid)
        if not state:
            return

        candidate_str = candidate_data.get("candidate", "")
        if not candidate_str:
            return

        try:
            # aiortc expects addIceCandidate with specific format
            from aiortc.sdp import candidate_from_sdp
            candidate = candidate_from_sdp(candidate_str.split(":", 1)[-1].strip())
            candidate.sdpMid = candidate_data.get("sdpMid", "0")
            candidate.sdpMLineIndex = candidate_data.get("sdpMLineIndex", 0)
            await state.pc.addIceCandidate(candidate)
        except Exception as e:
            logger.debug(f"ICE candidate error for {sid[:8]}: {e}")

    async def _relay_track_to_others(self, room_id, source_sid, track):
        """Relay a newly arrived track to all other participants in the room."""
        with self._lock:
            room = self._rooms.get(room_id, {})
            others = [
                (sid, state)
                for sid, state in room.items()
                if sid != source_sid
            ]

        for other_sid, other_state in others:
            try:
                relayed = self._relay.subscribe(track)
                other_state.pc.addTrack(relayed)
                other_state.subscriptions.append(relayed)

                # Renegotiate with this participant to inform them of new tracks
                await self._renegotiate(room_id, other_sid, other_state)
            except Exception as e:
                logger.debug(
                    f"Relay {track.kind} to {other_sid[:8]} failed: {e}"
                )

    async def _renegotiate(self, room_id, sid, state):
        """Trigger SDP renegotiation with a participant (server sends offer)."""
        try:
            offer = await state.pc.createOffer()
            await state.pc.setLocalDescription(offer)

            if self._on_renegotiate:
                self._on_renegotiate(room_id, sid, {
                    "sdp": state.pc.localDescription.sdp,
                    "type": "offer",
                })
            state.renegotiation_needed = True
        except Exception as e:
            logger.debug(f"Renegotiation with {sid[:8]} failed: {e}")

    async def _remove_participant(self, room_id, sid):
        """Remove participant, close their PC, and notify others."""
        with self._lock:
            room = self._rooms.get(room_id, {})
            state = room.pop(sid, None)

        if state:
            try:
                await state.pc.close()
            except Exception:
                pass
            logger.info(
                f"SFU removed {state.username} ({sid[:8]}) from room {room_id}"
            )

        # Clean empty rooms
        with self._lock:
            room = self._rooms.get(room_id, {})
            if not room:
                self._rooms.pop(room_id, None)
