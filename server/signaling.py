"""
Helen WiFi - Robust WebRTC Signaling Server
ACK/Retry, Call State Machine, Message Ordering, Dedup,
Heartbeat, Session Recovery, Trickle ICE
"""
import time
import uuid
import logging
import threading
from datetime import datetime
from collections import defaultdict
from enum import Enum

logger = logging.getLogger("BRO.signaling")


# ── Call States ──────────────────────────────────────────────────────────────
class CallState(Enum):
    IDLE = "idle"
    RINGING = "ringing"
    ACCEPTED = "accepted"
    CONNECTING = "connecting"       # ICE negotiation in progress
    CONNECTED = "connected"         # Media flowing
    RECONNECTING = "reconnecting"   # ICE restart in progress
    ENDED = "ended"
    FAILED = "failed"


# Valid state transitions
_TRANSITIONS = {
    CallState.IDLE:         {CallState.RINGING},
    CallState.RINGING:      {CallState.ACCEPTED, CallState.ENDED, CallState.FAILED},
    CallState.ACCEPTED:     {CallState.CONNECTING, CallState.ENDED, CallState.FAILED},
    CallState.CONNECTING:   {CallState.CONNECTED, CallState.RECONNECTING, CallState.ENDED, CallState.FAILED},
    CallState.CONNECTED:    {CallState.RECONNECTING, CallState.ENDED, CallState.FAILED},
    CallState.RECONNECTING: {CallState.CONNECTED, CallState.ENDED, CallState.FAILED},
    CallState.ENDED:        {CallState.IDLE},
    CallState.FAILED:       {CallState.IDLE},
}


# ── Signaling message types that require ACK ────────────────────────────────
ACK_REQUIRED = {
    "webrtc_offer", "webrtc_answer", "webrtc_ice",
    "call_request", "call_accept", "call_reject", "call_end",
    "screen_offer", "screen_answer", "screen_ice",
    "group_call_offer", "group_call_answer", "group_call_ice",
}

# Retry config
MAX_RETRIES = 3
RETRY_DELAY_MS = [500, 1000, 2000]  # Exponential backoff
ACK_TIMEOUT_S = 3.0
MSG_TTL_S = 30.0                    # Discard messages older than this

# Session recovery window
SESSION_RECOVERY_WINDOW_S = 30.0    # Allow reconnection within 30s


