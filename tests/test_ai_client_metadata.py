# coding=utf-8
"""AIClient request passthrough and response metadata tests without network I/O."""

import importlib.util
import os
import sys
import types
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestAIClientMetadata(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.captured = {}
        fake_litellm = types.ModuleType("litellm")

        def completion(**kwargs):
            cls.captured.clear()
            cls.captured.update(kwargs)
            message = types.SimpleNamespace(content="{\"ok\":true}")
            choice = types.SimpleNamespace(message=message, finish_reason="max_tokens")
            usage = types.SimpleNamespace(
                prompt_tokens=120,
                completion_tokens=16000,
                total_tokens=16120,
                thoughts_token_count=80,
            )
            return types.SimpleNamespace(
                choices=[choice], usage=usage, model="gemini-3.5-flash", id="resp-1"
            )

        fake_litellm.completion = completion
        cls.previous_litellm = sys.modules.get("litellm")
        sys.modules["litellm"] = fake_litellm
        spec = importlib.util.spec_from_file_location(
            "test_ai_client_impl", os.path.join(ROOT, "trendradar/ai/client.py")
        )
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    @classmethod
    def tearDownClass(cls):
        if cls.previous_litellm is None:
            sys.modules.pop("litellm", None)
        else:
            sys.modules["litellm"] = cls.previous_litellm

    def test_extra_params_are_forwarded_and_metadata_is_preserved(self):
        client = self.module.AIClient(
            {
                "MODEL": "gemini/gemini-3.5-flash",
                "API_KEY": "k",
                "MAX_TOKENS": 16000,
                "TEMPERATURE": None,
                "EXTRA_PARAMS": {
                    "reasoning_effort": "low",
                    "response_format": {"type": "json_schema"},
                },
            }
        )
        content = client.chat([{"role": "user", "content": "x"}])
        self.assertEqual(content, '{"ok":true}')
        self.assertEqual(self.captured["reasoning_effort"], "low")
        self.assertEqual(self.captured["response_format"]["type"], "json_schema")
        self.assertEqual(self.captured["max_tokens"], 16000)
        self.assertNotIn("temperature", self.captured)
        self.assertEqual(client.last_response_metadata["finish_reason"], "MAX_TOKENS")
        self.assertEqual(client.last_response_metadata["usage"]["completion_tokens"], 16000)
        self.assertEqual(client.last_response_metadata["usage"]["thoughts_token_count"], 80)
        self.assertEqual(client.last_response_metadata["response_id"], "resp-1")
        self.assertEqual(client.last_response_metadata["model"], "gemini-3.5-flash")

    def test_per_call_kwargs_override_extra_params(self):
        client = self.module.AIClient(
            {
                "MODEL": "test/model",
                "API_KEY": "k",
                "MAX_TOKENS": 16000,
                "EXTRA_PARAMS": {"reasoning_effort": "low", "timeout": 5},
            }
        )
        client.chat(
            [{"role": "user", "content": "x"}],
            reasoning_effort="minimal",
            timeout=30,
            max_tokens=8000,
        )
        self.assertEqual(self.captured["reasoning_effort"], "minimal")
        self.assertEqual(self.captured["timeout"], 30)
        self.assertEqual(self.captured["max_tokens"], 8000)


if __name__ == "__main__":
    unittest.main()
