"""
WebRTC Signaling Server
Handles WebRTC offer/answer/ICE candidate exchange for
voice calls, video calls, and data channels.
"""
import logging
from datetime import datetime

logger = logging.getLogger("BRO.signaling")


class SignalingServer:
    """
    Manages WebRTC signaling for peer-to-peer connections.
    Handles rooms, offers, answers, and ICE candidates.
    """

    def __init__(self, socketio):
        self.sio = socketio
        self.rooms = {}  # {room_id: {users: [], created: ..., type: ...}}
        self.user_rooms = {}  # {sid: room_id}
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
            user_info = {
                "sid": sid,
                "username": username,
                "joined": datetime.utcnow().isoformat(),
            }
            room["users"].append(user_info)
            self.user_rooms[sid] = room_id

            self.sio.enter_room(sid, room_id)

            # Notify others in the room
            self.sio.emit("user_joined", {
                "sid": sid,
                "username": username,
                "users": [u["username"] for u in room["users"]],
            }, room=room_id, skip_sid=sid)

            # Send existing users to the new user
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
            sid = request.sid
            self._remove_user(sid)

        @self.sio.on("webrtc_offer")
        def on_offer(data):
            """Forward WebRTC offer to target peer."""
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
            """Forward WebRTC answer to target peer."""
            from flask import request
            target_sid = data.get("target")
            self.sio.emit("webrtc_answer", {
                "sdp": data.get("sdp"),
                "type": data.get("type", "answer"),
                "sender": request.sid,
            }, room=target_sid)

        @self.sio.on("webrtc_ice")
        def on_ice(data):
            """Forward ICE candidate to target peer."""
            from flask import request
            target_sid = data.get("target")
            self.sio.emit("webrtc_ice", {
                "candidate": data.get("candidate"),
                "sender": request.sid,
            }, room=target_sid)

        @self.sio.on("call_request")
        def on_call_request(data):
            """Handle call request (voice/video)."""
            from flask import request
            target_sid = data.get("target")
            self.sio.emit("incoming_call", {
                "sender": request.sid,
                "sender_name": data.get("sender_name", "Unknown"),
                "call_type": data.get("call_type", "video"),
                "room_id": data.get("room_id"),
            }, room=target_sid)

        @self.sio.on("call_accept")
        def on_call_accept(data):
            """Handle call acceptance."""
            from flask import request
            target_sid = data.get("target")
            self.sio.emit("call_accepted", {
                "sender": request.sid,
                "room_id": data.get("room_id"),
            }, room=target_sid)

        @self.sio.on("call_reject")
        def on_call_reject(data):
            """Handle call rejection."""
            from flask import request
            target_sid = data.get("target")
            self.sio.emit("call_rejected", {
                "sender": request.sid,
            }, room=target_sid)

        @self.sio.on("call_end")
        def on_call_end(data):
            """Handle call ending."""
            from flask import request
            room_id = data.get("room_id")
            self.sio.emit("call_ended", {
                "sender": request.sid,
            }, room=room_id, skip_sid=request.sid)

        @self.sio.on("disconnect")
        def on_disconnect():
            from flask import request
            self._remove_user(request.sid)

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
        """Return list of active rooms."""
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
        """Return signaling statistics."""
        total_users = sum(len(r["users"]) for r in self.rooms.values())
        return {
            "active_rooms": len(self.rooms),
            "total_users": total_users,
            "rooms": self.get_active_rooms(),
        }
