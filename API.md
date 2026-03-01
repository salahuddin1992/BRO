# Helen WiFi (BRO) - API Documentation

Complete reference for all REST API endpoints and Socket.IO events.

**Base URL:** `http://<server-ip>:<port>`
**Default Port:** 7777
**Protocol:** HTTP + WebSocket (Socket.IO)

---

## Table of Contents

- [Authentication](#authentication)
- [REST API Endpoints](#rest-api-endpoints)
  - [Pages](#pages)
  - [Admin Authentication](#admin-authentication)
  - [Admin API - Statistics](#admin-api---statistics)
  - [Admin API - User Management](#admin-api---user-management)
  - [Admin API - Role Management](#admin-api---role-management)
  - [Admin API - Room Management](#admin-api---room-management)
  - [Admin API - Message Management](#admin-api---message-management)
  - [Admin API - File Management](#admin-api---file-management)
  - [Admin API - Password Management](#admin-api---password-management)
  - [Admin API - Backup & Restore](#admin-api---backup--restore)
  - [Admin API - Recordings](#admin-api---recordings)
  - [Admin API - Settings](#admin-api---settings)
  - [File Upload & Download](#file-upload--download)
  - [Configuration](#configuration)
  - [Mesh Network API](#mesh-network-api)
- [Socket.IO Events](#socketio-events)
  - [Connection Events](#connection-events)
  - [Authentication Events](#authentication-events)
  - [Room Events](#room-events)
  - [Status & Typing Events](#status--typing-events)
  - [Chat Message Events](#chat-message-events)
  - [Profile Events](#profile-events)
  - [E2E Encryption Events](#e2e-encryption-events)
  - [Screen Share Events](#screen-share-events)
  - [Voice/Video Call Events](#voicevideo-call-events)
  - [WebRTC Signaling Events](#webrtc-signaling-events)
- [Server-Emitted Events](#server-emitted-events)
- [Data Models](#data-models)
- [Error Handling](#error-handling)
- [Rate Limiting](#rate-limiting)

---

## Authentication

### Admin Panel
- Admin routes require Flask session authentication (`session["admin"] = True`)
- Login via `POST /login` with admin credentials
- All `/api/admin/*` endpoints require admin session

### Client Users
- Socket.IO authentication via `auth_register` / `auth_login` / `auth_token` events
- Successful auth returns a token for session resumption
- File downloads require authenticated username query param (`?u=<username>`)

### Mesh Network
- Inter-server APIs require `X-Mesh-Secret` header matching `config.SECRET_KEY`

---

## REST API Endpoints

### Pages

#### `GET /`
Redirects to `/client`.

#### `GET /client`
Renders the main client chat interface.

- **Response:** HTML page

#### `GET /admin`
Renders the admin control panel (requires admin session).

- **Auth:** Admin session required
- **Response:** HTML page

---

### Admin Authentication

#### `GET /login`
Renders admin login page.

- **Response:** HTML login form

#### `POST /login`
Authenticate as admin.

- **Content-Type:** `application/x-www-form-urlencoded`
- **Body:**
  | Field | Type | Description |
  |-------|------|-------------|
  | `username` | string | Admin username |
  | `password` | string | Admin password |
- **Success:** Redirect to `/admin` (sets session)
- **Failure:** Re-renders login page with error
- **Rate Limit:** Yes (per IP)

#### `GET /logout`
Clears admin session and redirects to login.

---

### Admin API - Statistics

#### `GET /api/admin/stats`
Returns comprehensive server statistics.

- **Auth:** Admin session required
- **Response:**
```json
{
  "server_id": "abc123def456",
  "uptime": 3600,
  "host_ip": "192.168.1.100",
  "port": 7777,
  "is_fiber": false,
  "clients_count": 5,
  "clients": [{"sid": "...", "username": "user1", "ip": "...", "status": "online"}],
  "messages_count": 150,
  "messages": [...],
  "files_count": 10,
  "files": [...],
  "registered_users": 20,
  "users": [...],
  "banned_users": [...],
  "rooms": [...],
  "recordings_count": 3,
  "recordings": [...],
  "network": {"interfaces": [...]},
  "mesh": {"peers": [...], "active_rooms": 0, "total_users": 0},
  "logs": [{"time": "...", "level": "info", "message": "..."}]
}
```

---

### Admin API - User Management

#### `POST /api/admin/users/<username>/ban`
Ban a user. Disconnects active sessions and invalidates tokens.

- **Auth:** Admin session required
- **Response:** `{"status": "ok"}`

#### `POST /api/admin/users/<username>/unban`
Unban a previously banned user.

- **Auth:** Admin session required
- **Response:** `{"status": "ok"}`

#### `POST /api/admin/users/<username>/kick`
Force disconnect a user's active session.

- **Auth:** Admin session required
- **Response:** `{"status": "ok"}`

#### `DELETE /api/admin/users/<username>/delete`
Permanently delete a user account.

- **Auth:** Admin session required
- **Response:** `{"status": "ok"}`

#### `POST /api/admin/users/<username>/reset-password`
Reset a user's password.

- **Auth:** Admin session required
- **Body (JSON):**
  | Field | Type | Description |
  |-------|------|-------------|
  | `new_password` | string | New password (min 4 chars) |
- **Response:** `{"status": "ok"}`
- **Error:** `{"error": "كلمة المرور قصيرة"}` (400)

---

### Admin API - Role Management

#### `POST /api/admin/users/<username>/role`
Set a user's role.

- **Auth:** Admin session required
- **Body (JSON):**
  | Field | Type | Description |
  |-------|------|-------------|
  | `role` | string | One of: `"user"`, `"moderator"`, `"admin"` |
- **Response:** `{"status": "ok", "role": "moderator"}`
- **Side Effect:** Emits `role_changed` Socket.IO event to the target user

---

### Admin API - Room Management

#### `DELETE /api/admin/rooms/<room_id>`
Delete a room and its associated files.

- **Auth:** Admin session required
- **Response:** `{"status": "ok"}`
- **Error:** `{"error": "Room not found"}` (404)

---

### Admin API - Message Management

#### `DELETE /api/admin/messages/<msg_id>`
Delete a specific message by ID.

- **Auth:** Admin session required
- **Response:** `{"status": "ok"}`

#### `DELETE /api/admin/messages/by-user/<username>`
Delete all messages sent by a specific user.

- **Auth:** Admin session required
- **Response:** `{"status": "ok", "deleted": 15}`

---

### Admin API - File Management

#### `DELETE /api/admin/files/<file_id>`
Delete a file record and remove the file from disk.

- **Auth:** Admin session required
- **Response:** `{"status": "ok"}`
- **Error:** `{"error": "File not found"}` (404)

---

### Admin API - Password Management

#### `POST /api/admin/change-password`
Change the admin panel password.

- **Auth:** Admin session required
- **Body (JSON):**
  | Field | Type | Description |
  |-------|------|-------------|
  | `old_password` | string | Current admin password |
  | `new_password` | string | New admin password (min 6 chars) |
  | `confirm_password` | string | Must match `new_password` |
- **Response:** `{"status": "ok"}`
- **Error:** `{"error": "..."}` (400)

---

### Admin API - Backup & Restore

#### `POST /api/admin/backup`
Create a database backup.

- **Auth:** Admin session required
- **Body (JSON):**
  | Field | Type | Description |
  |-------|------|-------------|
  | `description` | string | Optional description |
- **Response:** `{"status": "ok", "backup_id": 1}`

#### `GET /api/admin/backups`
List all backups.

- **Auth:** Admin session required
- **Response:** `{"backups": [{"id": 1, "filename": "...", "description": "...", "created_at": "...", "size": 1024}]}`

#### `POST /api/admin/restore`
Restore database from a backup file.

- **Auth:** Admin session required
- **Body (JSON):**
  | Field | Type | Description |
  |-------|------|-------------|
  | `backup_id` | int | ID of the backup to restore |
- **Response:** `{"status": "ok"}`
- **Error:** `{"error": "Backup not found"}` (404)

#### `DELETE /api/admin/backups/<backup_id>`
Delete a backup record and file.

- **Auth:** Admin session required
- **Response:** `{"status": "ok"}`

#### `GET /api/admin/backup/download/<filename>`
Download a backup file.

- **Auth:** Admin session required
- **Response:** File download

---

### Admin API - Recordings

#### `GET /api/admin/recordings`
List all call recordings.

- **Auth:** Admin session required
- **Response:** `{"recordings": [{"id": 1, "caller": "...", "callee": "...", "call_type": "video", "filename": "...", "size": 1024, "duration": 120}]}`

#### `DELETE /api/admin/recordings/<rec_id>`
Delete a recording and remove file from disk.

- **Auth:** Admin session required
- **Response:** `{"status": "ok"}`

---

### Admin API - Settings

#### `GET /api/admin/settings`
Retrieve all server settings.

- **Auth:** Admin session required
- **Response:** `{"settings": {"key": "value", ...}}`

#### `POST /api/admin/settings`
Save/update server settings.

- **Auth:** Admin session required
- **Body (JSON):** Key-value pairs of settings
- **Response:** `{"status": "ok"}`

---

### File Upload & Download

#### `POST /api/upload`
Upload a shared file.

- **Auth:** Authenticated user (via Socket.IO session token)
- **Content-Type:** `multipart/form-data`
- **Body:**
  | Field | Type | Description |
  |-------|------|-------------|
  | `file` | file | The file to upload |
  | `room_id` | int | Optional - room to share in |
  | `target_user` | string | Optional - DM recipient |
- **Max Size:** 100 MB
- **Allowed Extensions:** txt, pdf, png, jpg, jpeg, gif, bmp, webp, svg, mp3, mp4, wav, ogg, webm, avi, mkv, mov, doc, docx, xls, xlsx, ppt, pptx, odt, ods, zip, rar, 7z, tar, gz, csv, json, xml, html, css, js, py
- **Response:**
```json
{
  "status": "ok",
  "file": {
    "name": "photo.jpg",
    "saved_as": "1234567890_photo.jpg",
    "size": 51200,
    "uploaded_by": "username",
    "uploaded_at": "2025-01-01T00:00:00",
    "room_id": null,
    "target_user": null
  }
}
```
- **Side Effect:** Emits `file_shared` to relevant clients

#### `POST /api/upload-recording`
Upload a call recording.

- **Auth:** Authenticated user
- **Content-Type:** `multipart/form-data`
- **Body:**
  | Field | Type | Description |
  |-------|------|-------------|
  | `recording` | file | The recording file |
  | `callee` | string | Name of call partner |
  | `call_type` | string | `"audio"` or `"video"` |
  | `duration` | int | Call duration in seconds |
- **Response:** `{"status": "ok", "id": 1}`

#### `GET /api/download/<filename>`
Download a shared file.

- **Auth:** Admin session or authenticated user (`?u=<username>`)
- **Response:** File download (attachment)
- **Error:** `{"error": "..."}` (401/400/404)

#### `GET /api/recording/<filename>`
Download a call recording.

- **Auth:** Admin session or authenticated user (`?u=<username>`)
- **Response:** File download (attachment)

#### `GET /api/files`
List shared files.

- **Query Params:**
  | Param | Type | Description |
  |-------|------|-------------|
  | `room_id` | int | Optional - filter by room |
- **Response:** `{"files": [...]}`

---

### Configuration

#### `GET /api/ice-config`
Get WebRTC ICE server configuration.

- **Response:**
```json
{
  "iceServers": [
    {"urls": "stun:stun.l.google.com:19302"}
  ]
}
```

---

### Mesh Network API

All mesh endpoints require the `X-Mesh-Secret` header.

#### `GET /api/mesh/info`
Get server info for mesh peering.

- **Auth:** Mesh secret or admin session
- **Response:**
```json
{
  "server_id": "abc123def456",
  "host": "192.168.1.100",
  "port": 7777,
  "mesh_port": 7778
}
```

#### `POST /api/mesh/sync-users`
Receive user list from a peer server.

- **Auth:** Mesh secret
- **Body (JSON):**
  | Field | Type | Description |
  |-------|------|-------------|
  | `server_id` | string | Peer server ID |
  | `users` | array | List of user objects |
  | `host` | string | Peer host IP |
  | `port` | int | Peer port |
- **Response:** `{"status": "ok"}`

#### `POST /api/mesh/forward`
Forward a Socket.IO event to a specific local client.

- **Auth:** Mesh secret
- **Body (JSON):**
  | Field | Type | Description |
  |-------|------|-------------|
  | `event` | string | Event name |
  | `data` | object | Event payload (must contain `target` SID) |
- **Response:** `{"status": "ok"}`

#### `POST /api/mesh/broadcast`
Broadcast a Socket.IO event to all local clients.

- **Auth:** Mesh secret
- **Body (JSON):**
  | Field | Type | Description |
  |-------|------|-------------|
  | `event` | string | Event name |
  | `data` | object | Event payload |
- **Response:** `{"status": "ok"}`

---

## Socket.IO Events

### Connection Events

#### Client -> Server: `connect`
Automatic on connection. Server creates client record.

#### Server -> Client: `server_info`
Sent immediately after connection.

```json
{
  "server_id": "abc123def456",
  "ice_servers": [{"urls": "stun:stun.l.google.com:19302"}],
  "is_fiber": false
}
```

#### Client -> Server: `disconnect`
Automatic on disconnect. Server cleans up client state and broadcasts offline status.

---

### Authentication Events

#### Client -> Server: `auth_register`
Register a new user account.

```json
{
  "username": "user1",
  "password": "pass123"
}
```

**Validation:**
- Username: 2-30 chars, alphanumeric + Arabic + spaces + hyphens
- Password: min 4 chars
- Rate limited per IP

#### Client -> Server: `auth_login`
Login with existing credentials.

```json
{
  "username": "user1",
  "password": "pass123"
}
```

#### Server -> Client: `auth_result`
Response to register/login/token_auth.

```json
{
  "ok": true,
  "username": "user1",
  "rooms": [{"id": 1, "name": "General", "description": "..."}],
  "token": "abc123...",
  "role": "user"
}
```

On failure:
```json
{
  "ok": false,
  "error": "Error message",
  "token_expired": true
}
```

#### Client -> Server: `auth_token`
Resume session with saved token.

```json
{
  "token": "abc123..."
}
```

#### Client -> Server: `auth_logout`
Logout and invalidate token.

```json
{
  "token": "abc123..."
}
```

#### Server -> Client: `logged_out`
Confirms logout. Payload: `{}`

---

### Room Events

#### Client -> Server: `create_room`
Create a new chat room.

```json
{
  "name": "Room Name",
  "description": "Optional description"
}
```

#### Server -> Client: `room_created`
Broadcast to all clients when a room is created.

```json
{
  "id": 1,
  "name": "Room Name",
  "description": "Optional description"
}
```

#### Server -> Client: `room_error`
Room operation error.

```json
{
  "error": "Error message"
}
```

#### Client -> Server: `join_room_req`
Join an existing room.

```json
{
  "room_id": 1
}
```

#### Client -> Server: `leave_room_req`
Leave a room.

```json
{
  "room_id": 1
}
```

#### Server -> Client: `rooms_updated`
Sent after room join/leave/create.

```json
{
  "rooms": [{"id": 1, "name": "General", "description": "..."}]
}
```

#### Client -> Server: `get_room_history`
Get message history for a room.

```json
{
  "room_id": 1,
  "before_id": 50
}
```

#### Server -> Client: `room_history`
```json
{
  "room_id": 1,
  "messages": [...],
  "files": [...],
  "before_id": 50,
  "has_more": true
}
```

#### Client -> Server: `get_dm_history`
Get direct message history.

```json
{
  "username": "other_user",
  "before_id": 100
}
```

#### Server -> Client: `dm_history`
```json
{
  "username": "other_user",
  "messages": [...],
  "before_id": 100,
  "has_more": false
}
```

#### Client -> Server: `get_rooms_list`
Get all public rooms. No payload required.

#### Server -> Client: `all_rooms`
```json
{
  "rooms": [{"id": 1, "name": "...", "description": "...", "member_count": 5}]
}
```

---

### Status & Typing Events

#### Client -> Server: `set_status`
Update user status.

```json
{
  "status": "online"
}
```
Valid values: `"online"`, `"away"`, `"busy"`

#### Server -> Client (broadcast): `users_online`
Broadcast whenever user list changes.

```json
{
  "users": [
    {"sid": "...", "username": "user1", "status": "online"},
    {"sid": "...", "username": "user2", "status": "away"}
  ]
}
```

#### Client -> Server: `typing`
Notify that user started typing.

```json
{
  "target_sid": "sid123",
  "room_id": null
}
```
Send either `target_sid` (for DM) or `room_id` (for room chat).

#### Server -> Client: `user_typing`
```json
{
  "username": "user1",
  "room_id": null
}
```

#### Client -> Server: `stop_typing`
Notify that user stopped typing.

```json
{
  "target_sid": "sid123",
  "room_id": null
}
```

#### Server -> Client: `user_stop_typing`
```json
{
  "username": "user1",
  "room_id": null
}
```

---

### Chat Message Events

#### Client -> Server: `chat_message`
Send a message.

```json
{
  "text": "Hello world",
  "target_user": "user2",
  "room_id": null,
  "reply_to": null,
  "encrypted": false
}
```

| Field | Type | Description |
|-------|------|-------------|
| `text` | string | Message text (required) |
| `target_user` | string | DM recipient username (null for public/room) |
| `room_id` | int | Room ID (null for public/DM) |
| `reply_to` | int | Message ID being replied to (null if not a reply) |
| `encrypted` | bool | Whether the message is E2E encrypted |

**Routing:**
- `target_user` set: DM (sent to sender + recipient)
- `room_id` set: Room message (sent to all room members)
- Neither: Public broadcast (sent to all + mesh peers)

#### Server -> Client: `chat_message`
Received message.

```json
{
  "id": 42,
  "sender": "user1",
  "text": "Hello world",
  "target_user": "user2",
  "room_id": null,
  "reply_to": null,
  "encrypted": false,
  "timestamp": "2025-01-01T12:00:00",
  "reply_info": {
    "sender": "user2",
    "text": "Original message text..."
  }
}
```

#### Client -> Server: `delete_message`
Delete a message.

```json
{
  "id": 42
}
```

**Permissions:**
- Regular users: can only delete own messages
- Moderators/Admins: can delete any message

#### Server -> Client (broadcast): `message_deleted`
```json
{
  "id": 42
}
```

#### Client -> Server: `search_messages`
Search messages.

```json
{
  "query": "search term",
  "room_id": null
}
```

**Validation:** Query must be at least 2 characters.

#### Server -> Client: `search_results`
```json
{
  "query": "search term",
  "results": [{"id": 1, "sender": "...", "text": "...", "timestamp": "..."}]
}
```

---

### Profile Events

#### Client -> Server: `change_password`
Change user password.

```json
{
  "old_password": "oldpass",
  "new_password": "newpass"
}
```

#### Client -> Server: `update_display_name`
Update display name.

```json
{
  "display_name": "New Name"
}
```

#### Server -> Client: `profile_result`
```json
{
  "ok": true,
  "msg": "Success message"
}
```

On failure:
```json
{
  "ok": false,
  "error": "Error message"
}
```

---

### E2E Encryption Events

#### Client -> Server: `set_public_key`
Store user's public key for E2E encryption (ECDH P-256).

```json
{
  "public_key": "base64-encoded-jwk..."
}
```

#### Client -> Server: `get_public_key`
Retrieve another user's public key.

```json
{
  "username": "user2"
}
```

#### Server -> Client: `public_key_response`
```json
{
  "username": "user2",
  "public_key": "base64-encoded-jwk..."
}
```

---

### Screen Share Events

#### Client -> Server: `screen_share_start`
Notify target that screen sharing started.

```json
{
  "target": "target_sid",
  "sender_name": "user1"
}
```

#### Server -> Client: `screen_share_started`
```json
{
  "sender": "sender_sid",
  "sender_name": "user1"
}
```

#### Client -> Server: `screen_share_stop`
```json
{
  "target": "target_sid"
}
```

#### Server -> Client: `screen_share_stopped`
```json
{
  "sender": "sender_sid"
}
```

#### Client -> Server: `screen_offer`
WebRTC offer for screen share.

```json
{
  "target": "target_sid",
  "sdp": "...",
  "type": "offer"
}
```

#### Client -> Server: `screen_answer`
WebRTC answer for screen share.

```json
{
  "target": "target_sid",
  "sdp": "...",
  "type": "answer"
}
```

#### Client -> Server: `screen_ice`
ICE candidate for screen share.

```json
{
  "target": "target_sid",
  "candidate": {...}
}
```

---

### Voice/Video Call Events

#### Client -> Server: `call_request`
Initiate a call.

```json
{
  "target": "target_sid",
  "sender_name": "user1",
  "call_type": "video"
}
```
`call_type`: `"video"` or `"audio"`

#### Server -> Client: `incoming_call`
```json
{
  "sender": "sender_sid",
  "sender_name": "user1",
  "call_type": "video",
  "target": "target_sid"
}
```

#### Client -> Server: `call_accept`
```json
{
  "target": "caller_sid"
}
```

#### Server -> Client: `call_accepted`
```json
{
  "sender": "accepter_sid",
  "target": "caller_sid"
}
```

#### Client -> Server: `call_reject`
```json
{
  "target": "caller_sid"
}
```

#### Server -> Client: `call_rejected`
```json
{
  "sender": "rejecter_sid",
  "target": "caller_sid"
}
```

#### Client -> Server: `call_end`
```json
{
  "target": "other_sid"
}
```

#### Server -> Client: `call_ended`
```json
{
  "sender": "ender_sid",
  "target": "other_sid"
}
```

---

### WebRTC Signaling Events

#### Client -> Server: `webrtc_offer`
```json
{
  "target": "target_sid",
  "sdp": "v=0...",
  "type": "offer"
}
```

#### Client -> Server: `webrtc_answer`
```json
{
  "target": "target_sid",
  "sdp": "v=0...",
  "type": "answer"
}
```

#### Client -> Server: `webrtc_ice`
```json
{
  "target": "target_sid",
  "candidate": {
    "candidate": "candidate:...",
    "sdpMLineIndex": 0,
    "sdpMid": "0"
  }
}
```

---

## Server-Emitted Events

Summary of all events the server emits to clients:

| Event | Trigger | Target |
|-------|---------|--------|
| `server_info` | Client connects | Sender only |
| `auth_result` | Auth attempt | Sender only |
| `logged_out` | Logout | Sender only |
| `users_online` | User list changes | Broadcast |
| `user_offline` | User disconnects | Broadcast |
| `rooms_updated` | Room membership changes | Sender only |
| `room_created` | New room created | Broadcast |
| `room_error` | Room operation fails | Sender only |
| `all_rooms` | Rooms list requested | Sender only |
| `room_history` | Room history requested | Sender only |
| `dm_history` | DM history requested | Sender only |
| `chat_message` | Message sent | Targeted |
| `message_deleted` | Message deleted | Broadcast |
| `search_results` | Search performed | Sender only |
| `user_typing` | User starts typing | Targeted |
| `user_stop_typing` | User stops typing | Targeted |
| `profile_result` | Profile update | Sender only |
| `role_changed` | Admin changes role | Target user |
| `file_shared` | File uploaded | Targeted |
| `public_key_response` | Key requested | Sender only |
| `screen_share_started` | Screen share begins | Target user |
| `screen_share_stopped` | Screen share ends | Target user |
| `screen_offer` | Screen share SDP | Target user |
| `screen_answer` | Screen share SDP | Target user |
| `screen_ice` | Screen share ICE | Target user |
| `incoming_call` | Call initiated | Target user |
| `call_accepted` | Call accepted | Caller |
| `call_rejected` | Call rejected | Caller |
| `call_ended` | Call ended | Other party |
| `webrtc_offer` | WebRTC SDP offer | Target user |
| `webrtc_answer` | WebRTC SDP answer | Target user |
| `webrtc_ice` | WebRTC ICE candidate | Target user |
| `force_disconnect` | User banned/kicked | Target user |

---

## Data Models

### User
```json
{
  "username": "user1",
  "display_name": "User One",
  "role": "user",
  "status": "online",
  "is_banned": false,
  "created_at": "2025-01-01T00:00:00"
}
```

### Message
```json
{
  "id": 42,
  "sender": "user1",
  "text": "Hello",
  "target": null,
  "room_id": null,
  "reply_to": null,
  "encrypted": false,
  "timestamp": "2025-01-01T12:00:00"
}
```

### Room
```json
{
  "id": 1,
  "name": "General",
  "description": "Public chat room",
  "created_by": "user1",
  "member_count": 5
}
```

### File
```json
{
  "id": 1,
  "original_name": "photo.jpg",
  "saved_name": "1234567890_photo.jpg",
  "size": 51200,
  "uploaded_by": "user1",
  "room_id": null,
  "uploaded_at": "2025-01-01T00:00:00"
}
```

### Recording
```json
{
  "id": 1,
  "caller": "user1",
  "callee": "user2",
  "call_type": "video",
  "filename": "recording_1234567890_rec.webm",
  "size": 1048576,
  "duration": 120,
  "created_at": "2025-01-01T00:00:00"
}
```

### Network Interface
```json
{
  "name": "wlan0",
  "ip": "192.168.1.100",
  "netmask": "255.255.255.0",
  "mac": "aa:bb:cc:dd:ee:ff",
  "type": "WiFi",
  "gateway": "192.168.1.1",
  "is_fiber": false,
  "active": true
}
```

---

## Error Handling

### HTTP Error Responses
All API errors return JSON with an `error` field:

```json
{
  "error": "Error description"
}
```

Common HTTP status codes:
- `400` - Bad request (validation error)
- `401` - Unauthorized (not authenticated)
- `403` - Forbidden (insufficient permissions)
- `404` - Not found

### Socket.IO Errors
Socket.IO errors are returned via the response event (e.g., `auth_result` with `ok: false`).

---

## Rate Limiting

Authentication endpoints are rate-limited per IP address:
- **Window:** 60 seconds
- **Max attempts:** 10 per window
- Applies to: `/login`, `auth_register`, `auth_login`
- Exceeded: Returns error message asking to wait

---

## Roles & Permissions

| Role | Permissions |
|------|------------|
| `user` | Send messages, join rooms, upload files, make calls |
| `moderator` | All user permissions + delete any message, kick users |
| `admin` | All moderator permissions + ban/unban, delete users, manage roles |
