"""
WebRTC Signaling Server - Full Featured
=========================================
Handles WebRTC offer/answer/ICE candidate exchange for:
  - Voice calls (audio only)
  - Video calls (up to 4K@60fps)
  - Screen sharing
  - Data channels
  - ICE restart for reconnection
  - Connection quality monitoring
  - Multi-party support
"""
import logging
from datetime import datetime

logger = logging.getLogger("BRO.signaling")


class SignalingServer:
    """
    Manages WebRTC signaling for peer-to-peer connections.
    Supports rooms, offers, answers, ICE candidates, screen sharing,
    ICE restart, and connection quality reporting.
    """

    def __init__(self, socketio):
        self.sio = socketio
        self.rooms = {}  # {room_id: {users: [], created, type}}
        self.user_rooms = {}  # {sid: room_id}
        self.active_calls = {}  # {sid: {target, type, started_at, quality}}
        self.screen_shares = {}  # {sid: {room_id, started_at}}
        self._register_handlers()

    def _register_handlers(self):
        """Register all WebRTC signaling socket events."""

        @self.sio.on("join_room")
        def on_join_room(data):
            from flask import request
            sid = request.sid
            room_id = data.get("room_id")
            username = data.get("username", f"User-{sid[:6]}")

            if room_id not in self.rooms:
                self.rooms[room_id] = {
                    "users": [],
                    "created": datetime.utcnow().isoformat(),
                    "type": data.get("type", "general"),
                }

            room = self.rooms[room_id]
            # Prevent duplicate joins
            if not any(u["sid"] == sid for u in room["users"]):
                user_info = {
                    "sid": sid,
                    "username": username,
                    "joined": datetime.utcnow().isoformat(),
                }
                room["users"].append(user_info)
            self.user_rooms[sid] = room_id
            self.sio.enter_room(sid, room_id)

            # Notify others
            self.sio.emit("user_joined_room", {
                "sid": sid,
                "username": username,
                "users": [u["username"] for u in room["users"]],
            }, room=room_id, skip_sid=sid)

            # Send existing users to new user
            self.sio.emit("room_users", {
                "room_id": room_id,
                "users": [
                    {"sid": u["sid"], "username": u["username"]}
                    for u in room["users"] if u["sid"] != sid
                ],
            }, room=sid)

            logger.info(f"User {username} joined room {room_id}")

        @self.sio.on("leave_room")
        def on_leave_room(data):
            from flask import request
            self._remove_user(request.sid)

        @self.sio.on("webrtc_offer")
        def on_offer(data):
            from flask import request
            target_sid = data.get("target")
            self.sio.emit("webrtc_offer", {
                "sdp": data.get("sdp"),
                "type": data.get("type", "offer"),
                "sender": request.sid,
                "call_type": data.get("call_type", "video"),
            }, room=target_sid)

        @self.sio.on("webrtc_answer")
        def on_answer(data):
            from flask import request
            target_sid = data.get("target")
            self.sio.emit("webrtc_answer", {
                "sdp": data.get("sdp"),
                "type": data.get("type", "answer"),
                "sender": request.sid,
            }, room=target_sid)

        @self.sio.on("webrtc_ice")
        def on_ice(data):
            from flask import request
            target_sid = data.get("target")
            self.sio.emit("webrtc_ice", {
                "candidate": data.get("candidate"),
                "sender": request.sid,
            }, room=target_sid)

        @self.sio.on("ice_restart")
        def on_ice_restart(data):
            """Handle ICE restart request for reconnection."""
            from flask import request
            target_sid = data.get("target")
            logger.info(f"ICE restart requested: {request.sid} -> {target_sid}")
            self.sio.emit("ice_restart", {
                "sender": request.sid,
                "sdp": data.get("sdp"),
                "type": data.get("type", "offer"),
            }, room=target_sid)

        @self.sio.on("call_request")
        def on_call_request(data):
            from flask import request
            target_sid = data.get("target")
            call_type = data.get("call_type", "video")
            # Track active call
            self.active_calls[request.sid] = {
                "target": target_sid,
                "type": call_type,
                "started_at": datetime.utcnow().isoformat(),
            }
            self.sio.emit("incoming_call", {
                "sender": request.sid,
                "sender_name": data.get("sender_name", "Unknown"),
                "call_type": call_type,
                "room_id": data.get("room_id"),
            }, room=target_sid)

        @self.sio.on("call_accept")
        def on_call_accept(data):
            from flask import request
            target_sid = data.get("target")
            self.active_calls[request.sid] = {
                "target": target_sid,
                "type": "accepted",
                "started_at": datetime.utcnow().isoformat(),
            }
            self.sio.emit("call_accepted", {
                "sender": request.sid,
                "room_id": data.get("room_id"),
            }, room=target_sid)

        @self.sio.on("call_reject")
        def on_call_reject(data):
            from flask import request
            target_sid = data.get("target")
            self.active_calls.pop(request.sid, None)
            self.sio.emit("call_rejected", {
                "sender": request.sid,
            }, room=target_sid)

        @self.sio.on("call_end")
        def on_call_end(data):
            from flask import request
            target_sid = data.get("target")
            self.active_calls.pop(request.sid, None)
            # Stop screen share if active
            self.screen_shares.pop(request.sid, None)
            if target_sid:
                self.active_calls.pop(target_sid, None)
                self.screen_shares.pop(target_sid, None)
                self.sio.emit("call_ended", {
                    "sender": request.sid,
                }, room=target_sid)
            else:
                self.sio.emit("call_ended", {
                    "sender": request.sid,
                }, broadcast=True, skip_sid=request.sid)

        @self.sio.on("screen_share_start")
        def on_screen_share_start(data):
            """Handle screen sharing start."""
            from flask import request
            target_sid = data.get("target")
            self.screen_shares[request.sid] = {
                "target": target_sid,
                "started_at": datetime.utcnow().isoformat(),
            }
            self.sio.emit("screen_share_started", {
                "sender": request.sid,
                "sdp": data.get("sdp"),
                "type": data.get("type", "offer"),
            }, room=target_sid)
            logger.info(f"Screen share started: {request.sid}")

        @self.sio.on("screen_share_stop")
        def on_screen_share_stop(data):
            """Handle screen sharing stop."""
            from flask import request
            target_sid = data.get("target")
            self.screen_shares.pop(request.sid, None)
            if target_sid:
                self.sio.emit("screen_share_stopped", {
                    "sender": request.sid,
                }, room=target_sid)

        @self.sio.on("connection_quality")
        def on_connection_quality(data):
            """Receive connection quality report from client."""
            from flask import request
            sid = request.sid
            if sid in self.active_calls:
                self.active_calls[sid]["quality"] = {
                    "rtt": data.get("rtt"),
                    "packet_loss": data.get("packet_loss"),
                    "bitrate": data.get("bitrate"),
                    "resolution": data.get("resolution"),
                    "framerate": data.get("framerate"),
                    "updated_at": datetime.utcnow().isoformat(),
                }

        @self.sio.on("webrtc_renegotiate")
        def on_renegotiate(data):
            """Handle renegotiation (e.g., adding/removing tracks)."""
            from flask import request
            target_sid = data.get("target")
            self.sio.emit("webrtc_renegotiate", {
                "sdp": data.get("sdp"),
                "type": data.get("type"),
                "sender": request.sid,
                "reason": data.get("reason", "track_change"),
            }, room=target_sid)

    def handle_disconnect(self, sid):
        """Called externally from bro_server on disconnect."""
        self._remove_user(sid)
        # End any active calls
        call = self.active_calls.pop(sid, None)
        if call and call.get("target"):
            self.sio.emit("call_ended", {"sender": sid}, room=call["target"])
            self.active_calls.pop(call["target"], None)
        # Stop screen shares
        share = self.screen_shares.pop(sid, None)
        if share and share.get("target"):
            self.sio.emit("screen_share_stopped", {"sender": sid}, room=share["target"])

    def _remove_user(self, sid):
        """Remove user from their room."""
        room_id = self.user_rooms.pop(sid, None)
        if room_id and room_id in self.rooms:
            room = self.rooms[room_id]
            room["users"] = [u for u in room["users"] if u["sid"] != sid]
            self.sio.leave_room(sid, room_id)
            self.sio.emit("user_left", {"sid": sid}, room=room_id)
            if not room["users"]:
                del self.rooms[room_id]

    def get_active_rooms(self):
        return {
            rid: {
                "user_count": len(r["users"]),
                "users": [u["username"] for u in r["users"]],
                "type": r["type"],
                "created": r["created"],
            }
            for rid, r in self.rooms.items()
        }

    def get_stats(self):
        total_users = sum(len(r["users"]) for r in self.rooms.values())
        return {
            "active_rooms": len(self.rooms),
            "total_users": total_users,
            "active_calls": len(self.active_calls),
            "screen_shares": len(self.screen_shares),
            "rooms": self.get_active_rooms(),
        }
