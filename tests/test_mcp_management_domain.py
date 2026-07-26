import ast
import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import Mock

from fastmcp import Client

from mcp_server.context import MCPContext
from mcp_server.server import create_server, mcp


ROOT = Path(__file__).parents[1]
MANAGEMENT_HANDLERS = {
    "get_current_config",
    "get_system_status",
    "check_version",
}
EXPECTED_DESCRIPTION_DIGEST = (
    "ebe2774021eeae3ca3737a5fd32cfee2a8266d611222770bf39cee01bb933833"
)


class ManagementFeatureBoundaryTests(unittest.TestCase):
    def test_server_delegates_management_handlers(self):
        server_tree = ast.parse(
            (ROOT / "mcp_server/server.py").read_text(encoding="utf-8")
        )
        defined_functions = {
            node.name
            for node in ast.walk(server_tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

        self.assertTrue(
            MANAGEMENT_HANDLERS.isdisjoint(defined_functions)
        )

    def test_public_parameter_guidance_is_stable(self):
        import asyncio

        tools = asyncio.run(mcp.get_tools())
        descriptions = {
            name: tools[name].description
            for name in sorted(MANAGEMENT_HANDLERS)
        }
        encoded = json.dumps(
            descriptions,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()

        self.assertEqual(
            hashlib.sha256(encoded).hexdigest(),
            EXPECTED_DESCRIPTION_DIGEST,
        )


class ManagementFeatureDelegationTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_management_handlers_use_role_specific_dependencies(self):
        config = Mock()
        config.get_current_config.return_value = {
            "success": True,
            "config": {"section": "crawler"},
        }
        system = Mock()
        system.get_system_status.return_value = {
            "success": True,
            "data": {"health": "healthy"},
        }
        system.check_version.return_value = {
            "success": True,
            "data": {"any_update": False},
        }
        context = MCPContext.from_tools(
            project_root="/tmp/project",
            tools={
                "config": config,
                "system": system,
            },
        )

        async with Client(create_server(context=context)) as client:
            config_result = await client.call_tool(
                "get_current_config",
                {"section": "crawler"},
            )
            status_result = await client.call_tool(
                "get_system_status",
                {},
            )
            version_result = await client.call_tool(
                "check_version",
                {"proxy_url": "http://proxy.example"},
            )

        self.assertTrue(json.loads(config_result.content[0].text)["success"])
        self.assertTrue(json.loads(status_result.content[0].text)["success"])
        self.assertTrue(json.loads(version_result.content[0].text)["success"])
        config.get_current_config.assert_called_once_with(
            section="crawler"
        )
        system.get_system_status.assert_called_once_with()
        system.check_version.assert_called_once_with(
            proxy_url="http://proxy.example"
        )


if __name__ == "__main__":
    unittest.main()
