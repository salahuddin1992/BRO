"""Tests for security features: XSS, path traversal, auth, headers, crypto AAD, mesh, SFU."""
import os
import sys
import time

# Ensure project root on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from markupsafe import escape as html_escape


class TestXSSSanitization:
    """Test XSS prevention in messages."""

    def test_html_escape_script_tag(self):
        text = '<script>alert("xss")</script>'
        sanitized = str(html_escape(text))
        assert "<script>" not in sanitized
        assert "&lt;script&gt;" in sanitized

    def test_html_escape_img_onerror(self):
        text = '<img src=x onerror=alert(1)>'
        sanitized = str(html_escape(text))
        assert "<img" not in sanitized
        assert "&lt;img" in sanitized

    def test_html_escape_preserves_normal_text(self):
        text = "مرحبا! Hello, how are you?"
        sanitized = str(html_escape(text))
        assert sanitized == text

    def test_html_escape_preserves_arabic(self):
        text = "مرحبا بالعالم 123"
        sanitized = str(html_escape(text))
        assert sanitized == text

    def test_html_escape_ampersand(self):
        text = "A & B"
        sanitized = str(html_escape(text))
        assert "&amp;" in sanitized

    def test_html_escape_quotes(self):
        text = 'He said "hello"'
        sanitized = str(html_escape(text))
        assert '"' not in sanitized or "&#34;" in sanitized

    def test_html_escape_nested_xss(self):
        text = '<div onmouseover="alert(1)">click</div>'
        sanitized = str(html_escape(text))
        assert "onmouseover" not in sanitized or "&lt;div" in sanitized

    def test_html_escape_javascript_url(self):
        text = '<a href="javascript:alert(1)">link</a>'
        sanitized = str(html_escape(text))
        assert "javascript:" not in sanitized or "&lt;a" in sanitized


class TestPathTraversal:
    """Test path traversal protection."""

    def test_secure_filename_removes_path(self):
        from werkzeug.utils import secure_filename
        assert secure_filename("../../../etc/passwd") == "etc_passwd"
        assert secure_filename("..\\..\\windows\\system32") == "windowssystem32"

    def test_secure_filename_removes_dots(self):
        from werkzeug.utils import secure_filename
        assert ".." not in secure_filename("../file.txt")

    def test_secure_filename_preserves_extension(self):
        from werkzeug.utils import secure_filename
        assert secure_filename("photo.jpg") == "photo.jpg"

    def test_secure_filename_handles_unicode(self):
        from werkzeug.utils import secure_filename
        # secure_filename strips non-ASCII by default
        result = secure_filename("ملف.pdf")
        assert result  # Should not be empty (returns something)

    def test_path_stays_in_directory(self):
        """Test that os.path.realpath prevents directory escape."""
        base = "/tmp/uploads"
        filename = "../../etc/passwd"
        fpath = os.path.join(base, filename)
        real = os.path.realpath(fpath)
        assert not real.startswith(os.path.realpath(base))

    def test_normal_path_stays_in_directory(self):
        """Normal filenames should stay in the directory."""
        base = "/tmp/uploads"
        filename = "photo_12345.jpg"
        fpath = os.path.join(base, filename)
        real = os.path.realpath(fpath)
        assert real.startswith(os.path.realpath(base))


class TestPasswordPolicy:
    """Test password validation policy."""

    def test_short_password_rejected(self):
        from server.bro_server import BROServer
        ok, err = BROServer._validate_password("ab1")
        assert ok is False
        assert "قصيرة" in err

    def test_no_digits_rejected(self):
        from server.bro_server import BROServer
        ok, err = BROServer._validate_password("abcdef")
        assert ok is False
        assert "حروف وأرقام" in err

    def test_no_letters_rejected(self):
        from server.bro_server import BROServer
        ok, err = BROServer._validate_password("123456")
        assert ok is False
        assert "حروف وأرقام" in err

    def test_valid_password_accepted(self):
        from server.bro_server import BROServer
        ok, err = BROServer._validate_password("abc123")
        assert ok is True
        assert err == ""

    def test_strong_password_accepted(self):
        from server.bro_server import BROServer
        ok, err = BROServer._validate_password("MyStr0ngP@ss")
        assert ok is True


