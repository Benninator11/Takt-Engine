import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from takt_engine.gui import i18n


class TranslationTests(unittest.TestCase):
    def test_fixed_labels_translate_in_both_directions(self):
        self.assertEqual(i18n.translate_text("Übertakten", "en"), "Overclocking")
        self.assertEqual(i18n.translate_text("Overclocking", "de"), "Übertakten")
        self.assertEqual(i18n.translate_text("Voreinstellungen", "en"), "Presets")

    def test_dynamic_values_keep_numbers_and_translate_labels(self):
        german = "Zielwert Stufe 2: 55 %"
        english = i18n.translate_text(german, "en")
        self.assertEqual(english, "Target Stage 2: 55 %")
        self.assertEqual(i18n.translate_text(english, "de"), german)

    def test_word_boundaries_do_not_modify_unrelated_words(self):
        self.assertEqual(i18n.translate_text("Jahr 2026", "en"), "Jahr 2026")

    def test_language_setting_is_persisted_separately(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "ui-settings.json"
            with patch.object(i18n, "UI_SETTINGS_PATH", settings_path):
                i18n.save_ui_language("en")
                self.assertEqual(i18n.load_ui_language(), "en")
                i18n.save_ui_language("de")
                self.assertEqual(i18n.load_ui_language(), "de")

    def test_invalid_language_is_rejected(self):
        with self.assertRaises(ValueError):
            i18n.save_ui_language("fr")


if __name__ == "__main__":
    unittest.main()
