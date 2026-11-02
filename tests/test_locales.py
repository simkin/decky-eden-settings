"""Every locale must cover exactly the keys of English and keep its {placeholders}; English must cover the schema."""
import glob
import json
import os
import re
import sys
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "py_modules"))
import eden_cfg as E  # noqa: E402

LOCALES = {os.path.basename(p)[:-5]: json.load(open(p, encoding="utf-8"))
           for p in glob.glob(os.path.join(ROOT, "src", "locales", "*.json"))}
EN = LOCALES["en"]
PLACEHOLDER = re.compile(r"\{(\w+)\}")
# The "Global (value)" entry in a dropdown button has room for roughly this many characters.
MAX_OPTION_LABEL = 22


class TestLocales(unittest.TestCase):
    def test_english_exists_and_other_locales_present(self):
        self.assertIn("en", LOCALES)
        self.assertGreaterEqual(len(LOCALES), 5)

    def test_same_keys_as_english(self):
        for lang, d in LOCALES.items():
            self.assertEqual(sorted(set(EN) - set(d)), [], f"{lang}: missing keys")
            self.assertEqual(sorted(set(d) - set(EN)), [], f"{lang}: unknown keys")

    def test_no_empty_strings(self):
        for lang, d in LOCALES.items():
            for k, v in d.items():
                self.assertTrue(v.strip(), f"{lang}:{k} is empty")

    def test_placeholders_match_english(self):
        for lang, d in LOCALES.items():
            for k, v in d.items():
                self.assertEqual(set(PLACEHOLDER.findall(v)), set(PLACEHOLDER.findall(EN[k])), f"{lang}:{k}")

    def test_english_covers_every_setting_and_option(self):
        for s in E.SETTINGS:
            self.assertIn(f"setting.{s['key']}.label", EN)
            self.assertIn(f"setting.{s['key']}.desc", EN)
            self.assertIn(f"group.{s['group']}", EN)
            for v in s["options"]:
                self.assertIn(f"option.{s['key']}.{v}", EN, f"{s['key']}={v}")

    def test_no_orphan_option_labels(self):
        valid = {f"option.{s['key']}.{v}" for s in E.SETTINGS for v in s["options"]}
        for k in EN:
            if k.startswith("option."):
                self.assertIn(k, valid)

    def test_option_labels_fit_a_dropdown_button(self):
        for lang, d in LOCALES.items():
            for k, v in d.items():
                if k.startswith("option."):
                    self.assertLessEqual(len(v), MAX_OPTION_LABEL, f"{lang}:{k} '{v}' will be cut off")


if __name__ == "__main__":
    unittest.main()
