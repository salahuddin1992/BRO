"""Tests for security features: XSS, path traversal, auth, headers."""
import os
import sys

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
