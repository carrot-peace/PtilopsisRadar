#!/usr/bin/env python3
# coding=utf-8

import builtins
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "fetch_hotlist_samples.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("fetch_hotlist_samples_test", str(SCRIPT_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestLoadPlatformsFallback(unittest.TestCase):
    def setUp(self):
        self.mod = _load_script()

    def _write_config(self, text):
        f = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".yaml", delete=False)
        with f:
            f.write(text)
        self.addCleanup(lambda: Path(f.name).unlink(missing_ok=True))
        return f.name

    def _without_yaml(self):
        original_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "yaml":
                raise ImportError("yaml intentionally unavailable")
            return original_import(name, *args, **kwargs)

        return mock.patch("builtins.__import__", side_effect=fake_import)

    def test_fallback_handles_platforms_as_last_top_level_block(self):
        path = self._write_config(
            """
rss:
  sources:
    - id: "rss-should-not-leak"
platforms:
  enabled: true
  api_url: "https://example.test/api/s"
  sources:
    - id: "weibo"
      name: "微博"
      expected_domain: "weibo.com"
""".lstrip()
        )

        with self._without_yaml():
            platforms, api_url = self.mod._load_platforms(path)

        self.assertEqual(api_url, "https://example.test/api/s")
        self.assertEqual(platforms, [("weibo", "微博", "weibo.com")])

    def test_fallback_fails_fast_without_top_level_platforms(self):
        path = self._write_config(
            """
rss:
  sources:
    - id: "rss-should-not-leak"
      name: "RSS"
""".lstrip()
        )

        with self._without_yaml():
            with self.assertRaisesRegex(ValueError, "platforms"):
                self.mod._load_platforms(path)


if __name__ == "__main__":
    unittest.main()
