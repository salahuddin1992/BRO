"""
Helen WiFi - SQLite Database
Users, Messages, Files, Rooms, Bans, Roles, Encryption Keys, Backup
"""
import sqlite3
import threading
import os
import shutil
import logging
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from cachetools import TTLCache

logger = logging.getLogger("BRO.db")

IMAGE_EXTS = {'png','jpg','jpeg','gif','bmp','webp','svg'}

# User roles
ROLE_USER = 'user'
ROLE_MODERATOR = 'moderator'
ROLE_ADMIN = 'admin'

ROLE_PERMISSIONS = {
    ROLE_USER: ['send_message', 'create_room', 'join_room', 'upload_file', 'make_call'],
    ROLE_MODERATOR: ['send_message', 'create_room', 'join_room', 'upload_file', 'make_call',
                     'delete_message', 'kick_user', 'mute_user', 'manage_rooms'],
    ROLE_ADMIN: ['send_message', 'create_room', 'join_room', 'upload_file', 'make_call',
                 'delete_message', 'kick_user', 'mute_user', 'manage_rooms',
                 'ban_user', 'delete_user', 'manage_roles', 'manage_server', 'backup'],
}


class Database:
    def __init__(self, db_path):
        self.db_path = db_path
        self._local = threading.local()
        # Caches: TTL in seconds, maxsize = max entries
        self._user_cache = TTLCache(maxsize=200, ttl=60)        # user lookups: 60s
        self._rooms_cache = TTLCache(maxsize=50, ttl=30)        # rooms list: 30s
        self._room_members_cache = TTLCache(maxsize=100, ttl=30) # room members: 30s
        self._init_db()

    def _get_conn(self):
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA foreign_keys=ON")
        return self._local.conn

    def _init_db(self):
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                display_name TEXT,
                status TEXT DEFAULT 'online',
                banned INTEGER DEFAULT 0,
                role TEXT DEFAULT 'user',
                public_key TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                last_seen TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS rooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT DEFAULT '',
                created_by TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS room_members (
                room_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                joined_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (room_id, username),
                FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender TEXT NOT NULL,
                text TEXT NOT NULL,
                target TEXT,
                room_id INTEGER,
                reply_to INTEGER,
                encrypted INTEGER DEFAULT 0,
                deleted INTEGER DEFAULT 0,
                timestamp TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                saved_as TEXT NOT NULL,
                size INTEGER DEFAULT 0,
                mime_type TEXT DEFAULT '',
                uploaded_by TEXT,
                room_id INTEGER,
                encrypted INTEGER DEFAULT 0,
                expires_at TEXT,
                uploaded_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS user_quotas (
                username TEXT PRIMARY KEY,
                used_bytes INTEGER DEFAULT 0,
                max_bytes INTEGER DEFAULT 524288000
            );

            CREATE TABLE IF NOT EXISTS offline_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_user TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_offline_target ON offline_messages(target_user);

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS recordings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                caller TEXT NOT NULL,
                callee TEXT NOT NULL,
                call_type TEXT DEFAULT 'audio',
                filename TEXT NOT NULL,
                size INTEGER DEFAULT 0,
                duration INTEGER DEFAULT 0,
                recorded_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS backups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                size INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                description TEXT DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_messages_room ON messages(room_id);
            CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages(sender);
            CREATE INDEX IF NOT EXISTS idx_messages_target ON messages(target);
            CREATE INDEX IF NOT EXISTS idx_messages_ts ON messages(timestamp);
        """)
        # Add columns if upgrading from older schema
        for col_sql in [
            "ALTER TABLE users ADD COLUMN banned INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user'",
            "ALTER TABLE users ADD COLUMN public_key TEXT",
            "ALTER TABLE messages ADD COLUMN reply_to INTEGER",
            "ALTER TABLE messages ADD COLUMN deleted INTEGER DEFAULT 0",
            "ALTER TABLE messages ADD COLUMN encrypted INTEGER DEFAULT 0",
            "ALTER TABLE files ADD COLUMN mime_type TEXT DEFAULT ''",
            "ALTER TABLE files ADD COLUMN encrypted INTEGER DEFAULT 0",
            "ALTER TABLE files ADD COLUMN expires_at TEXT",
        ]:
            try:
                conn.execute(col_sql)
            except sqlite3.OperationalError:
                pass
        # Default general room
        cur = conn.execute("SELECT id FROM rooms WHERE name=?", ("عامة",))
        if not cur.fetchone():
            conn.execute("INSERT INTO rooms (name, description, created_by) VALUES (?, ?, ?)",
                         ("عامة", "الغرفة العامة", "system"))
        conn.commit()

    # ===================== Users =====================

    def register_user(self, username, password, display_name=None):
        conn = self._get_conn()
        pw_hash = generate_password_hash(password)
        try:
            conn.execute(
                "INSERT INTO users (username, password_hash, display_name, role) VALUES (?, ?, ?, ?)",
                (username, pw_hash, display_name or username, ROLE_USER))
            conn.commit()
            self.join_room_by_name("عامة", username)
            return True
        except sqlite3.IntegrityError:
            return False

    def authenticate(self, username, password):
        conn = self._get_conn()
        row = conn.execute("SELECT password_hash, banned FROM users WHERE username=?", (username,)).fetchone()
        if not row:
            return False
        if row["banned"]:
            return None  # banned
        if check_password_hash(row["password_hash"], password):
            conn.execute("UPDATE users SET last_seen=datetime('now'), status='online' WHERE username=?", (username,))
            conn.commit()
            return True
        return False

    def user_exists(self, username):
        conn = self._get_conn()
        return conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone() is not None

    def is_banned(self, username):
        conn = self._get_conn()
        row = conn.execute("SELECT banned FROM users WHERE username=?", (username,)).fetchone()
        return bool(row and row["banned"])

    def set_status(self, username, status):
        conn = self._get_conn()
        conn.execute("UPDATE users SET status=?, last_seen=datetime('now') WHERE username=?", (status, username))
        conn.commit()

    def set_offline(self, username):
        self.set_status(username, "offline")

    def get_user(self, username):
        cached = self._user_cache.get(username)
        if cached is not None:
            return cached
        conn = self._get_conn()
        row = conn.execute("SELECT username, display_name, status, banned, role, public_key, last_seen, created_at FROM users WHERE username=?",
                           (username,)).fetchone()
        result = dict(row) if row else None
        if result:
            self._user_cache[username] = result
        return result

    def get_all_users(self):
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT username, display_name, status, banned, role, last_seen, created_at FROM users ORDER BY username"
        ).fetchall()
        return [dict(r) for r in rows]

    def change_password(self, username, old_password, new_password):
        conn = self._get_conn()
        row = conn.execute("SELECT password_hash FROM users WHERE username=?", (username,)).fetchone()
        if not row or not check_password_hash(row["password_hash"], old_password):
            return False
        conn.execute("UPDATE users SET password_hash=? WHERE username=?",
                     (generate_password_hash(new_password), username))
        conn.commit()
        return True

    def update_display_name(self, username, display_name):
        conn = self._get_conn()
        conn.execute("UPDATE users SET display_name=? WHERE username=?", (display_name, username))
        conn.commit()

    def ban_user(self, username):
        conn = self._get_conn()
        conn.execute("UPDATE users SET banned=1, status='offline' WHERE username=?", (username,))
        conn.commit()
        self._user_cache.pop(username, None)

    def unban_user(self, username):
        conn = self._get_conn()
        conn.execute("UPDATE users SET banned=0 WHERE username=?", (username,))
        conn.commit()
        self._user_cache.pop(username, None)

    def delete_user(self, username):
        conn = self._get_conn()
        conn.execute("UPDATE messages SET deleted=1 WHERE sender=?", (username,))
        conn.execute("DELETE FROM room_members WHERE username=?", (username,))
        conn.execute("DELETE FROM users WHERE username=?", (username,))
        conn.commit()
        self._user_cache.pop(username, None)
        self._rooms_cache.clear()
        self._room_members_cache.clear()

    def get_files_by_room(self, room_id):
        conn = self._get_conn()
        rows = conn.execute("SELECT id, saved_as FROM files WHERE room_id=?", (room_id,)).fetchall()
        return [dict(r) for r in rows]

    def admin_reset_password(self, username, new_password):
        conn = self._get_conn()
        conn.execute("UPDATE users SET password_hash=? WHERE username=?",
                     (generate_password_hash(new_password), username))
        conn.commit()

    # ===================== Roles =====================

    def get_user_role(self, username):
        conn = self._get_conn()
        row = conn.execute("SELECT role FROM users WHERE username=?", (username,)).fetchone()
        return row["role"] if row else ROLE_USER

    def set_user_role(self, username, role):
        if role not in ROLE_PERMISSIONS:
            return False
        conn = self._get_conn()
        conn.execute("UPDATE users SET role=? WHERE username=?", (role, username))
        conn.commit()
        self._user_cache.pop(username, None)
        return True

    def has_permission(self, username, permission):
        role = self.get_user_role(username)
        return permission in ROLE_PERMISSIONS.get(role, [])

    def get_role_permissions(self, role):
        return ROLE_PERMISSIONS.get(role, [])

    # ===================== Public Keys (E2E) =====================

    def set_public_key(self, username, public_key):
        conn = self._get_conn()
        conn.execute("UPDATE users SET public_key=? WHERE username=?", (public_key, username))
        conn.commit()

    def get_public_key(self, username):
        conn = self._get_conn()
        row = conn.execute("SELECT public_key FROM users WHERE username=?", (username,)).fetchone()
        return row["public_key"] if row else None

    def get_public_keys(self, usernames):
        conn = self._get_conn()
        placeholders = ",".join("?" for _ in usernames)
        rows = conn.execute(
            f"SELECT username, public_key FROM users WHERE username IN ({placeholders}) AND public_key IS NOT NULL",
            usernames).fetchall()
        return {r["username"]: r["public_key"] for r in rows}

    # ===================== Rooms =====================

    def create_room(self, name, description="", created_by="system"):
        conn = self._get_conn()
        try:
            conn.execute("INSERT INTO rooms (name, description, created_by) VALUES (?, ?, ?)",
                         (name, description, created_by))
            conn.commit()
            room_id = conn.execute("SELECT id FROM rooms WHERE name=?", (name,)).fetchone()["id"]
            self._rooms_cache.clear()
            if created_by != "system":
                self.join_room(room_id, created_by)
            return room_id
        except sqlite3.IntegrityError:
            return None

    def get_rooms(self):
        cached = self._rooms_cache.get("all_rooms")
        if cached is not None:
            return cached
        conn = self._get_conn()
        rows = conn.execute("SELECT id, name, description, created_by, created_at FROM rooms ORDER BY id").fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["member_count"] = conn.execute("SELECT COUNT(*) as c FROM room_members WHERE room_id=?",
                                             (d["id"],)).fetchone()["c"]
            result.append(d)
        self._rooms_cache["all_rooms"] = result
        return result

    def get_room(self, room_id):
        conn = self._get_conn()
        row = conn.execute("SELECT id, name, description, created_by, created_at FROM rooms WHERE id=?",
                           (room_id,)).fetchone()
        return dict(row) if row else None

    def delete_room(self, room_id):
        conn = self._get_conn()
        conn.execute("DELETE FROM rooms WHERE id=? AND name != ?", (room_id, "عامة"))
        conn.commit()
        self._rooms_cache.clear()
        self._room_members_cache.pop(f"members_{room_id}", None)

    def update_room(self, room_id, name=None, description=None):
        conn = self._get_conn()
        if name:
            conn.execute("UPDATE rooms SET name=? WHERE id=?", (name, room_id))
        if description is not None:
            conn.execute("UPDATE rooms SET description=? WHERE id=?", (description, room_id))
        conn.commit()

    def join_room(self, room_id, username):
        conn = self._get_conn()
        try:
            conn.execute("INSERT OR IGNORE INTO room_members (room_id, username) VALUES (?, ?)",
                         (room_id, username))
            conn.commit()
            self._room_members_cache.pop(f"members_{room_id}", None)
            self._rooms_cache.clear()
            return True
        except Exception:
            return False

    def join_room_by_name(self, room_name, username):
        conn = self._get_conn()
        row = conn.execute("SELECT id FROM rooms WHERE name=?", (room_name,)).fetchone()
        if row:
            return self.join_room(row["id"], username)
        return False

    def leave_room(self, room_id, username):
        conn = self._get_conn()
        conn.execute("DELETE FROM room_members WHERE room_id=? AND username=?", (room_id, username))
        conn.commit()
        self._room_members_cache.pop(f"members_{room_id}", None)
        self._rooms_cache.clear()

    def get_room_members(self, room_id):
        cache_key = f"members_{room_id}"
        cached = self._room_members_cache.get(cache_key)
        if cached is not None:
            return cached
        conn = self._get_conn()
        rows = conn.execute("SELECT username FROM room_members WHERE room_id=?", (room_id,)).fetchall()
        result = [r["username"] for r in rows]
        self._room_members_cache[cache_key] = result
        return result

    def get_user_rooms(self, username):
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT r.id, r.name, r.description FROM rooms r
            JOIN room_members rm ON r.id = rm.room_id
            WHERE rm.username=? ORDER BY r.id
        """, (username,)).fetchall()
        return [dict(r) for r in rows]

    # ===================== Messages =====================

    def save_message(self, sender, text, target=None, room_id=None, reply_to=None, encrypted=False):
        conn = self._get_conn()
        ts = datetime.utcnow().isoformat()
        cur = conn.execute(
            "INSERT INTO messages (sender, text, target, room_id, reply_to, encrypted, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sender, text, target, room_id, reply_to, 1 if encrypted else 0, ts))
        conn.commit()
        return {"id": cur.lastrowid, "timestamp": ts}

    def get_messages(self, room_id=None, target=None, limit=50, before_id=None):
        conn = self._get_conn()
        before_clause = "AND id < ?" if before_id else ""
        params = []
        if room_id:
            params = [room_id]
            if before_id:
                params.append(before_id)
            params.append(limit)
            rows = conn.execute(
                f"SELECT id, sender, text, target, room_id, reply_to, encrypted, deleted, timestamp FROM messages WHERE room_id=? AND deleted=0 {before_clause} ORDER BY id DESC LIMIT ?",
                params).fetchall()
        elif target:
            params = [target, target]
            if before_id:
                params.append(before_id)
            params.append(limit)
            rows = conn.execute(
                f"SELECT id, sender, text, target, room_id, reply_to, encrypted, deleted, timestamp FROM messages WHERE (target=? OR sender=?) AND deleted=0 {before_clause} ORDER BY id DESC LIMIT ?",
                params).fetchall()
        else:
            params = []
            if before_id:
                params.append(before_id)
            params.append(limit)
            rows = conn.execute(
                f"SELECT id, sender, text, target, room_id, reply_to, encrypted, deleted, timestamp FROM messages WHERE deleted=0 {before_clause} ORDER BY id DESC LIMIT ?",
                params).fetchall()
        return list(reversed([dict(r) for r in rows]))

    def get_dm_history(self, user1, user2, limit=50, before_id=None):
        conn = self._get_conn()
        before_clause = "AND id < ?" if before_id else ""
        params = [user1, user2, user2, user1]
        if before_id:
            params.append(before_id)
        params.append(limit)
        rows = conn.execute(f"""
            SELECT id, sender, text, target, room_id, reply_to, encrypted, deleted, timestamp FROM messages
            WHERE ((sender=? AND target=?) OR (sender=? AND target=?)) AND deleted=0
            {before_clause} ORDER BY id DESC LIMIT ?
        """, params).fetchall()
        return list(reversed([dict(r) for r in rows]))

    def get_message(self, msg_id):
        conn = self._get_conn()
        row = conn.execute("SELECT id, sender, text, target, room_id, reply_to, timestamp FROM messages WHERE id=?",
                           (msg_id,)).fetchone()
        return dict(row) if row else None

    def delete_message(self, msg_id, username=None):
        """Delete a message. If username given, only allow sender to delete."""
        conn = self._get_conn()
        if username:
            conn.execute("UPDATE messages SET deleted=1 WHERE id=? AND sender=?", (msg_id, username))
        else:
            conn.execute("UPDATE messages SET deleted=1 WHERE id=?", (msg_id,))
        conn.commit()

    def search_messages(self, query, room_id=None, username=None, limit=30):
        conn = self._get_conn()
        q = f"%{query}%"
        if room_id:
            rows = conn.execute(
                "SELECT id, sender, text, room_id, timestamp FROM messages WHERE text LIKE ? AND room_id=? AND deleted=0 ORDER BY id DESC LIMIT ?",
                (q, room_id, limit)).fetchall()
        elif username:
            user_rooms = [r["id"] for r in self.get_user_rooms(username)]
            if user_rooms:
                placeholders = ",".join("?" for _ in user_rooms)
                rows = conn.execute(
                    f"SELECT id, sender, text, room_id, timestamp FROM messages WHERE text LIKE ? AND deleted=0 AND (room_id IN ({placeholders}) OR sender=? OR target=?) ORDER BY id DESC LIMIT ?",
                    [q] + user_rooms + [username, username, limit]).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, sender, text, room_id, timestamp FROM messages WHERE text LIKE ? AND deleted=0 AND (sender=? OR target=?) ORDER BY id DESC LIMIT ?",
                    (q, username, username, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, sender, text, room_id, timestamp FROM messages WHERE text LIKE ? AND deleted=0 ORDER BY id DESC LIMIT ?",
                (q, limit)).fetchall()
        return [dict(r) for r in rows]

    def get_all_messages(self, limit=100):
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id, sender, text, target, room_id, timestamp FROM messages WHERE deleted=0 ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()
        return list(reversed([dict(r) for r in rows]))

    def admin_delete_messages_by_user(self, username):
        conn = self._get_conn()
        conn.execute("UPDATE messages SET deleted=1 WHERE sender=?", (username,))
        conn.commit()

    def get_unread_count(self, username, room_id, last_read_ts):
        """Count messages in a room after a certain timestamp."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT COUNT(*) as c FROM messages WHERE room_id=? AND sender!=? AND timestamp>? AND deleted=0",
            (room_id, username, last_read_ts or "2000-01-01")).fetchone()
        return row["c"] if row else 0

    # ===================== Files =====================

    def save_file(self, name, saved_as, size, uploaded_by, room_id=None, mime_type='', encrypted=False, expires_at=None):
        conn = self._get_conn()
        cur = conn.execute(
            "INSERT INTO files (name, saved_as, size, uploaded_by, room_id, mime_type, encrypted, expires_at, uploaded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
            (name, saved_as, size, uploaded_by, room_id, mime_type, 1 if encrypted else 0, expires_at))
        conn.commit()
        # Update user quota
        self._update_quota(uploaded_by, size)
        return cur.lastrowid

    def get_files(self, room_id=None, limit=100):
        conn = self._get_conn()
        if room_id:
            rows = conn.execute(
                "SELECT id, name, saved_as, size, uploaded_by, uploaded_at FROM files WHERE room_id=? ORDER BY id DESC LIMIT ?",
                (room_id, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, name, saved_as, size, uploaded_by, uploaded_at FROM files ORDER BY id DESC LIMIT ?",
                (limit,)).fetchall()
        return [dict(r) for r in rows]

    def delete_file(self, file_id):
        conn = self._get_conn()
        row = conn.execute("SELECT saved_as FROM files WHERE id=?", (file_id,)).fetchone()
        conn.execute("DELETE FROM files WHERE id=?", (file_id,))
        conn.commit()
        return row["saved_as"] if row else None

    def search_files(self, query, uploaded_by=None, room_id=None, date_from=None, date_to=None, limit=50):
        """Search files by name, uploader, room, or date range."""
        conn = self._get_conn()
        conditions = ["1=1"]
        params = []
        if query:
            conditions.append("name LIKE ?")
            params.append(f"%{query}%")
        if uploaded_by:
            conditions.append("uploaded_by = ?")
            params.append(uploaded_by)
        if room_id:
            conditions.append("room_id = ?")
            params.append(room_id)
        if date_from:
            conditions.append("uploaded_at >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("uploaded_at <= ?")
            params.append(date_to)
        where = " AND ".join(conditions)
        params.append(limit)
        rows = conn.execute(
            f"SELECT id, name, saved_as, size, mime_type, uploaded_by, room_id, uploaded_at FROM files WHERE {where} ORDER BY id DESC LIMIT ?",
            params).fetchall()
        return [dict(r) for r in rows]

    def get_expired_files(self):
        """Get files that have passed their expiration date."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id, saved_as FROM files WHERE expires_at IS NOT NULL AND expires_at < datetime('now')"
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_expired_files(self):
        """Delete expired file records and return their saved_as names."""
        expired = self.get_expired_files()
        if expired:
            conn = self._get_conn()
            ids = [f["id"] for f in expired]
            placeholders = ",".join("?" for _ in ids)
            conn.execute(f"DELETE FROM files WHERE id IN ({placeholders})", ids)
            conn.commit()
        return expired

    # ===================== User Quotas =====================

    def _update_quota(self, username, size_delta):
        """Update user's storage quota usage."""
        if not username:
            return
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO user_quotas (username, used_bytes) VALUES (?, MAX(0, ?)) "
            "ON CONFLICT(username) DO UPDATE SET used_bytes = MAX(0, user_quotas.used_bytes + ?)",
            (username, size_delta, size_delta))
        conn.commit()

    def get_user_quota(self, username):
        """Get user's quota info: {used_bytes, max_bytes}."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT used_bytes, max_bytes FROM user_quotas WHERE username = ?",
            (username,)).fetchone()
        if row:
            return {"used_bytes": row["used_bytes"], "max_bytes": row["max_bytes"]}
        return {"used_bytes": 0, "max_bytes": 524288000}  # 500MB default

    def set_user_quota_limit(self, username, max_bytes):
        """Set max storage quota for a user."""
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO user_quotas (username, max_bytes) VALUES (?, ?) "
            "ON CONFLICT(username) DO UPDATE SET max_bytes = ?",
            (username, max_bytes, max_bytes))
        conn.commit()

    def check_quota(self, username, file_size):
        """Check if user has enough quota for a file. Returns True if ok."""
        quota = self.get_user_quota(username)
        return (quota["used_bytes"] + file_size) <= quota["max_bytes"]

    # ===================== Offline Messages =====================

    def save_offline_message(self, target_user, event_type, payload):
        """Queue a message for an offline user."""
        import json
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO offline_messages (target_user, event_type, payload) VALUES (?, ?, ?)",
            (target_user, event_type, json.dumps(payload)))
        conn.commit()

    def get_offline_messages(self, username, limit=200):
        """Retrieve and delete queued messages for a user."""
        import json
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id, event_type, payload, created_at FROM offline_messages WHERE target_user = ? ORDER BY id LIMIT ?",
            (username, limit)).fetchall()
        messages = [{"event_type": r["event_type"], "payload": json.loads(r["payload"]),
                     "created_at": r["created_at"]} for r in rows]
        if rows:
            ids = [r["id"] for r in rows]
            placeholders = ",".join("?" for _ in ids)
            conn.execute(f"DELETE FROM offline_messages WHERE id IN ({placeholders})", ids)
            conn.commit()
        return messages

    # ===================== Recordings =====================

    def save_recording(self, caller, callee, call_type, filename, size, duration):
        conn = self._get_conn()
        cur = conn.execute(
            "INSERT INTO recordings (caller, callee, call_type, filename, size, duration) VALUES (?, ?, ?, ?, ?, ?)",
            (caller, callee, call_type, filename, size, duration))
        conn.commit()
        return cur.lastrowid

    def get_recordings(self, username=None, limit=50):
        conn = self._get_conn()
        if username:
            rows = conn.execute(
                "SELECT id, caller, callee, call_type, filename, size, duration, recorded_at FROM recordings WHERE caller=? OR callee=? ORDER BY id DESC LIMIT ?",
                (username, username, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, caller, callee, call_type, filename, size, duration, recorded_at FROM recordings ORDER BY id DESC LIMIT ?",
                (limit,)).fetchall()
        return [dict(r) for r in rows]

    def delete_recording(self, rec_id):
        conn = self._get_conn()
        row = conn.execute("SELECT filename FROM recordings WHERE id=?", (rec_id,)).fetchone()
        conn.execute("DELETE FROM recordings WHERE id=?", (rec_id,))
        conn.commit()
        return row["filename"] if row else None

    # ===================== Backup & Restore =====================

    def create_backup(self, backup_dir, description=""):
        """Create a backup of the database."""
        os.makedirs(backup_dir, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_name = f"helen_backup_{ts}.db"
        backup_path = os.path.join(backup_dir, backup_name)

        # Use SQLite backup API
        conn = self._get_conn()
        backup_conn = sqlite3.connect(backup_path)
        conn.backup(backup_conn)
        backup_conn.close()

        size = os.path.getsize(backup_path)
        self.save_backup_record(backup_name, size, description)
        return {"filename": backup_name, "size": size, "created_at": ts}

    def restore_backup(self, backup_dir, backup_name):
        """Restore database from a backup file."""
        backup_path = os.path.join(backup_dir, backup_name)
        if not os.path.isfile(backup_path):
            return False

        # Close current connection
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

        # Replace current DB with backup
        shutil.copy2(backup_path, self.db_path)

        # Re-initialize connection
        self._init_db()
        return True

    def save_backup_record(self, filename, size, description=""):
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO backups (filename, size, description) VALUES (?, ?, ?)",
            (filename, size, description))
        conn.commit()

    def get_backups(self):
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id, filename, size, created_at, description FROM backups ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_backup_record(self, backup_id):
        conn = self._get_conn()
        row = conn.execute("SELECT filename FROM backups WHERE id=?", (backup_id,)).fetchone()
        conn.execute("DELETE FROM backups WHERE id=?", (backup_id,))
        conn.commit()
        return row["filename"] if row else None

    # ===================== Stats =====================

    def count_messages(self):
        conn = self._get_conn()
        return conn.execute("SELECT COUNT(*) as c FROM messages WHERE deleted=0").fetchone()["c"]

    def count_files(self):
        conn = self._get_conn()
        return conn.execute("SELECT COUNT(*) as c FROM files").fetchone()["c"]

    def count_users(self):
        conn = self._get_conn()
        return conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]

    def count_banned(self):
        conn = self._get_conn()
        return conn.execute("SELECT COUNT(*) as c FROM users WHERE banned=1").fetchone()["c"]

    def count_recordings(self):
        conn = self._get_conn()
        return conn.execute("SELECT COUNT(*) as c FROM recordings").fetchone()["c"]

    def get_db_size(self):
        try:
            return os.path.getsize(self.db_path)
        except OSError:
            return 0

    # ===================== Settings =====================

    def set_setting(self, key, value):
        conn = self._get_conn()
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        conn.commit()

    def get_setting(self, key, default=None):
        conn = self._get_conn()
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def get_all_settings(self):
        conn = self._get_conn()
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: r["value"] for r in rows}
