"""
Helen WiFi - Database Unit Tests
Tests for database/db.py: Users, Rooms, Messages, Files, Roles, Recordings, Backup, Settings
"""
import os
import sys
import shutil
import tempfile
import unittest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db import (
    Database, ROLE_USER, ROLE_MODERATOR, ROLE_ADMIN, ROLE_PERMISSIONS
)


class TestDatabaseBase(unittest.TestCase):
    """Base class for database tests with setup/teardown."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test.db")
        self.db = Database(self.db_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)


class TestUserManagement(TestDatabaseBase):
    """Tests for user registration, authentication, and management."""

    def test_register_user(self):
        result = self.db.register_user("alice", "pass123")
        self.assertTrue(result)

    def test_register_duplicate_user(self):
        self.db.register_user("alice", "pass123")
        result = self.db.register_user("alice", "pass456")
        self.assertFalse(result)

    def test_authenticate_valid(self):
        self.db.register_user("alice", "pass123")
        result = self.db.authenticate("alice", "pass123")
        self.assertTrue(result)

    def test_authenticate_wrong_password(self):
        self.db.register_user("alice", "pass123")
        result = self.db.authenticate("alice", "wrong")
        self.assertFalse(result)

    def test_authenticate_nonexistent_user(self):
        result = self.db.authenticate("ghost", "pass123")
        self.assertFalse(result)

    def test_authenticate_banned_user(self):
        self.db.register_user("alice", "pass123")
        self.db.ban_user("alice")
        result = self.db.authenticate("alice", "pass123")
        self.assertIsNone(result)  # None = banned

    def test_user_exists(self):
        self.db.register_user("alice", "pass123")
        self.assertTrue(self.db.user_exists("alice"))
        self.assertFalse(self.db.user_exists("bob"))

    def test_get_user(self):
        self.db.register_user("alice", "pass123", display_name="Alice W")
        user = self.db.get_user("alice")
        self.assertIsNotNone(user)
        self.assertEqual(user["username"], "alice")
        self.assertEqual(user["display_name"], "Alice W")
        self.assertEqual(user["role"], ROLE_USER)
        self.assertFalse(user["banned"])

    def test_get_user_nonexistent(self):
        user = self.db.get_user("ghost")
        self.assertIsNone(user)

    def test_get_all_users(self):
        self.db.register_user("alice", "pass1")
        self.db.register_user("bob", "pass2")
        users = self.db.get_all_users()
        # 11 default seeded users + 2 registered = 13
        self.assertEqual(len(users), 13)
        usernames = [u["username"] for u in users]
        self.assertIn("alice", usernames)
        self.assertIn("bob", usernames)

    def test_set_status(self):
        self.db.register_user("alice", "pass123")
        self.db.set_status("alice", "busy")
        user = self.db.get_user("alice")
        self.assertEqual(user["status"], "busy")

    def test_set_offline(self):
        self.db.register_user("alice", "pass123")
        self.db.set_offline("alice")
        user = self.db.get_user("alice")
        self.assertEqual(user["status"], "offline")

    def test_change_password(self):
        self.db.register_user("alice", "pass123")
        result = self.db.change_password("alice", "pass123", "newpass")
        self.assertTrue(result)
        self.assertTrue(self.db.authenticate("alice", "newpass"))
        self.assertFalse(self.db.authenticate("alice", "pass123"))

    def test_change_password_wrong_old(self):
        self.db.register_user("alice", "pass123")
        result = self.db.change_password("alice", "wrong", "newpass")
        self.assertFalse(result)

    def test_update_display_name(self):
        self.db.register_user("alice", "pass123")
        self.db.update_display_name("alice", "Alice Updated")
        user = self.db.get_user("alice")
        self.assertEqual(user["display_name"], "Alice Updated")

    def test_ban_unban_user(self):
        self.db.register_user("alice", "pass123")
        self.assertFalse(self.db.is_banned("alice"))

        self.db.ban_user("alice")
        self.assertTrue(self.db.is_banned("alice"))

        self.db.unban_user("alice")
        self.assertFalse(self.db.is_banned("alice"))

    def test_delete_user(self):
        self.db.register_user("alice", "pass123")
        self.db.save_message("alice", "hello", room_id=1)
        self.db.delete_user("alice")
        self.assertFalse(self.db.user_exists("alice"))

    def test_admin_reset_password(self):
        self.db.register_user("alice", "pass123")
        self.db.admin_reset_password("alice", "reset456")
        self.assertTrue(self.db.authenticate("alice", "reset456"))
        self.assertFalse(self.db.authenticate("alice", "pass123"))

    def test_register_auto_joins_general_room(self):
        self.db.register_user("alice", "pass123")
        rooms = self.db.get_user_rooms("alice")
        room_names = [r["name"] for r in rooms]
        self.assertIn("عامة", room_names)


class TestRoleManagement(TestDatabaseBase):
    """Tests for role-based access control."""

    def test_default_role_is_user(self):
        self.db.register_user("alice", "pass123")
        self.assertEqual(self.db.get_user_role("alice"), ROLE_USER)

    def test_set_user_role_moderator(self):
        self.db.register_user("alice", "pass123")
        result = self.db.set_user_role("alice", ROLE_MODERATOR)
        self.assertTrue(result)
        self.assertEqual(self.db.get_user_role("alice"), ROLE_MODERATOR)

    def test_set_user_role_admin(self):
        self.db.register_user("alice", "pass123")
        result = self.db.set_user_role("alice", ROLE_ADMIN)
        self.assertTrue(result)
        self.assertEqual(self.db.get_user_role("alice"), ROLE_ADMIN)

    def test_set_invalid_role(self):
        self.db.register_user("alice", "pass123")
        result = self.db.set_user_role("alice", "superadmin")
        self.assertFalse(result)
        self.assertEqual(self.db.get_user_role("alice"), ROLE_USER)

    def test_user_permissions(self):
        self.db.register_user("alice", "pass123")
        self.assertTrue(self.db.has_permission("alice", "send_message"))
        self.assertTrue(self.db.has_permission("alice", "create_room"))
        self.assertFalse(self.db.has_permission("alice", "delete_message"))
        self.assertFalse(self.db.has_permission("alice", "ban_user"))

    def test_moderator_permissions(self):
        self.db.register_user("alice", "pass123")
        self.db.set_user_role("alice", ROLE_MODERATOR)
        self.assertTrue(self.db.has_permission("alice", "send_message"))
        self.assertTrue(self.db.has_permission("alice", "delete_message"))
        self.assertTrue(self.db.has_permission("alice", "kick_user"))
        self.assertFalse(self.db.has_permission("alice", "ban_user"))

    def test_admin_permissions(self):
        self.db.register_user("alice", "pass123")
        self.db.set_user_role("alice", ROLE_ADMIN)
        self.assertTrue(self.db.has_permission("alice", "ban_user"))
        self.assertTrue(self.db.has_permission("alice", "delete_user"))
        self.assertTrue(self.db.has_permission("alice", "backup"))
        self.assertTrue(self.db.has_permission("alice", "manage_server"))

    def test_get_role_permissions(self):
        perms = self.db.get_role_permissions(ROLE_USER)
        self.assertIn("send_message", perms)
        self.assertNotIn("ban_user", perms)

    def test_role_permissions_constants(self):
        self.assertIn(ROLE_USER, ROLE_PERMISSIONS)
        self.assertIn(ROLE_MODERATOR, ROLE_PERMISSIONS)
        self.assertIn(ROLE_ADMIN, ROLE_PERMISSIONS)
        # Admin should have more permissions than user
        self.assertGreater(len(ROLE_PERMISSIONS[ROLE_ADMIN]),
                           len(ROLE_PERMISSIONS[ROLE_USER]))


class TestPublicKeys(TestDatabaseBase):
    """Tests for E2E encryption public key management."""

    def test_set_and_get_public_key(self):
        self.db.register_user("alice", "pass123")
        self.db.set_public_key("alice", '{"kty":"EC","crv":"P-256"}')
        key = self.db.get_public_key("alice")
        self.assertEqual(key, '{"kty":"EC","crv":"P-256"}')

    def test_get_public_key_none(self):
        self.db.register_user("alice", "pass123")
        key = self.db.get_public_key("alice")
        self.assertIsNone(key)

    def test_get_public_key_nonexistent_user(self):
        key = self.db.get_public_key("ghost")
        self.assertIsNone(key)

    def test_get_public_keys_batch(self):
        self.db.register_user("alice", "pass123")
        self.db.register_user("bob", "pass123")
        self.db.set_public_key("alice", "key_a")
        self.db.set_public_key("bob", "key_b")
        keys = self.db.get_public_keys(["alice", "bob"])
        self.assertEqual(keys["alice"], "key_a")
        self.assertEqual(keys["bob"], "key_b")

    def test_get_public_keys_partial(self):
        self.db.register_user("alice", "pass123")
        self.db.register_user("bob", "pass123")
        self.db.set_public_key("alice", "key_a")
        # bob has no key
        keys = self.db.get_public_keys(["alice", "bob"])
        self.assertIn("alice", keys)
        self.assertNotIn("bob", keys)


class TestRoomManagement(TestDatabaseBase):
    """Tests for room creation, joining, and management."""

    def test_default_room_exists(self):
        rooms = self.db.get_rooms()
        names = [r["name"] for r in rooms]
        self.assertIn("عامة", names)

    def test_create_room(self):
        room_id = self.db.create_room("dev", "Development chat", "alice")
        self.assertIsNotNone(room_id)
        room = self.db.get_room(room_id)
        self.assertEqual(room["name"], "dev")
        self.assertEqual(room["description"], "Development chat")

    def test_create_duplicate_room(self):
        self.db.create_room("dev", "")
        result = self.db.create_room("dev", "")
        self.assertIsNone(result)

    def test_join_room(self):
        self.db.register_user("alice", "pass123")
        room_id = self.db.create_room("dev", "")
        self.db.join_room(room_id, "alice")
        members = self.db.get_room_members(room_id)
        self.assertIn("alice", members)

    def test_leave_room(self):
        self.db.register_user("alice", "pass123")
        room_id = self.db.create_room("dev", "")
        self.db.join_room(room_id, "alice")
        self.db.leave_room(room_id, "alice")
        members = self.db.get_room_members(room_id)
        self.assertNotIn("alice", members)

    def test_get_user_rooms(self):
        self.db.register_user("alice", "pass123")
        room_id = self.db.create_room("dev", "")
        self.db.join_room(room_id, "alice")
        rooms = self.db.get_user_rooms("alice")
        names = [r["name"] for r in rooms]
        self.assertIn("dev", names)
        self.assertIn("عامة", names)  # auto-joined

    def test_delete_room(self):
        room_id = self.db.create_room("temp", "")
        self.db.delete_room(room_id)
        room = self.db.get_room(room_id)
        self.assertIsNone(room)

    def test_cannot_delete_general_room(self):
        rooms = self.db.get_rooms()
        general = [r for r in rooms if r["name"] == "عامة"][0]
        self.db.delete_room(general["id"])
        # Should still exist
        rooms = self.db.get_rooms()
        names = [r["name"] for r in rooms]
        self.assertIn("عامة", names)

    def test_update_room(self):
        room_id = self.db.create_room("dev", "old desc")
        self.db.update_room(room_id, description="new desc")
        room = self.db.get_room(room_id)
        self.assertEqual(room["description"], "new desc")

    def test_room_member_count(self):
        self.db.register_user("alice", "pass123")
        self.db.register_user("bob", "pass123")
        room_id = self.db.create_room("dev", "")
        self.db.join_room(room_id, "alice")
        self.db.join_room(room_id, "bob")
        rooms = self.db.get_rooms()
        dev = [r for r in rooms if r["name"] == "dev"][0]
        self.assertEqual(dev["member_count"], 2)

    def test_join_room_by_name(self):
        self.db.register_user("alice", "pass123")
        self.db.create_room("dev", "")
        result = self.db.join_room_by_name("dev", "alice")
        self.assertTrue(result)


class TestMessageManagement(TestDatabaseBase):
    """Tests for message creation, retrieval, and deletion."""

    def setUp(self):
        super().setUp()
        self.db.register_user("alice", "pass123")
        self.db.register_user("bob", "pass123")

    def test_save_message(self):
        result = self.db.save_message("alice", "hello world", room_id=1)
        self.assertIn("id", result)
        self.assertIn("timestamp", result)

    def test_get_messages_by_room(self):
        self.db.save_message("alice", "msg1", room_id=1)
        self.db.save_message("bob", "msg2", room_id=1)
        msgs = self.db.get_messages(room_id=1)
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["text"], "msg1")
        self.assertEqual(msgs[1]["text"], "msg2")

    def test_get_dm_history(self):
        self.db.save_message("alice", "hi bob", target="bob")
        self.db.save_message("bob", "hi alice", target="alice")
        msgs = self.db.get_dm_history("alice", "bob")
        self.assertEqual(len(msgs), 2)

    def test_delete_message(self):
        result = self.db.save_message("alice", "secret", room_id=1)
        msg_id = result["id"]
        self.db.delete_message(msg_id)
        msgs = self.db.get_messages(room_id=1)
        self.assertEqual(len(msgs), 0)

    def test_delete_message_by_sender_only(self):
        result = self.db.save_message("alice", "secret", room_id=1)
        msg_id = result["id"]
        # bob shouldn't be able to delete alice's message
        self.db.delete_message(msg_id, username="bob")
        msgs = self.db.get_messages(room_id=1)
        self.assertEqual(len(msgs), 1)  # still exists
        # alice can delete own message
        self.db.delete_message(msg_id, username="alice")
        msgs = self.db.get_messages(room_id=1)
        self.assertEqual(len(msgs), 0)

    def test_search_messages(self):
        self.db.save_message("alice", "hello world", room_id=1)
        self.db.save_message("alice", "foo bar", room_id=1)
        results = self.db.search_messages("hello")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["text"], "hello world")

    def test_search_messages_in_room(self):
        room2 = self.db.create_room("dev", "")
        self.db.save_message("alice", "hello room1", room_id=1)
        self.db.save_message("alice", "hello room2", room_id=room2)
        results = self.db.search_messages("hello", room_id=1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["text"], "hello room1")

    def test_message_with_reply(self):
        r1 = self.db.save_message("alice", "original", room_id=1)
        r2 = self.db.save_message("bob", "reply", room_id=1, reply_to=r1["id"])
        msg = self.db.get_message(r2["id"])
        self.assertEqual(msg["reply_to"], r1["id"])

    def test_get_message(self):
        result = self.db.save_message("alice", "test", room_id=1)
        msg = self.db.get_message(result["id"])
        self.assertIsNotNone(msg)
        self.assertEqual(msg["sender"], "alice")
        self.assertEqual(msg["text"], "test")

    def test_get_all_messages(self):
        self.db.save_message("alice", "msg1", room_id=1)
        self.db.save_message("bob", "msg2", room_id=1)
        msgs = self.db.get_all_messages()
        self.assertEqual(len(msgs), 2)

    def test_admin_delete_messages_by_user(self):
        self.db.save_message("alice", "msg1", room_id=1)
        self.db.save_message("alice", "msg2", room_id=1)
        self.db.save_message("bob", "msg3", room_id=1)
        self.db.admin_delete_messages_by_user("alice")
        msgs = self.db.get_messages(room_id=1)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["sender"], "bob")

    def test_count_messages(self):
        self.db.save_message("alice", "msg1", room_id=1)
        self.db.save_message("bob", "msg2", room_id=1)
        self.assertEqual(self.db.count_messages(), 2)

    def test_message_pagination(self):
        for i in range(10):
            self.db.save_message("alice", f"msg{i}", room_id=1)
        msgs = self.db.get_messages(room_id=1, limit=3)
        self.assertEqual(len(msgs), 3)

    def test_message_before_id(self):
        ids = []
        for i in range(5):
            r = self.db.save_message("alice", f"msg{i}", room_id=1)
            ids.append(r["id"])
        msgs = self.db.get_messages(room_id=1, before_id=ids[3], limit=10)
        self.assertEqual(len(msgs), 3)

    def test_encrypted_message(self):
        result = self.db.save_message("alice", "encrypted_data", target="bob", encrypted=True)
        msg = self.db.get_message(result["id"])
        self.assertEqual(msg["text"], "encrypted_data")


class TestFileManagement(TestDatabaseBase):
    """Tests for file upload tracking."""

    def test_save_file(self):
        file_id = self.db.save_file("test.png", "abc_test.png", 1024, "alice", room_id=1)
        self.assertIsNotNone(file_id)

    def test_get_files(self):
        self.db.save_file("a.png", "1_a.png", 100, "alice", room_id=1)
        self.db.save_file("b.pdf", "2_b.pdf", 200, "bob", room_id=1)
        files = self.db.get_files(room_id=1)
        self.assertEqual(len(files), 2)

    def test_get_all_files(self):
        self.db.save_file("a.png", "1_a.png", 100, "alice", room_id=1)
        room2 = self.db.create_room("dev", "")
        self.db.save_file("b.pdf", "2_b.pdf", 200, "bob", room_id=room2)
        files = self.db.get_files()
        self.assertEqual(len(files), 2)

    def test_delete_file(self):
        file_id = self.db.save_file("test.png", "abc_test.png", 1024, "alice")
        saved_as = self.db.delete_file(file_id)
        self.assertEqual(saved_as, "abc_test.png")
        files = self.db.get_files()
        self.assertEqual(len(files), 0)

    def test_count_files(self):
        self.db.save_file("a.png", "1_a.png", 100, "alice")
        self.db.save_file("b.pdf", "2_b.pdf", 200, "bob")
        self.assertEqual(self.db.count_files(), 2)

    def test_get_files_by_room(self):
        self.db.save_file("a.png", "1_a.png", 100, "alice", room_id=1)
        files = self.db.get_files_by_room(1)
        self.assertEqual(len(files), 1)


class TestRecordingManagement(TestDatabaseBase):
    """Tests for call recording tracking."""

    def test_save_recording(self):
        rec_id = self.db.save_recording("alice", "bob", "video", "rec_001.webm", 5000, 120)
        self.assertIsNotNone(rec_id)

    def test_get_recordings(self):
        self.db.save_recording("alice", "bob", "video", "rec_001.webm", 5000, 120)
        self.db.save_recording("bob", "charlie", "audio", "rec_002.webm", 2000, 60)
        recs = self.db.get_recordings()
        self.assertEqual(len(recs), 2)

    def test_get_recordings_by_user(self):
        self.db.save_recording("alice", "bob", "video", "rec_001.webm", 5000, 120)
        self.db.save_recording("bob", "charlie", "audio", "rec_002.webm", 2000, 60)
        recs = self.db.get_recordings(username="alice")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["caller"], "alice")

    def test_delete_recording(self):
        rec_id = self.db.save_recording("alice", "bob", "video", "rec_001.webm", 5000, 120)
        filename = self.db.delete_recording(rec_id)
        self.assertEqual(filename, "rec_001.webm")
        recs = self.db.get_recordings()
        self.assertEqual(len(recs), 0)

    def test_count_recordings(self):
        self.db.save_recording("alice", "bob", "video", "rec_001.webm", 5000, 120)
        self.assertEqual(self.db.count_recordings(), 1)


class TestBackupRestore(TestDatabaseBase):
    """Tests for backup and restore functionality."""

    def test_create_backup(self):
        self.db.register_user("alice", "pass123")
        self.db.save_message("alice", "hello", room_id=1)

        backup_dir = os.path.join(self.test_dir, "backups")
        result = self.db.create_backup(backup_dir, "test backup")
        self.assertIn("filename", result)
        self.assertIn("size", result)
        self.assertGreater(result["size"], 0)

        # Backup file should exist
        backup_path = os.path.join(backup_dir, result["filename"])
        self.assertTrue(os.path.isfile(backup_path))

    def test_get_backups(self):
        backup_dir = os.path.join(self.test_dir, "backups")
        self.db.create_backup(backup_dir, "backup 1")
        self.db.create_backup(backup_dir, "backup 2")
        backups = self.db.get_backups()
        self.assertEqual(len(backups), 2)

    def test_restore_backup(self):
        self.db.register_user("alice", "pass123")
        self.db.save_message("alice", "before backup", room_id=1)

        backup_dir = os.path.join(self.test_dir, "backups")
        result = self.db.create_backup(backup_dir, "test")

        # Add more data after backup
        self.db.register_user("bob", "pass456")
        self.db.save_message("bob", "after backup", room_id=1)
        # 11 default seeded users + alice + bob = 13
        self.assertEqual(self.db.count_users(), 13)

        # Restore
        success = self.db.restore_backup(backup_dir, result["filename"])
        self.assertTrue(success)

        # Should have only alice + 11 defaults (pre-backup state)
        self.assertEqual(self.db.count_users(), 12)
        self.assertTrue(self.db.user_exists("alice"))
        self.assertFalse(self.db.user_exists("bob"))

    def test_restore_nonexistent_backup(self):
        backup_dir = os.path.join(self.test_dir, "backups")
        os.makedirs(backup_dir, exist_ok=True)
        result = self.db.restore_backup(backup_dir, "nonexistent.db")
        self.assertFalse(result)

    def test_delete_backup_record(self):
        backup_dir = os.path.join(self.test_dir, "backups")
        self.db.create_backup(backup_dir, "test")
        backups = self.db.get_backups()
        self.assertEqual(len(backups), 1)

        filename = self.db.delete_backup_record(backups[0]["id"])
        self.assertIsNotNone(filename)
        backups = self.db.get_backups()
        self.assertEqual(len(backups), 0)


class TestSettings(TestDatabaseBase):
    """Tests for key-value settings storage."""

    def test_set_and_get_setting(self):
        self.db.set_setting("theme", "dark")
        self.assertEqual(self.db.get_setting("theme"), "dark")

    def test_get_setting_default(self):
        result = self.db.get_setting("nonexistent", default="fallback")
        self.assertEqual(result, "fallback")

    def test_get_setting_none_default(self):
        result = self.db.get_setting("nonexistent")
        self.assertIsNone(result)

    def test_update_setting(self):
        self.db.set_setting("theme", "dark")
        self.db.set_setting("theme", "light")
        self.assertEqual(self.db.get_setting("theme"), "light")

    def test_get_all_settings(self):
        self.db.set_setting("theme", "dark")
        self.db.set_setting("lang", "en")
        settings = self.db.get_all_settings()
        self.assertEqual(settings["theme"], "dark")
        self.assertEqual(settings["lang"], "en")


class TestStats(TestDatabaseBase):
    """Tests for statistics methods."""

    def test_count_users(self):
        # 11 default seeded users exist on fresh DB
        self.assertEqual(self.db.count_users(), 11)
        self.db.register_user("alice", "pass123")
        self.assertEqual(self.db.count_users(), 12)

    def test_count_banned(self):
        self.db.register_user("alice", "pass123")
        self.db.register_user("bob", "pass123")
        self.assertEqual(self.db.count_banned(), 0)
        self.db.ban_user("alice")
        self.assertEqual(self.db.count_banned(), 1)

    def test_get_db_size(self):
        size = self.db.get_db_size()
        self.assertGreater(size, 0)


class TestDatabaseSchema(TestDatabaseBase):
    """Tests for database schema and migration."""

    def test_tables_created(self):
        conn = self.db._get_conn()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = [t["name"] for t in tables]
        self.assertIn("users", table_names)
        self.assertIn("rooms", table_names)
        self.assertIn("room_members", table_names)
        self.assertIn("messages", table_names)
        self.assertIn("files", table_names)
        self.assertIn("settings", table_names)
        self.assertIn("recordings", table_names)
        self.assertIn("backups", table_names)

    def test_indexes_created(self):
        conn = self.db._get_conn()
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
        index_names = [i["name"] for i in indexes]
        self.assertIn("idx_messages_room", index_names)
        self.assertIn("idx_messages_sender", index_names)
        self.assertIn("idx_messages_target", index_names)
        self.assertIn("idx_messages_ts", index_names)


if __name__ == "__main__":
    unittest.main()
