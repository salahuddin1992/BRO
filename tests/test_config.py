"""
Helen WiFi - Configuration Unit Tests
Tests for config.py: Configuration values and paths
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config


class TestConfig(unittest.TestCase):
    """Tests for configuration module."""

    def test_base_path_exists(self):
        self.assertTrue(os.path.isdir(config.BASE_PATH))

    def test_runtime_path_exists(self):
        self.assertTrue(os.path.isdir(config.RUNTIME_PATH))

    def test_server_host(self):
        self.assertEqual(config.SERVER_HOST, "0.0.0.0")

    def test_server_port(self):
        self.assertIsInstance(config.SERVER_PORT, int)
        self.assertGreater(config.SERVER_PORT, 0)
        self.assertLess(config.SERVER_PORT, 65536)

    def test_secret_key_exists(self):
        self.assertIsInstance(config.SECRET_KEY, str)
        self.assertGreater(len(config.SECRET_KEY), 0)

    def test_admin_credentials(self):
        self.assertIsInstance(config.ADMIN_USERNAME, str)
        self.assertIsInstance(config.ADMIN_PASSWORD, str)
        self.assertGreater(len(config.ADMIN_USERNAME), 0)
        self.assertGreater(len(config.ADMIN_PASSWORD), 0)

    def test_mesh_config(self):
        self.assertIsInstance(config.MESH_PORT, int)
        self.assertIsInstance(config.MESH_MAX_SERVERS, int)
        self.assertGreater(config.MESH_PORT, 0)
        self.assertGreater(config.MESH_MAX_SERVERS, 0)

    def test_upload_folder_exists(self):
        self.assertTrue(os.path.isdir(config.UPLOAD_FOLDER))

    def test_db_path(self):
        self.assertIsInstance(config.DB_PATH, str)
        self.assertTrue(config.DB_PATH.endswith(".db"))

    def test_ice_servers_is_list(self):
        self.assertIsInstance(config.ICE_SERVERS, list)

    def test_fiber_types(self):
        self.assertIsInstance(config.FIBER_TYPES, dict)
        self.assertIn("GPON", config.FIBER_TYPES)
        self.assertIn("EPON", config.FIBER_TYPES)
        self.assertIn("SFP", config.FIBER_TYPES)
        self.assertIn("FTTH", config.FIBER_TYPES)

    def test_log_level(self):
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        self.assertIn(config.LOG_LEVEL, valid_levels)

    def test_log_file_path(self):
        self.assertIsInstance(config.LOG_FILE, str)
        self.assertTrue(config.LOG_FILE.endswith(".log"))


if __name__ == "__main__":
    unittest.main()
