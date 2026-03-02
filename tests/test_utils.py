"""
Helen WiFi - Tests for utility modules
"""
import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestCrypto:
    def test_generate_keypair(self):
        from utils.crypto import generate_keypair
        private_key, public_b64 = generate_keypair()
        assert private_key is not None
        assert len(public_b64) > 0

    def test_encrypt_decrypt(self):
        from utils.crypto import generate_keypair, derive_shared_key, encrypt, decrypt

        # Simulate two parties
        priv_a, pub_a = generate_keypair()
        priv_b, pub_b = generate_keypair()

        # Derive shared keys (should be identical)
        key_a = derive_shared_key(priv_a, pub_b)
        key_b = derive_shared_key(priv_b, pub_a)
        assert key_a == key_b

        # Encrypt/decrypt
        plaintext = "مرحبا بالعالم - Hello World!"
        ciphertext = encrypt(key_a, plaintext)
        assert ciphertext != plaintext
        decrypted = decrypt(key_b, ciphertext)
        assert decrypted == plaintext

    def test_encrypt_decrypt_file(self):
        from utils.crypto import generate_keypair, derive_shared_key, encrypt_file, decrypt_file

        priv_a, pub_a = generate_keypair()
        priv_b, pub_b = generate_keypair()
        key = derive_shared_key(priv_a, pub_b)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            f.write(b"test file content")
            input_path = f.name

        encrypted_path = input_path + ".enc"
        decrypted_path = input_path + ".dec"

        try:
            encrypt_file(key, input_path, encrypted_path)
            assert os.path.exists(encrypted_path)

            decrypt_file(key, encrypted_path, decrypted_path)
            with open(decrypted_path, "rb") as f:
                assert f.read() == b"test file content"
        finally:
            for p in [input_path, encrypted_path, decrypted_path]:
                if os.path.exists(p):
                    os.remove(p)


class TestCompression:
    def test_compress_decompress_data(self):
        from utils.compression import compress_data, decompress_data

        original = b"Hello World! " * 100
        compressed = compress_data(original)
        assert len(compressed) < len(original)
        decompressed = decompress_data(compressed)
        assert decompressed == original

    def test_should_compress(self):
        from utils.compression import should_compress

        assert should_compress("readme.txt", 5000) is True
        assert should_compress("data.json", 2000) is True
        assert should_compress("image.png", 5000) is False
        assert should_compress("small.txt", 500) is False

    def test_compress_decompress_file(self):
        from utils.compression import compress_file, decompress_file

        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            content = b"test content for compression " * 50
            f.write(content)
            input_path = f.name

        compressed_path = input_path + ".zst"
        decompressed_path = input_path + ".decompressed"

        try:
            compress_file(input_path, compressed_path)
            assert os.path.exists(compressed_path)
            assert os.path.getsize(compressed_path) < os.path.getsize(input_path)

            decompress_file(compressed_path, decompressed_path)
            with open(decompressed_path, "rb") as f:
                assert f.read() == content
        finally:
            for p in [input_path, compressed_path, decompressed_path]:
                if os.path.exists(p):
                    os.remove(p)


class TestQRGenerator:
    def test_generate_qr_base64(self):
        from utils.qr_generator import generate_qr_code

        result = generate_qr_code("http://192.168.1.1:8400")
        assert result.startswith("data:image/png;base64,")

    def test_generate_qr_file(self):
        from utils.qr_generator import generate_qr_code

        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as f:
            output_path = f.name

        try:
            result = generate_qr_code("http://192.168.1.1:8400", output_path)
            assert os.path.exists(result)
            assert os.path.getsize(result) > 0
        finally:
            if os.path.exists(output_path):
                os.remove(output_path)


class TestMonitor:
    def test_get_system_stats(self):
        from utils.monitor import get_system_stats

        stats = get_system_stats()
        assert "cpu_percent" in stats
        assert "memory" in stats
        assert "disk" in stats
        assert "network" in stats
        assert stats["memory"]["total"] > 0

    def test_get_process_stats(self):
        from utils.monitor import get_process_stats

        stats = get_process_stats()
        assert "pid" in stats
        assert "memory_mb" in stats
        assert stats["pid"] > 0


class TestThumbnails:
    def test_generate_thumbnail(self):
        from utils.thumbnails import generate_thumbnail
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test image
            img = Image.new("RGB", (800, 600), color="red")
            img.save(os.path.join(tmpdir, "test_image.jpg"))

            thumb = generate_thumbnail(tmpdir, "test_image.jpg")
            assert thumb is not None
            assert thumb.startswith("thumb_")

            # Verify thumbnail exists and is smaller
            thumb_path = os.path.join(tmpdir, "thumbnails", thumb)
            assert os.path.exists(thumb_path)

            with Image.open(thumb_path) as t:
                assert t.width <= 200
                assert t.height <= 200

    def test_non_image_returns_none(self):
        from utils.thumbnails import generate_thumbnail

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a non-image file
            with open(os.path.join(tmpdir, "test.txt"), "w") as f:
                f.write("not an image")

            result = generate_thumbnail(tmpdir, "test.txt")
            assert result is None


class TestDatabase:
    def test_cache_works(self):
        from database.db import Database

        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
            db_path = f.name

        try:
            db = Database(db_path)
            db.register_user("testuser", "pass1234")

            # First call populates cache
            user1 = db.get_user("testuser")
            assert user1 is not None
            assert user1["username"] == "testuser"

            # Second call should hit cache
            user2 = db.get_user("testuser")
            assert user2 is not None
            assert user2["username"] == "testuser"

            # Cache invalidation on ban
            db.ban_user("testuser")
            user3 = db.get_user("testuser")
            assert user3["banned"] == 1
        finally:
            os.remove(db_path)


class TestMsgpack:
    def test_msgpack_roundtrip(self):
        import msgpack

        data = {
            "type": "announce",
            "server_id": "abc123",
            "host": "192.168.1.5",
            "port": 8400,
            "peer_count": 3,
        }
        packed = msgpack.packb(data, use_bin_type=True)
        assert len(packed) < len(str(data).encode())
        unpacked = msgpack.unpackb(packed, raw=False)
        assert unpacked == data
