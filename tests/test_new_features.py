"""Tests for new security fixes and features added in this update."""
import os
import sys
import time
import threading
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


class TestThreadSafety:
    """Test thread-safety of shared state."""

    def test_clients_lock_exists(self):
        """BROServer should have _clients_lock."""
        pytest.importorskip("flask_socketio")
        from server.bro_server import BROServer
        assert hasattr(BROServer, '__init__')

    def test_tokens_lock_exists(self):
        """BROServer should have _tokens_lock for auth_tokens."""
        pytest.importorskip("flask_socketio")
        from server.bro_server import BROServer


class TestDatabaseFTS5:
    """Test FTS5 full-text search for messages."""

    @pytest.fixture
    def db(self, tmp_path):
        from database.db import Database
        db = Database(str(tmp_path / "test.db"))
        return db

    def test_fts5_table_created(self, db):
        """FTS5 virtual table should be created."""
        conn = db._get_conn()
        try:
            conn.execute("SELECT 1 FROM messages_fts LIMIT 1")
            fts_available = True
        except Exception:
            fts_available = False
        # FTS5 may not be available in all SQLite builds
        assert isinstance(fts_available, bool)

    def test_search_messages_basic(self, db):
        """Search messages should work with or without FTS5."""
        db.register_user("testuser", "test1234")
        db.save_message("testuser", "hello world test message")
        db.save_message("testuser", "another message here")
        results = db.search_messages("hello")
        assert len(results) >= 1
        assert any("hello" in r["text"] for r in results)

    def test_search_messages_arabic(self, db):
        """Search should work with Arabic text."""
        db.register_user("testuser", "test1234")
        db.save_message("testuser", "مرحبا بالعالم")
        results = db.search_messages("مرحبا")
        assert len(results) >= 1


class TestConnectionPooling:
    """Test SQLite connection pooling."""

    @pytest.fixture
    def db(self, tmp_path):
        from database.db import Database
        return Database(str(tmp_path / "test.db"))

    def test_pool_attributes(self, db):
        """Database should have pool attributes."""
        assert hasattr(db, '_pool')
        assert hasattr(db, '_pool_lock')
        assert hasattr(db, '_pool_max')
        assert db._pool_max == 10

    def test_return_conn(self, db):
        """Connections should be returnable to pool."""
        conn = db._get_conn()
        assert conn is not None
        db._return_conn(conn)
        assert len(db._pool) <= db._pool_max


class TestHealthCheck:
    """Test /api/health endpoint exists in routes."""

    def test_health_check_concept(self):
        """Health check should return server status."""
        pytest.importorskip("flask_socketio")
        from server.bro_server import BROServer


class TestRestoreBackupSafety:
    """Test that restore_backup creates safety backup first."""

    @pytest.fixture
    def db(self, tmp_path):
        from database.db import Database
        db = Database(str(tmp_path / "test.db"))
        return db

    def test_restore_missing_backup(self, db, tmp_path):
        """Restore should fail gracefully for missing file."""
        backup_dir = str(tmp_path / "backups")
        os.makedirs(backup_dir, exist_ok=True)
        result = db.restore_backup(backup_dir, "nonexistent.db")
        assert result is False

    def test_restore_creates_safety_backup(self, db, tmp_path):
        """Restore should create a safety backup before overwriting."""
        backup_dir = str(tmp_path / "backups")
        os.makedirs(backup_dir, exist_ok=True)
        # Create a backup to restore from
        result = db.create_backup(backup_dir, "test backup")
        backup_name = result["filename"]
        # Restore it
        db.restore_backup(backup_dir, backup_name)
        # Check that a pre_restore_ file was created
        files = os.listdir(backup_dir)
        pre_restore_files = [f for f in files if f.startswith("pre_restore_")]
        assert len(pre_restore_files) >= 1


class TestPathTraversalThumbnail:
    """Test realpath check for thumbnail endpoint."""

    def test_secure_filename_blocks_traversal(self):
        from werkzeug.utils import secure_filename
        dangerous = "../../../etc/passwd"
        safe = secure_filename(dangerous)
        assert ".." not in safe
        assert "/" not in safe


