"""
Helen WiFi - i18n Unit Tests
Tests for static/js/i18n.js translation completeness and consistency
"""
import os
import sys
import re
import json
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestI18NTranslations(unittest.TestCase):
    """Tests for translation file completeness and consistency."""

    @classmethod
    def setUpClass(cls):
        i18n_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "static", "js", "i18n.js"
        )
        with open(i18n_path, "r", encoding="utf-8") as f:
            cls.content = f.read()

        # Extract Arabic keys
        cls.ar_keys = set()
        cls.en_keys = set()

        # Parse translation keys from JS
        in_ar = False
        in_en = False
        brace_depth = 0
        for line in cls.content.split("\n"):
            stripped = line.strip()
            # Detect start of ar/en sections (format: "ar: {" or "en: {")
            if re.match(r"^ar\s*:\s*\{", stripped):
                in_ar = True
                in_en = False
                brace_depth = 1
                continue
            if re.match(r"^en\s*:\s*\{", stripped):
                in_en = True
                in_ar = False
                brace_depth = 1
                continue

            if (in_ar or in_en) and brace_depth > 0:
                brace_depth += stripped.count("{") - stripped.count("}")
                if brace_depth <= 0:
                    if in_ar:
                        in_ar = False
                    if in_en:
                        in_en = False
                    continue

            match = re.match(r"'([^']+)'\s*:", stripped)
            if match:
                key = match.group(1)
                if in_ar:
                    cls.ar_keys.add(key)
                elif in_en:
                    cls.en_keys.add(key)

    def test_both_languages_have_keys(self):
        self.assertGreater(len(self.ar_keys), 0, "Arabic translations should have keys")
        self.assertGreater(len(self.en_keys), 0, "English translations should have keys")

    def test_same_keys_in_both_languages(self):
        missing_in_en = self.ar_keys - self.en_keys
        missing_in_ar = self.en_keys - self.ar_keys
        self.assertEqual(
            missing_in_en, set(),
            f"Keys in Arabic but missing in English: {missing_in_en}"
        )
        self.assertEqual(
            missing_in_ar, set(),
            f"Keys in English but missing in Arabic: {missing_in_ar}"
        )

    def test_required_keys_exist(self):
        required = [
            "app_name", "login", "register", "username", "password",
            "settings", "logout", "close", "cancel",
            "online", "offline", "away", "busy",
            "admin", "moderator", "user",
            "rooms", "messages", "files",
            "search", "delete",
        ]
        for key in required:
            self.assertIn(key, self.ar_keys, f"Required key '{key}' missing in Arabic")
            self.assertIn(key, self.en_keys, f"Required key '{key}' missing in English")

    def test_no_empty_translations(self):
        for line in self.content.split("\n"):
            line = line.strip()
            match = re.match(r"'([^']+)'\s*:\s*''", line)
            if match:
                self.fail(f"Empty translation found for key: {match.group(1)}")

    def test_i18n_file_exists(self):
        i18n_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "static", "js", "i18n.js"
        )
        self.assertTrue(os.path.isfile(i18n_path))

    def test_shortcut_function_defined(self):
        self.assertIn("function t(key)", self.content)

    def test_i18n_object_defined(self):
        self.assertIn("const I18N", self.content)

    def test_apply_all_method(self):
        self.assertIn("applyAll", self.content)

    def test_set_lang_method(self):
        self.assertIn("setLang", self.content)

    def test_supports_data_i18n_attribute(self):
        self.assertIn("data-i18n", self.content)


class TestI18NUsage(unittest.TestCase):
    """Tests that i18n is properly integrated in HTML templates."""

    @classmethod
    def setUpClass(cls):
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(base, "templates", "client.html"), "r", encoding="utf-8") as f:
            cls.client_html = f.read()
        with open(os.path.join(base, "templates", "admin.html"), "r", encoding="utf-8") as f:
            cls.admin_html = f.read()

    def test_client_includes_i18n_script(self):
        self.assertIn("i18n.js", self.client_html)

    def test_admin_includes_i18n_script(self):
        self.assertIn("i18n.js", self.admin_html)

    def test_client_has_data_i18n_attributes(self):
        count = self.client_html.count("data-i18n=")
        self.assertGreater(count, 10, "Client should have many data-i18n attributes")

    def test_admin_has_data_i18n_attributes(self):
        count = self.admin_html.count("data-i18n=")
        self.assertGreater(count, 5, "Admin should have data-i18n attributes")

    def test_client_has_language_selector(self):
        self.assertIn("setLang", self.client_html)

    def test_admin_has_language_selector(self):
        self.assertIn("adminLangSelect", self.admin_html)

    def test_client_uses_t_function(self):
        t_calls = len(re.findall(r"\bt\('", self.client_html))
        self.assertGreater(t_calls, 10, "Client JS should use t() function extensively")

    def test_admin_uses_t_function(self):
        t_calls = len(re.findall(r"\bt\('", self.admin_html))
        self.assertGreater(t_calls, 10, "Admin JS should use t() function extensively")

    def test_html_root_has_id(self):
        self.assertIn('id="htmlRoot"', self.client_html)
        self.assertIn('id="htmlRoot"', self.admin_html)


if __name__ == "__main__":
    unittest.main()