class TestUsernameValidation:
    """Test username validation policy."""

    def test_short_username_rejected(self):
        from server.bro_server import BROServer
        ok, err = BROServer._validate_username("a")
        assert ok is False

    def test_empty_username_rejected(self):
        from server.bro_server import BROServer
        ok, err = BROServer._validate_username("")
        assert ok is False

    def test_long_username_rejected(self):
        from server.bro_server import BROServer
        ok, err = BROServer._validate_username("a" * 31)
        assert ok is False

    def test_valid_english_username(self):
        from server.bro_server import BROServer
        ok, err = BROServer._validate_username("john_doe")
        assert ok is True

    def test_valid_arabic_username(self):
        from server.bro_server import BROServer
        ok, err = BROServer._validate_username("محمد")
        assert ok is True

    def test_valid_mixed_username(self):
        from server.bro_server import BROServer
        ok, err = BROServer._validate_username("user-123")
        assert ok is True

    def test_special_chars_rejected(self):
        from server.bro_server import BROServer
        ok, err = BROServer._validate_username("user@name")
        assert ok is False

    def test_script_injection_rejected(self):
        from server.bro_server import BROServer
        ok, err = BROServer._validate_username("<script>alert(1)</script>")
        assert ok is False


class TestSecurityHeaders:
    """Test that security-related configs exist."""

    def test_tls_config_exists(self):
        import config
        assert hasattr(config, "TLS_CERT")
        assert hasattr(config, "TLS_KEY")
        assert hasattr(config, "TLS_AVAILABLE")

    def test_tls_certs_generated(self):
        import config
        assert config.TLS_AVAILABLE is True
        assert os.path.isfile(config.TLS_CERT)
        assert os.path.isfile(config.TLS_KEY)

    def test_secret_key_strong(self):
        import config
        assert len(config.SECRET_KEY) >= 32

    def test_password_policy_config(self):
        import config
        assert config.PASSWORD_MIN_LENGTH >= 6
        assert config.PASSWORD_REQUIRE_MIXED is True

    def test_max_file_size_set(self):
        import config
        assert config.MAX_FILE_SIZE == 100 * 1024 * 1024  # 100MB

    def test_allowed_extensions_no_executables(self):
        from server.bro_server import ALLOWED_EXTENSIONS
        dangerous = {"exe", "bat", "cmd", "com", "scr", "msi", "dll", "vbs", "ps1", "sh"}
        assert not ALLOWED_EXTENSIONS.intersection(dangerous)


class TestCORSConfig:
    """Test CORS is properly restricted."""

    def test_cors_patterns_are_local_only(self):
        """CORS patterns should only match private network IPs."""
        import re
        cors_origins = [
            r"https?://127\.0\.0\.1(:\d+)?",
            r"https?://localhost(:\d+)?",
            r"https?://192\.168\.\d+\.\d+(:\d+)?",
            r"https?://10\.\d+\.\d+\.\d+(:\d+)?",
            r"https?://172\.(1[6-9]|2\d|3[01])\.\d+\.\d+(:\d+)?",
        ]
        # Should match local
        local_origins = [
            "http://127.0.0.1:8400",
            "https://localhost:8400",
            "http://192.168.1.100:8400",
            "http://10.0.0.1:8400",
            "http://172.16.0.1:8400",
        ]
        for origin in local_origins:
            matched = any(re.fullmatch(p, origin) for p in cors_origins)
            assert matched, f"Local origin {origin} should match CORS"

        # Should NOT match external
        external_origins = [
            "http://evil.com",
            "http://8.8.8.8:8400",
            "http://203.0.113.1:8400",
        ]
        for origin in external_origins:
            matched = any(re.fullmatch(p, origin) for p in cors_origins)
            assert not matched, f"External origin {origin} should NOT match CORS"


