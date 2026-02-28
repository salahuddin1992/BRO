"""
WebRTC Signaling - Simple offer/answer/ICE exchange
"""
import logging
from datetime import datetime

logger = logging.getLogger("BRO.signaling")


class SignalingServer:
    def __init__(self, sio):
        self.sio = sio
        self.rooms = {}       # {room_id: {users: [], created}}
        self.user_rooms = {}  # {sid: room_id}

        @sio.on("join_room")
        def on_join(data):
            from flask import request
            sid = request.sid
            room_id = data.get("room_id")
            username = data.get("username", sid[:6])

            if room_id not in self.rooms:
                self.rooms[room_id] = {"users": [], "created": datetime.utcnow().isoformat()}

            room = self.rooms[room_id]
            if not any(u["sid"] == sid for u in room["users"]):
                room["users"].append({"sid": sid, "username": username})
            self.user_rooms[sid] = room_id
            sio.enter_room(sid, room_id)

            sio.emit("room_users", {
                "room_id": room_id,
                "users": [{"sid": u["sid"], "username": u["username"]}
                          for u in room["users"] if u["sid"] != sid],
            }, room=sid)

        @sio.on("leave_room")
        def on_leave(data):
            from flask import request
            self._remove(request.sid)

    def handle_disconnect(self, sid):
        self._remove(sid)

    def _remove(self, sid):
        room_id = self.user_rooms.pop(sid, None)
        if room_id and room_id in self.rooms:
            room = self.rooms[room_id]
            room["users"] = [u for u in room["users"] if u["sid"] != sid]
            self.sio.leave_room(sid, room_id)
            if not room["users"]:
                del self.rooms[room_id]

    def get_stats(self):
        return {
            "active_rooms": len(self.rooms),
            "total_users": sum(len(r["users"]) for r in self.rooms.values()),
        }
