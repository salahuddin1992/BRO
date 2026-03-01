"""
Helen WiFi - SQLite Database
Users, Messages, Files, Rooms, Bans
"""
import sqlite3
import threading
import os
import logging
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

logger = logging.getLogger("BRO.db")

IMAGE_EXTS = {'png','jpg','jpeg','gif','bmp','webp','svg'}


class Database:
    def __init__(self, db_path):
        self.db_path = db_path
        self._local = threading.local()
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
                deleted INTEGER DEFAULT 0,
                timestamp TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                saved_as TEXT NOT NULL,
                size INTEGER DEFAULT 0,
                uploaded_by TEXT,
                room_id INTEGER,
                uploaded_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_messages_room ON messages(room_id);
            CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages(sender);
            CREATE INDEX IF NOT EXISTS idx_messages_target ON messages(target);
            CREATE INDEX IF NOT EXISTS idx_messages_ts ON messages(timestamp);
        """)
        # Add columns if upgrading from older schema
        try:
            conn.execute("ALTER TABLE users ADD COLUMN banned INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE messages ADD COLUMN reply_to INTEGER")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE messages ADD COLUMN deleted INTEGER DEFAULT 0")
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
                "INSERT INTO users (username, password_hash, display_name) VALUES (?, ?, ?)",
                (username, pw_hash, display_name or username))
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
        conn = self._get_conn()
        row = conn.execute("SELECT username, display_name, status, banned, last_seen, created_at FROM users WHERE username=?",
                           (username,)).fetchone()
        return dict(row) if row else None

    def get_all_users(self):
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT username, display_name, status, banned, last_seen, created_at FROM users ORDER BY username"
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

    def unban_user(self, username):
        conn = self._get_conn()
        conn.execute("UPDATE users SET banned=0 WHERE username=?", (username,))
        conn.commit()

    def delete_user(self, username):
        conn = self._get_conn()
        conn.execute("UPDATE messages SET deleted=1 WHERE sender=?", (username,))
        conn.execute("DELETE FROM room_members WHERE username=?", (username,))
        conn.execute("DELETE FROM users WHERE username=?", (username,))
        conn.commit()

    def get_files_by_room(self, room_id):
        conn = self._get_conn()
        rows = conn.execute("SELECT id, saved_as FROM files WHERE room_id=?", (room_id,)).fetchall()
        return [dict(r) for r in rows]

    def admin_reset_password(self, username, new_password):
        conn = self._get_conn()
        conn.execute("UPDATE users SET password_hash=? WHERE username=?",
                     (generate_password_hash(new_password), username))
        conn.commit()

    # ===================== Rooms =====================

    def create_room(self, name, description="", created_by="system"):
        conn = self._get_conn()
        try:
            conn.execute("INSERT INTO rooms (name, description, created_by) VALUES (?, ?, ?)",
                         (name, description, created_by))
            conn.commit()
            room_id = conn.execute("SELECT id FROM rooms WHERE name=?", (name,)).fetchone()["id"]
            if created_by != "system":
                self.join_room(room_id, created_by)
            return room_id
        except sqlite3.IntegrityError:
            return None

    def get_rooms(self):
        conn = self._get_conn()
        rows = conn.execute("SELECT id, name, description, created_by, created_at FROM rooms ORDER BY id").fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["member_count"] = conn.execute("SELECT COUNT(*) as c FROM room_members WHERE room_id=?",
                                             (d["id"],)).fetchone()["c"]
            result.append(d)
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

    def get_room_members(self, room_id):
        conn = self._get_conn()
        rows = conn.execute("SELECT username FROM room_members WHERE room_id=?", (room_id,)).fetchall()
        return [r["username"] for r in rows]

    def get_user_rooms(self, username):
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT r.id, r.name, r.description FROM rooms r
            JOIN room_members rm ON r.id = rm.room_id
            WHERE rm.username=? ORDER BY r.id
        """, (username,)).fetchall()
        return [dict(r) for r in rows]

    # ===================== Messages =====================

    def save_message(self, sender, text, target=None, room_id=None, reply_to=None):
        conn = self._get_conn()
        ts = datetime.utcnow().isoformat()
        cur = conn.execute(
            "INSERT INTO messages (sender, text, target, room_id, reply_to, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
            (sender, text, target, room_id, reply_to, ts))
        conn.commit()
        return {"id": cur.lastrowid, "timestamp": ts}

    def get_messages(self, room_id=None, target=None, limit=50):
        conn = self._get_conn()
        if room_id:
            rows = conn.execute(
                "SELECT id, sender, text, target, room_id, reply_to, deleted, timestamp FROM messages WHERE room_id=? AND deleted=0 ORDER BY id DESC LIMIT ?",
                (room_id, limit)).fetchall()
        elif target:
            rows = conn.execute(
                "SELECT id, sender, text, target, room_id, reply_to, deleted, timestamp FROM messages WHERE (target=? OR sender=?) AND deleted=0 ORDER BY id DESC LIMIT ?",
                (target, target, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, sender, text, target, room_id, reply_to, deleted, timestamp FROM messages WHERE deleted=0 ORDER BY id DESC LIMIT ?",
                (limit,)).fetchall()
        return list(reversed([dict(r) for r in rows]))

    def get_dm_history(self, user1, user2, limit=50):
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT id, sender, text, target, room_id, reply_to, deleted, timestamp FROM messages
            WHERE ((sender=? AND target=?) OR (sender=? AND target=?)) AND deleted=0
            ORDER BY id DESC LIMIT ?
        """, (user1, user2, user2, user1, limit)).fetchall()
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
            # Only search in user's rooms and own DMs
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

    def save_file(self, name, saved_as, size, uploaded_by, room_id=None):
        conn = self._get_conn()
        cur = conn.execute(
            "INSERT INTO files (name, saved_as, size, uploaded_by, room_id, uploaded_at) VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (name, saved_as, size, uploaded_by, room_id))
        conn.commit()
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