class TestCryptoAAD:
    """Test E2E encryption with AAD (Associated Authenticated Data)."""

    def test_encrypt_decrypt_without_aad(self):
        """Basic encrypt/decrypt without AAD still works."""
        from utils.crypto import encrypt, decrypt, generate_keypair, derive_shared_key
        priv_a, pub_a = generate_keypair()
        priv_b, pub_b = generate_keypair()
        key = derive_shared_key(priv_a, pub_b)
        ct = encrypt(key, "hello world")
        pt = decrypt(key, ct)
        assert pt == "hello world"

    def test_encrypt_decrypt_with_aad(self):
        """Encrypt/decrypt with AAD context binding."""
        from utils.crypto import encrypt, decrypt, generate_keypair, derive_shared_key
        priv_a, pub_a = generate_keypair()
        priv_b, pub_b = generate_keypair()
        key = derive_shared_key(priv_a, pub_b)
        aad = "sender:alice,receiver:bob"
        ct = encrypt(key, "secret message", aad=aad)
        pt = decrypt(key, ct, aad=aad)
        assert pt == "secret message"

    def test_aad_mismatch_fails(self):
        """Decryption with wrong AAD should fail."""
        from utils.crypto import encrypt, decrypt, generate_keypair, derive_shared_key
        priv_a, pub_a = generate_keypair()
        priv_b, pub_b = generate_keypair()
        key = derive_shared_key(priv_a, pub_b)
        ct = encrypt(key, "secret", aad="correct-context")
        with pytest.raises(Exception):
            decrypt(key, ct, aad="wrong-context")

    def test_aad_missing_fails(self):
        """Encrypted with AAD but decrypted without should fail."""
        from utils.crypto import encrypt, decrypt, generate_keypair, derive_shared_key
        priv_a, pub_a = generate_keypair()
        priv_b, pub_b = generate_keypair()
        key = derive_shared_key(priv_a, pub_b)
        ct = encrypt(key, "secret", aad="some-context")
        with pytest.raises(Exception):
            decrypt(key, ct)  # no AAD

    def test_encrypt_decrypt_file_with_aad(self):
        """File encryption/decryption with AAD."""
        import tempfile
        from utils.crypto import encrypt_file, decrypt_file, generate_keypair, derive_shared_key
        priv_a, pub_a = generate_keypair()
        priv_b, pub_b = generate_keypair()
        key = derive_shared_key(priv_a, pub_b)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            f.write(b"file content here")
            orig_path = f.name
        enc_path = orig_path + ".enc"
        dec_path = orig_path + ".dec"

        try:
            encrypt_file(key, orig_path, enc_path, aad="file:test.txt")
            decrypt_file(key, enc_path, dec_path, aad="file:test.txt")
            with open(dec_path, "rb") as f:
                assert f.read() == b"file content here"
        finally:
            for p in [orig_path, enc_path, dec_path]:
                try:
                    os.unlink(p)
                except OSError:
                    pass

    def test_file_aad_mismatch_fails(self):
        """File decryption with wrong AAD should fail."""
        import tempfile
        from utils.crypto import encrypt_file, decrypt_file, generate_keypair, derive_shared_key
        priv_a, pub_a = generate_keypair()
        priv_b, pub_b = generate_keypair()
        key = derive_shared_key(priv_a, pub_b)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            f.write(b"data")
            orig_path = f.name
        enc_path = orig_path + ".enc"
        dec_path = orig_path + ".dec"

        try:
            encrypt_file(key, orig_path, enc_path, aad="correct")
            with pytest.raises(Exception):
                decrypt_file(key, enc_path, dec_path, aad="wrong")
        finally:
            for p in [orig_path, enc_path, dec_path]:
                try:
                    os.unlink(p)
                except OSError:
                    pass