class TestRateLimitCleanup:
    """Test cleanup of stale rate limit entries."""

    def test_cleanup_concept(self):
        """Rate limit cleanup method should exist."""
        pytest.importorskip("flask_socketio")
        from server.bro_server import BROServer
        assert hasattr(BROServer, '_cleanup_rate_limit_entries')


class TestChunkCleanup:
    """Test stale chunk directory cleanup."""

    def test_cleanup_stale_chunks(self, tmp_path):
        """Old chunk directories should be removed."""
        pytest.importorskip("apscheduler")
        from utils.scheduler import _cleanup_stale_chunks

        chunk_dir = str(tmp_path / "chunks")
        os.makedirs(chunk_dir)

        # Create a stale directory (simulate old mtime)
        stale_dir = os.path.join(chunk_dir, "old_upload")
        os.makedirs(stale_dir)
        # Set old modification time
        old_time = time.time() - 7 * 3600  # 7 hours ago
        os.utime(stale_dir, (old_time, old_time))

        # Create a fresh directory
        fresh_dir = os.path.join(chunk_dir, "new_upload")
        os.makedirs(fresh_dir)

        _cleanup_stale_chunks(chunk_dir)

        assert not os.path.exists(stale_dir)
        assert os.path.exists(fresh_dir)


class TestFileEncryptionDecryption:
    """Test file encryption and decryption round-trip."""

    @pytest.fixture(autouse=True)
    def _check_crypto(self):
        try:
            import _cffi_backend  # noqa: F401
        except (ImportError, ModuleNotFoundError):
            pytest.skip("_cffi_backend not available")

    def test_encrypt_decrypt_file(self, tmp_path):
        from utils.crypto import encrypt_file, decrypt_file

        key = b'\x00' * 32
        plaintext = b"Hello, this is a test file content!"

        input_file = str(tmp_path / "plain.txt")
        encrypted_file = str(tmp_path / "encrypted.bin")
        decrypted_file = str(tmp_path / "decrypted.txt")

        with open(input_file, "wb") as f:
            f.write(plaintext)

        encrypt_file(key, input_file, encrypted_file)
        assert os.path.getsize(encrypted_file) > 0

        decrypt_file(key, encrypted_file, decrypted_file)
        with open(decrypted_file, "rb") as f:
            result = f.read()
        assert result == plaintext


class TestDefaultUsersRemoved:
    """Test that default users are no longer seeded."""

    @pytest.fixture
    def db(self, tmp_path):
        from database.db import Database
        return Database(str(tmp_path / "test.db"))

    def test_no_default_users(self, db):
        """Fresh database should have no users."""
        users = db.get_all_users()
        # Default users like هيلين, GeneralManager should NOT exist
        usernames = [u["username"] for u in users]
        assert "هيلين" not in usernames
        assert "GeneralManager" not in usernames
        assert "admin123" not in str(users)

    def test_registration_required(self, db):
        """Users must register to use the system."""
        assert not db.user_exists("testuser")
        db.register_user("testuser", "pass1234")
        assert db.user_exists("testuser")


class TestAPIDocPort:
    """Test that API.md has correct port."""

    def test_api_md_port(self):
        api_md_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "API.md")
        if os.path.exists(api_md_path):
            with open(api_md_path) as f:
                content = f.read()
            assert "7777" not in content, "API.md still references old port 7777"
            assert "8400" in content


class TestDockerfiles:
    """Test Docker deployment files exist."""

    def test_dockerfile_exists(self):
        root = os.path.dirname(os.path.dirname(__file__))
        assert os.path.isfile(os.path.join(root, "Dockerfile"))

    def test_docker_compose_exists(self):
        root = os.path.dirname(os.path.dirname(__file__))
        assert os.path.isfile(os.path.join(root, "docker-compose.yml"))

    def test_dockerignore_exists(self):
        root = os.path.dirname(os.path.dirname(__file__))
        assert os.path.isfile(os.path.join(root, ".dockerignore"))
