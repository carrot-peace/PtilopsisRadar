import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastmcp import Client

from mcp_server.context import MCPContext
from mcp_server.server import create_server, run_server
from mcp_server.transport import (
    BearerTokenVerifier,
    environment_flag,
    is_loopback_host,
)


class HTTPTransportConfigurationTests(unittest.TestCase):
    def test_loopback_detection_is_explicit(self):
        for host in ("127.0.0.1", "::1", "[::1]", "localhost"):
            with self.subTest(host=host):
                self.assertTrue(is_loopback_host(host))
        for host in ("0.0.0.0", "::", "192.0.2.1", "mcp.example"):
            with self.subTest(host=host):
                self.assertFalse(is_loopback_host(host))

    def test_invalid_environment_boolean_fails_closed(self):
        with patch.dict(
            "os.environ",
            {"MCP_HTTP_ALLOW_WRITE": "sometimes"},
        ):
            with self.assertRaises(ValueError):
                environment_flag("MCP_HTTP_ALLOW_WRITE")

    def test_public_unauthenticated_http_is_rejected(self):
        with self.assertRaisesRegex(
            ValueError,
            "Refusing unauthenticated public MCP HTTP exposure",
        ):
            run_server(
                transport="http",
                host="0.0.0.0",
                http_publish_host="0.0.0.0",
                http_bearer_token="",
                allow_insecure_public_http=False,
            )

    def test_container_bind_can_publish_only_to_loopback(self):
        fake_server = SimpleNamespace(run=Mock())
        with patch(
            "mcp_server.server.create_server",
            return_value=fake_server,
        ) as factory:
            run_server(
                project_root="/tmp/project",
                transport="http",
                host="0.0.0.0",
                http_publish_host="127.0.0.1",
                http_bearer_token="",
                allow_http_write=False,
                allow_insecure_public_http=False,
            )

        factory.assert_called_once_with(
            project_root="/tmp/project",
            allow_write=False,
            expose_error_details=False,
            auth=None,
        )
        fake_server.run.assert_called_once_with(
            transport="http",
            host="0.0.0.0",
            port=3333,
            path="/mcp",
        )


class BearerTokenVerifierTests(unittest.IsolatedAsyncioTestCase):
    async def test_verifier_accepts_only_the_configured_token(self):
        verifier = BearerTokenVerifier("correct-horse")

        accepted = await verifier.verify_token("correct-horse")
        rejected = await verifier.verify_token("wrong-token")

        self.assertIsNotNone(accepted)
        self.assertEqual(accepted.client_id, "ptilopsis-radar-http")
        self.assertIsNone(rejected)
        self.assertNotIn(
            "correct-horse",
            repr(verifier.__dict__),
        )


class HTTPApplicationPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_only_context_blocks_mutating_tools(self):
        crawl = Mock()
        storage = Mock()
        context = MCPContext.from_tools(
            project_root="/tmp/project",
            tools={"crawl": crawl, "storage": storage},
            allow_write=False,
            expose_error_details=False,
        )

        async with Client(create_server(context=context)) as client:
            crawl_result = await client.call_tool(
                "trigger_crawl",
                {},
            )
            sync_result = await client.call_tool(
                "sync_from_remote",
                {"days": 7},
            )

        for result in (crawl_result, sync_result):
            payload = json.loads(result.content[0].text)
            self.assertFalse(payload["success"])
            self.assertEqual(
                payload["error"]["code"],
                "PERMISSION_DENIED",
            )
        crawl.trigger_crawl.assert_not_called()
        storage.sync_from_remote.assert_not_called()

    async def test_untrusted_context_masks_internal_error_details(self):
        data = Mock()
        data.get_latest_news.return_value = {
            "success": False,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "/secret/path database failure",
                "traceback": "private stack",
            },
            "diagnostics": {
                "error": "nested provider secret",
            },
            "data": {
                "failed_dates": [
                    {
                        "date": "2026-07-26",
                        "error": "provider path /secret/cache",
                    },
                ],
            },
        }
        context = MCPContext.from_tools(
            project_root="/tmp/project",
            tools={"data": data},
            expose_error_details=False,
        )

        async with Client(create_server(context=context)) as client:
            result = await client.call_tool("get_latest_news", {})

        encoded = result.content[0].text
        payload = json.loads(encoded)
        self.assertEqual(
            payload["error"]["message"],
            "服务内部错误",
        )
        self.assertNotIn("/secret/path", encoded)
        self.assertNotIn("private stack", encoded)
        self.assertNotIn("nested provider secret", encoded)
        self.assertNotIn("provider path", encoded)

    async def test_trusted_context_preserves_legacy_error_payload(self):
        data = Mock()
        data.get_latest_news.return_value = {
            "success": False,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "legacy detail",
            },
        }
        context = MCPContext.from_tools(
            project_root="/tmp/project",
            tools={"data": data},
            expose_error_details=True,
        )

        async with Client(create_server(context=context)) as client:
            result = await client.call_tool("get_latest_news", {})

        self.assertIn("legacy detail", result.content[0].text)


if __name__ == "__main__":
    unittest.main()
