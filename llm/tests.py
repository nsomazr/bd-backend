from unittest.mock import patch

from django.test import SimpleTestCase

from .generator import (
    _detect_reply_language,
    _is_cuda_oom,
    _system_prompt,
    user_facing_generation_error,
)
from .loader import LoadedModel, _LazySingleActiveLoader


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


class LoaderLifecycleTests(SimpleTestCase):
    def test_session_keeps_model_loaded_when_requested(self):
        loader = _LazySingleActiveLoader()
        fake = LoadedModel("gemma4-e4b", object(), object(), "gemma4", "cuda")

        with patch.object(loader, "_load_locked", return_value=fake):
            with loader.session("gemma4-e4b") as loaded:
                self.assertIs(loaded, fake)
                self.assertEqual(loader.current_key, "gemma4-e4b")
                self.assertEqual(loader._active_count, 1)

        self.assertEqual(loader.current_key, "gemma4-e4b")
        self.assertEqual(loader._active_count, 0)

    def test_session_unloads_model_when_idle_and_requested(self):
        loader = _LazySingleActiveLoader()
        fake = LoadedModel("qwen3.5-4b", object(), object(), "qwen", "cuda")

        with patch.object(loader, "_load_locked", return_value=fake):
            with loader.session("qwen3.5-4b", unload_if_idle=True) as loaded:
                self.assertIs(loaded, fake)
                self.assertEqual(loader.current_key, "qwen3.5-4b")

        self.assertIsNone(loader.current_key)
        self.assertEqual(loader._active_count, 0)

    def test_acquire_retries_on_cpu_when_gpu_load_ooms(self):
        loader = _LazySingleActiveLoader()
        cpu_loaded = LoadedModel("gemma4-e4b", object(), object(), "gemma4", "cpu")

        with patch.object(
            loader,
            "_load_locked",
            side_effect=[RuntimeError("CUDA out of memory"), cpu_loaded],
        ):
            loaded = loader.acquire("gemma4-e4b")

        self.assertIs(loaded, cpu_loaded)
        self.assertEqual(loader.current_key, "gemma4-e4b")
        self.assertEqual(loader._active_count, 1)


class CpuFallbackTests(SimpleTestCase):
    def test_detects_cuda_oom_error_messages(self):
        self.assertTrue(_is_cuda_oom(RuntimeError("CUDA out of memory.")))
        self.assertTrue(_is_cuda_oom(RuntimeError("CUDA error: out of memory")))
        self.assertFalse(_is_cuda_oom(RuntimeError("Some other generation error")))

    def test_oom_error_is_hidden_from_user(self):
        message = user_facing_generation_error(RuntimeError("CUDA out of memory"))
        self.assertIn("temporarily busy", message)
        self.assertNotIn("CUDA", message)

    def test_other_generation_errors_are_generic(self):
        message = user_facing_generation_error(RuntimeError("torch stack trace here"))
        self.assertIn("temporary problem", message)
        self.assertNotIn("torch", message)
