from django.test import SimpleTestCase

from .generator import _detect_reply_language, _system_prompt


class LanguageDetectionTests(SimpleTestCase):
    def test_detects_swahili_from_latest_user_message(self):
        messages = [
            {"role": "user", "content": "Habari, naweza kuchangia damu lini?"},
        ]

        self.assertEqual(_detect_reply_language(messages), "sw")

    def test_detects_english_from_latest_user_message(self):
        messages = [
            {"role": "user", "content": "Hello, when can I donate blood?"},
        ]

        self.assertEqual(_detect_reply_language(messages), "en")

    def test_explicit_language_switch_overrides_input_language(self):
        messages = [
            {"role": "user", "content": "Please reply in Swahili: when can I donate blood?"},
        ]

        self.assertEqual(_detect_reply_language(messages), "sw")
        self.assertIn("Reply in Swahili", _system_prompt(messages))