class TestSFURoomLimit:
    """Test SFU room size limit."""

    def test_max_room_size_constant(self):
        from network.sfu import MAX_ROOM_SIZE
        assert MAX_ROOM_SIZE >= 10
        assert MAX_ROOM_SIZE <= 50

    def test_room_rejects_when_full(self):
        from network.sfu import SFURoom, MAX_ROOM_SIZE
        room = SFURoom("test-room")
        for i in range(MAX_ROOM_SIZE):
            result = room.add_participant(f"sid_{i}", f"user_{i}")
            assert result is not None
        # Next one should be rejected
        result = room.add_participant("overflow", "overflow_user")
        assert result is None

    def test_room_accepts_after_leave(self):
        from network.sfu import SFURoom, MAX_ROOM_SIZE
        room = SFURoom("test-room")
        for i in range(MAX_ROOM_SIZE):
            room.add_participant(f"sid_{i}", f"user_{i}")
        # Remove one
        room.remove_participant("sid_0")
        # Now should accept
        result = room.add_participant("new_sid", "new_user")
        assert result is not None


class TestMeshReplayProtection:
    """Test mesh UDP replay protection."""

    def test_mesh_node_imports(self):
        from mesh.mesh_node import MeshNode
        node = MeshNode("test-id", "127.0.0.1", 8400)
        assert node.server_id == "test-id"

    def test_sign_verify_message(self):
        """Test HMAC sign and verify round-trip."""
        import msgpack
        from mesh.mesh_node import MeshNode
        node = MeshNode("test-id", "127.0.0.1", 8400)
        msg = {"type": "announce", "server_id": "test", "ts": time.time()}
        data = msgpack.packb(msg, use_bin_type=True)
        signed = node._sign_message(data)
        result = node._verify_message(signed)
        assert result is not None

    def test_reject_tampered_message(self):
        """Tampered messages should be rejected."""
        import msgpack
        from mesh.mesh_node import MeshNode
        node = MeshNode("test-id", "127.0.0.1", 8400)
        msg = {"type": "announce", "server_id": "test", "ts": time.time()}
        data = msgpack.packb(msg, use_bin_type=True)
        signed = node._sign_message(data)
        # Tamper with the payload
        tampered = signed[:32] + b'\x00' + signed[33:]
        result = node._verify_message(tampered)
        assert result is None

    def test_reject_old_message(self):
        """Messages older than 30s should be rejected (replay protection)."""
        import msgpack
        from mesh.mesh_node import MeshNode
        node = MeshNode("test-id", "127.0.0.1", 8400)
        msg = {"type": "announce", "server_id": "test", "ts": time.time() - 60}
        data = msgpack.packb(msg, use_bin_type=True)
        signed = node._sign_message(data)
        result = node._verify_message(signed)
        assert result is None


class TestWebSocketMeshHeartbeat:
    """Test WebSocket mesh heartbeat mechanism."""

    def test_ws_mesh_init(self):
        from network.ws_mesh import WebSocketMeshBridge
        bridge = WebSocketMeshBridge("test-id", "127.0.0.1", 8400, "secret")
        assert bridge.server_id == "test-id"
        assert bridge.ws_port == 8402

    def test_ws_mesh_stats(self):
        from network.ws_mesh import WebSocketMeshBridge
        bridge = WebSocketMeshBridge("test-id", "127.0.0.1", 8400, "secret")
        stats = bridge.get_stats()
        assert "connected_peers" in stats
        assert stats["compression"] is True


class TestDatabaseIndices:
    """Test that database has proper indices."""

    def test_indices_created(self):
        import tempfile
        from database.db import Database
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            db = Database(db_path)
            conn = db._get_conn()
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
            index_names = [r["name"] for r in rows]
            assert "idx_messages_room" in index_names
            assert "idx_messages_sender" in index_names
            assert "idx_files_uploaded_by" in index_names
            assert "idx_room_members_username" in index_names
        finally:
            os.unlink(db_path)
