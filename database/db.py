"""
Helen WiFi - SQLite Database
Users, Messages, Files, Rooms
"""
import sqlite3
import threading
import os
import logging
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

logger = logging.getLogger("BRO.db")


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
                uploaded_at TEXT DEFAULT (datetime('now'))
            );
        """)
        # Create default general room if not exists
        cur = conn.execute("SELECT id FROM rooms WHERE name=?", ("عامة",))
        if not cur.fetchone():
            conn.execute("INSERT INTO rooms (name, description, created_by) VALUES (?, ?, ?)",
                         ("عامة", "الغرفة العامة", "system"))
        conn.commit()

    # --- Users ---

    def register_user(self, username, password, display_name=None):
        conn = self._get_conn()
        pw_hash = generate_password_hash(password)
        try:
            conn.execute(
                "INSERT INTO users (username, password_hash, display_name) VALUES (?, ?, ?)",
                (username, pw_hash, display_name or username))
            conn.commit()
            # Auto-join general room
            self.join_room_by_name("عامة", username)
            return True
        except sqlite3.IntegrityError:
            return False

    def authenticate(self, username, password):
        conn = self._get_conn()
        row = conn.execute("SELECT password_hash FROM users WHERE username=?", (username,)).fetchone()
        if row and check_password_hash(row["password_hash"], password):
            conn.execute("UPDATE users SET last_seen=datetime('now'), status='online' WHERE username=?", (username,))
            conn.commit()
            return True
        return False

    def user_exists(self, username):
        conn = self._get_conn()
        return conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone() is not None

    def set_status(self, username, status):
        conn = self._get_conn()
        conn.execute("UPDATE users SET status=?, last_seen=datetime('now') WHERE username=?", (status, username))
        conn.commit()

    def set_offline(self, username):
        self.set_status(username, "offline")

    def get_user(self, username):
        conn = self._get_conn()
        row = conn.execute("SELECT username, display_name, status, last_seen FROM users WHERE username=?",
                           (username,)).fetchone()
        return dict(row) if row else None

    def get_all_users(self):
        conn = self._get_conn()
        rows = conn.execute("SELECT username, display_name, status, last_seen FROM users ORDER BY username").fetchall()
        return [dict(r) for r in rows]

    # --- Rooms ---

    def create_room(self, name, description="", created_by="system"):
        conn = self._get_conn()
        try:
            conn.execute("INSERT INTO rooms (name, description, created_by) VALUES (?, ?, ?)",
                         (name, description, created_by))
            conn.commit()
            room_id = conn.execute("SELECT id FROM rooms WHERE name=?", (name,)).fetchone()["id"]
            # Creator auto-joins
            if created_by != "system":
                self.join_room(room_id, created_by)
            return room_id
        except sqlite3.IntegrityError:
            return None

    def get_rooms(self):
        conn = self._get_conn()
        rows = conn.execute("SELECT id, name, description, created_by, created_at FROM rooms ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def get_room(self, room_id):
        conn = self._get_conn()
        row = conn.execute("SELECT id, name, description, created_by, created_at FROM rooms WHERE id=?",
                           (room_id,)).fetchone()
        return dict(row) if row else None

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

    # --- Messages ---

    def save_message(self, sender, text, target=None, room_id=None):
        conn = self._get_conn()
        ts = datetime.utcnow().isoformat()
        conn.execute("INSERT INTO messages (sender, text, target, room_id, timestamp) VALUES (?, ?, ?, ?, ?)",
                     (sender, text, target, room_id, ts))
        conn.commit()
        return ts

    def get_messages(self, room_id=None, target=None, limit=50):
        conn = self._get_conn()
        if room_id:
            rows = conn.execute(
                "SELECT sender, text, target, room_id, timestamp FROM messages WHERE room_id=? ORDER BY id DESC LIMIT ?",
                (room_id, limit)).fetchall()
        elif target:
            rows = conn.execute(
                "SELECT sender, text, target, room_id, timestamp FROM messages WHERE target=? OR sender=? ORDER BY id DESC LIMIT ?",
                (target, target, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT sender, text, target, room_id, timestamp FROM messages ORDER BY id DESC LIMIT ?",
                (limit,)).fetchall()
        return list(reversed([dict(r) for r in rows]))

    def get_dm_history(self, user1, user2, limit=50):
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT sender, text, target, room_id, timestamp FROM messages
            WHERE (sender=? AND target=?) OR (sender=? AND target=?)
            ORDER BY id DESC LIMIT ?
        """, (user1, user2, user2, user1, limit)).fetchall()
        return list(reversed([dict(r) for r in rows]))

    def get_all_messages(self, limit=100):
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT sender, text, target, room_id, timestamp FROM messages ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()
        return list(reversed([dict(r) for r in rows]))

    # --- Files ---

    def save_file(self, name, saved_as, size, uploaded_by, room_id=None):
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO files (name, saved_as, size, uploaded_by, room_id, uploaded_at) VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (name, saved_as, size, uploaded_by, room_id))
        conn.commit()

    def get_files(self, room_id=None, limit=100):
        conn = self._get_conn()
        if room_id:
            rows = conn.execute(
                "SELECT name, saved_as, size, uploaded_by, uploaded_at FROM files WHERE room_id=? ORDER BY id DESC LIMIT ?",
                (room_id, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT name, saved_as, size, uploaded_by, uploaded_at FROM files ORDER BY id DESC LIMIT ?",
                (limit,)).fetchall()
        return [dict(r) for r in rows]

    def count_messages(self):
        conn = self._get_conn()
        return conn.execute("SELECT COUNT(*) as c FROM messages").fetchone()["c"]

    def count_files(self):
        conn = self._get_conn()
        return conn.execute("SELECT COUNT(*) as c FROM files").fetchone()["c"]

    def count_users(self):
        conn = self._get_conn()
        return conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