class SignalingServer:
    """Enhanced signaling server with ACK/Retry, state machine, and session recovery."""

    def __init__(self, sio):
        self.sio = sio
        self.rooms = {}                # {room_id: {users: [], created}}
        self.user_rooms = {}           # {sid: room_id}
        self._lock = threading.Lock()

        # ── ACK/Retry tracking ───────────────────────────────────────────
        self._pending_acks = {}        # {msg_id: {event, data, target, retries, sent_at}}
        self._seen_messages = {}       # {msg_id: timestamp} for dedup
        self._msg_sequence = defaultdict(int)  # {(sender, target): seq_num}

        # ── Call State Machine ───────────────────────────────────────────
        self._calls = {}               # {call_id: CallRecord}

        # ── Session Recovery ─────────────────────────────────────────────
        self._sessions = {}            # {username: {sid, connected_at, last_heartbeat}}
        self._disconnected = {}        # {username: {old_sid, disconnected_at, pending_messages}}

        # ── Call Diagnostics ─────────────────────────────────────────────
        self._call_logs = []           # [{call_id, participants, states, ice_info, ...}]
        self._max_logs = 500

        # ── Register Socket.IO handlers ──────────────────────────────────
        self._setup_handlers()

        # ── Cleanup timer ────────────────────────────────────────────────
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()

    # ═══════════════════════════════════════════════════════════════════════
    # Call State Machine
    # ═══════════════════════════════════════════════════════════════════════

    def create_call(self, caller_sid, callee_sid, call_type="video"):
        """Create a new call and return call_id."""
        call_id = str(uuid.uuid4())[:12]
        now = time.time()
        self._calls[call_id] = {
            "call_id": call_id,
            "caller_sid": caller_sid,
            "callee_sid": callee_sid,
            "call_type": call_type,
            "state": CallState.IDLE,
            "created_at": now,
            "state_history": [(CallState.IDLE.value, now)],
            "ice_info": {
                "caller": {"candidates": 0, "type": None, "transport": None},
                "callee": {"candidates": 0, "type": None, "transport": None},
            },
        }
        self._transition(call_id, CallState.RINGING)
        return call_id

    def _transition(self, call_id, new_state):
        """Transition call to new state if valid."""
        call = self._calls.get(call_id)
        if not call:
            return False
        current = call["state"]
        if new_state not in _TRANSITIONS.get(current, set()):
            logger.debug(f"Invalid transition {current.value}->{new_state.value} for call {call_id}")
            return False
        call["state"] = new_state
        call["state_history"].append((new_state.value, time.time()))
        logger.info(f"Call {call_id}: {current.value} -> {new_state.value}")

        # Notify participants of state change
        self.sio.emit("call_state_changed", {
            "call_id": call_id,
            "state": new_state.value,
            "timestamp": time.time(),
        }, room=call["caller_sid"])
        self.sio.emit("call_state_changed", {
            "call_id": call_id,
            "state": new_state.value,
            "timestamp": time.time(),
        }, room=call["callee_sid"])

        # Log completed/failed calls
        if new_state in (CallState.ENDED, CallState.FAILED):
            self._log_call(call)
        return True

    def get_call_by_participants(self, sid1, sid2):
        """Find active call between two participants."""
        for call_id, call in self._calls.items():
            if call["state"] not in (CallState.ENDED, CallState.FAILED):
                if {call["caller_sid"], call["callee_sid"]} == {sid1, sid2}:
                    return call_id, call
        return None, None

    def end_call(self, call_id, reason="normal"):
        """End a call."""
        call = self._calls.get(call_id)
        if not call:
            return
        target_state = CallState.ENDED if reason == "normal" else CallState.FAILED
        self._transition(call_id, target_state)

    def accept_call(self, call_id):
        """Accept a ringing call."""
        return self._transition(call_id, CallState.ACCEPTED)

    def call_connecting(self, call_id):
        """Mark call as in ICE negotiation."""
        return self._transition(call_id, CallState.CONNECTING)

    def call_connected(self, call_id):
        """Mark call as connected (media flowing)."""
        return self._transition(call_id, CallState.CONNECTED)

    def call_reconnecting(self, call_id):
        """Mark call as reconnecting (ICE restart)."""
        return self._transition(call_id, CallState.RECONNECTING)

    def record_ice_candidate(self, call_id, sid, candidate_data):
        """Record ICE candidate info for diagnostics."""
        call = self._calls.get(call_id)
        if not call:
            return
        role = "caller" if sid == call["caller_sid"] else "callee"
        ice = call["ice_info"][role]
        ice["candidates"] += 1
        # Extract candidate type from SDP
        if candidate_data and isinstance(candidate_data, dict):
            cand_str = candidate_data.get("candidate", "")
            if "relay" in cand_str:
                ice["type"] = "relay"
            elif "srflx" in cand_str:
                ice["type"] = ice["type"] or "srflx"
            elif "host" in cand_str:
                ice["type"] = ice["type"] or "host"
            # Extract transport
            if " UDP " in cand_str.upper() or " udp " in cand_str:
                ice["transport"] = "UDP"
            elif " TCP " in cand_str.upper() or " tcp " in cand_str:
                ice["transport"] = ice["transport"] or "TCP"

    # ═══════════════════════════════════════════════════════════════════════
    # ACK/Retry + Message Ordering + Dedup
    # ═══════════════════════════════════════════════════════════════════════

    def send_reliable(self, event, data, target_sid, sender_sid=None):
        """Send a signaling message with ACK/Retry guarantee.

        Returns msg_id for tracking.
        """
        msg_id = str(uuid.uuid4())[:10]
        seq = 0
        if sender_sid:
            key = (sender_sid, target_sid)
            self._msg_sequence[key] += 1
            seq = self._msg_sequence[key]

        envelope = {
            **data,
            "_msg_id": msg_id,
            "_seq": seq,
            "_ts": time.time(),
        }

        if event in ACK_REQUIRED:
            self._pending_acks[msg_id] = {
                "event": event,
                "data": envelope,
                "target": target_sid,
                "retries": 0,
                "sent_at": time.time(),
            }

        self.sio.emit(event, envelope, room=target_sid)
        return msg_id

    def handle_ack(self, msg_id):
        """Process ACK from client - stop retrying."""
        self._pending_acks.pop(msg_id, None)

    def is_duplicate(self, msg_id):
        """Check if we already processed this message."""
        if msg_id in self._seen_messages:
            return True
        self._seen_messages[msg_id] = time.time()
        return False

    def _retry_pending(self):
        """Retry unacknowledged messages."""
        now = time.time()
        expired = []
        for msg_id, info in list(self._pending_acks.items()):
            elapsed = now - info["sent_at"]
            if elapsed > MSG_TTL_S:
                expired.append(msg_id)
                continue
            retry_idx = info["retries"]
            if retry_idx >= MAX_RETRIES:
                expired.append(msg_id)
                logger.debug(f"Message {msg_id} dropped after {MAX_RETRIES} retries")
                continue
            delay_s = RETRY_DELAY_MS[min(retry_idx, len(RETRY_DELAY_MS) - 1)] / 1000.0
            if elapsed > delay_s * (retry_idx + 1):
                info["retries"] += 1
                self.sio.emit(info["event"], info["data"], room=info["target"])
                logger.debug(f"Retry {info['retries']}/{MAX_RETRIES} for {msg_id}")
        for m in expired:
            self._pending_acks.pop(m, None)

    # ═══════════════════════════════════════════════════════════════════════
    # Session Recovery + Heartbeat
    # ═══════════════════════════════════════════════════════════════════════

    def register_session(self, username, sid):
        """Register or recover a user session."""
        now = time.time()

        # Check for session recovery
        if username in self._disconnected:
            disc = self._disconnected.pop(username)
            if now - disc["disconnected_at"] < SESSION_RECOVERY_WINDOW_S:
                logger.info(f"Session recovered for {username} (old={disc['old_sid'][:6]}, new={sid[:6]})")
                # Deliver pending messages
                for msg in disc.get("pending_messages", []):
                    self.sio.emit(msg["event"], msg["data"], room=sid)
                # Update call references
                for call_id, call in self._calls.items():
                    if call["caller_sid"] == disc["old_sid"]:
                        call["caller_sid"] = sid
                    if call["callee_sid"] == disc["old_sid"]:
                        call["callee_sid"] = sid

        self._sessions[username] = {
            "sid": sid,
            "connected_at": now,
            "last_heartbeat": now,
        }

    def handle_heartbeat(self, username):
        """Update heartbeat timestamp."""
        if username in self._sessions:
            self._sessions[username]["last_heartbeat"] = time.time()

    def handle_disconnect(self, sid, username=None):
        """Handle user disconnect - buffer for potential recovery."""
        # Room cleanup
        self._remove(sid)

        if username:
            session = self._sessions.pop(username, None)
            if session:
                # Buffer for recovery
                self._disconnected[username] = {
                    "old_sid": sid,
                    "disconnected_at": time.time(),
                    "pending_messages": [],
                }
                logger.info(f"Session buffered for recovery: {username}")

    def queue_for_recovery(self, username, event, data):
        """Queue a message for a disconnected user's potential recovery."""
        if username in self._disconnected:
            self._disconnected[username].setdefault("pending_messages", []).append({
                "event": event,
                "data": data,
            })

    # ═══════════════════════════════════════════════════════════════════════
    # Room Management (Group Calls)
    # ═══════════════════════════════════════════════════════════════════════

    def join_room(self, room_id, username, sid):
        """Add a user to a signaling room."""
        with self._lock:
            if room_id not in self.rooms:
                self.rooms[room_id] = {"users": [], "created": datetime.utcnow().isoformat()}
            room = self.rooms[room_id]
            if not any(u["sid"] == sid for u in room["users"]):
                room["users"].append({"sid": sid, "username": username})
            self.user_rooms[sid] = room_id

    def leave_room(self, room_id, sid):
        """Remove a user from a signaling room."""
        with self._lock:
            self.user_rooms.pop(sid, None)
            if room_id in self.rooms:
                room = self.rooms[room_id]
                room["users"] = [u for u in room["users"] if u["sid"] != sid]
                if not room["users"]:
                    del self.rooms[room_id]

    def get_room_users(self, room_id):
        """Get list of users in a signaling room."""
        with self._lock:
            room = self.rooms.get(room_id)
            if room:
                return [{"sid": u["sid"], "username": u["username"]} for u in room["users"]]
            return []

    def _remove(self, sid):
        with self._lock:
            room_id = self.user_rooms.pop(sid, None)
            if room_id and room_id in self.rooms:
                room = self.rooms[room_id]
                room["users"] = [u for u in room["users"] if u["sid"] != sid]
                self.sio.leave_room(sid, room_id)
                if not room["users"]:
                    del self.rooms[room_id]

    # ═══════════════════════════════════════════════════════════════════════
    # Diagnostics & Logging
    # ═══════════════════════════════════════════════════════════════════════

    def _log_call(self, call):
        """Log completed call for diagnostics."""
        history = call.get("state_history", [])
        duration = 0
        if len(history) >= 2:
            duration = history[-1][1] - history[0][1]
        log_entry = {
            "call_id": call["call_id"],
            "call_type": call["call_type"],
            "final_state": call["state"].value,
            "duration_s": round(duration, 2),
            "ice_info": call["ice_info"],
            "state_history": [(s, round(t, 2)) for s, t in history],
            "timestamp": datetime.utcnow().isoformat(),
        }
        self._call_logs.append(log_entry)
        if len(self._call_logs) > self._max_logs:
            self._call_logs = self._call_logs[-self._max_logs:]
        logger.info(f"Call log: {call['call_id']} type={call['call_type']} "
                     f"state={call['state'].value} duration={duration:.1f}s "
                     f"ice_caller={call['ice_info']['caller']} "
                     f"ice_callee={call['ice_info']['callee']}")

    def get_call_logs(self, limit=50):
        """Get recent call logs for diagnostics."""
        return self._call_logs[-limit:]

    def get_active_calls(self):
        """Get list of active calls."""
        active = []
        for call_id, call in self._calls.items():
            if call["state"] not in (CallState.ENDED, CallState.FAILED, CallState.IDLE):
                active.append({
                    "call_id": call_id,
                    "call_type": call["call_type"],
                    "state": call["state"].value,
                    "ice_info": call["ice_info"],
                })
        return active

    def get_stats(self):
        return {
            "active_rooms": len(self.rooms),
            "total_users": sum(len(r["users"]) for r in self.rooms.values()),
            "active_calls": len(self.get_active_calls()),
            "pending_acks": len(self._pending_acks),
            "sessions": len(self._sessions),
            "buffered_disconnects": len(self._disconnected),
            "call_logs_count": len(self._call_logs),
        }

    # ═══════════════════════════════════════════════════════════════════════
    # Socket.IO Handlers
    # ═══════════════════════════════════════════════════════════════════════

    def _setup_handlers(self):
        sio = self.sio

        @sio.on("signal_ack")
        def on_ack(data):
            """Client acknowledges receipt of a signaling message."""
            msg_id = data.get("msg_id")
            if msg_id:
                self.handle_ack(msg_id)

        @sio.on("heartbeat")
        def on_heartbeat(data):
            """Client heartbeat for session liveness."""
            from flask import request
            username = data.get("username")
            if username:
                self.handle_heartbeat(username)
                self.sio.emit("heartbeat_ack", {
                    "ts": time.time(),
                }, room=request.sid)

        @sio.on("ice_state_report")
        def on_ice_report(data):
            """Client reports ICE connection state for diagnostics."""
            call_id = data.get("call_id")
            if not call_id:
                return
            state = data.get("state")  # checking, connected, failed, disconnected
            if state == "connected":
                self.call_connected(call_id)
            elif state == "failed":
                self.end_call(call_id, reason="ice_failed")
            elif state == "disconnected":
                self.call_reconnecting(call_id)
            # Record connection type
            call = self._calls.get(call_id)
            if call:
                from flask import request
                role = "caller" if request.sid == call["caller_sid"] else "callee"
                if data.get("connection_type"):
                    call["ice_info"][role]["type"] = data["connection_type"]
                if data.get("transport"):
                    call["ice_info"][role]["transport"] = data["transport"]

        @sio.on("ice_restart_request")
        def on_ice_restart(data):
            """Client requests ICE restart."""
            call_id = data.get("call_id")
            target = data.get("target")
            if call_id and target:
                self.call_reconnecting(call_id)
                from flask import request
                self.sio.emit("ice_restart", {
                    "call_id": call_id,
                    "sender": request.sid,
                }, room=target)

        @sio.on("join_room")
        def on_join(data):
            from flask import request
            sid = request.sid
            room_id = data.get("room_id")
            username = data.get("username", sid[:6])
            self.join_room(room_id, username, sid)
            sio.enter_room(sid, room_id)
            users = self.get_room_users(room_id)
            sio.emit("room_users", {
                "room_id": room_id,
                "users": [u for u in users if u["sid"] != sid],
            }, room=sid)

        @sio.on("leave_room")
        def on_leave(data):
            from flask import request
            self._remove(request.sid)

    # ═══════════════════════════════════════════════════════════════════════
    # Background Cleanup
    # ═══════════════════════════════════════════════════════════════════════

    def _cleanup_loop(self):
        """Periodic cleanup of stale data."""
        while True:
            try:
                try:
                    import eventlet
                    eventlet.sleep(5)
                except ImportError:
                    import gevent
                    gevent.sleep(5)
            except Exception:
                time.sleep(5)

            now = time.time()

            # Retry pending ACKs
            try:
                self._retry_pending()
            except Exception as e:
                logger.debug(f"Retry error: {e}")

            # Clean expired seen messages (dedup)
            expired = [m for m, ts in self._seen_messages.items() if now - ts > MSG_TTL_S * 2]
            for m in expired:
                self._seen_messages.pop(m, None)

            # Clean expired disconnect buffers
            expired_disc = [u for u, d in self._disconnected.items()
                           if now - d["disconnected_at"] > SESSION_RECOVERY_WINDOW_S]
            for u in expired_disc:
                self._disconnected.pop(u, None)
                logger.debug(f"Session recovery expired for {u}")

            # Clean stale calls (ended/failed older than 5min)
            stale = [cid for cid, c in self._calls.items()
                     if c["state"] in (CallState.ENDED, CallState.FAILED)
                     and now - c["state_history"][-1][1] > 300]
            for cid in stale:
                self._calls.pop(cid, None)
