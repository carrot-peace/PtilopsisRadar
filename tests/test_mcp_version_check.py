# coding=utf-8
"""MCP version check tests for PtilopsisRadar display suffix versions."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_server.tools.system import SystemManagementTools


class TestMCPVersionCheck(unittest.TestCase):
    def test_mcp_suffix_version_compares_by_numeric_tuple(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_dir = root / "config"
            config_dir.mkdir()
            (config_dir / "config.yaml").write_text(
                "\n".join(
                    [
                        "advanced:",
                        '  version_check_url: "https://example.invalid/version"',
                        '  mcp_version_check_url: "https://example.invalid/version_mcp"',
                    ]
                ),
                encoding="utf-8",
            )

            def fake_fetch(url, proxy_url=None):
                if url.endswith("version_mcp"):
                    return "0.1.0-mcp"
                return "0.1.0"

            tools = SystemManagementTools(project_root=str(root))
            with patch("trendradar.core.cdn.fetch_with_fallback", side_effect=fake_fetch):
                result = tools.check_version()

        self.assertTrue(result["success"])
        self.assertFalse(result["data"]["any_update"])
        self.assertEqual(result["data"]["trendradar"]["current_version"], "0.1.0")
        self.assertEqual(result["data"]["mcp"]["current_version"], "0.1.0-mcp")
        self.assertEqual(result["data"]["mcp"]["remote_version"], "0.1.0-mcp")
        self.assertEqual(result["data"]["mcp"]["current_parsed"], [0, 1, 0])


if __name__ == "__main__":
    unittest.main()
