import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest

from fastmcp import Client

from tests.test_mcp_contracts import EXPECTED_TOOLS


class MCPHTTPSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        self.port = listener.getsockname()[1]
        listener.close()

        self.stderr = tempfile.TemporaryFile(mode="w+")
        environment = os.environ.copy()
        environment["MCP_HTTP_BEARER_TOKEN"] = "http-smoke-token"
        environment.pop("MCP_HTTP_ALLOW_WRITE", None)
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "mcp_server.server",
                "--transport",
                "http",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
            ],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=self.stderr,
        )

        for _ in range(100):
            probe = socket.socket()
            try:
                ready = (
                    probe.connect_ex(("127.0.0.1", self.port)) == 0
                )
            finally:
                probe.close()
            if ready:
                break
            if self.process.poll() is not None:
                self.stderr.seek(0)
                self.fail(self.stderr.read())
            await asyncio.sleep(0.05)
        else:
            self.fail("MCP HTTP server did not become ready")

    async def asyncTearDown(self):
        self.process.terminate()
        try:
            await asyncio.to_thread(self.process.wait, 5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            await asyncio.to_thread(self.process.wait, 5)
        self.stderr.close()

    async def test_authenticated_http_surface_is_stable_and_read_only(self):
        async with Client(
            f"http://127.0.0.1:{self.port}/mcp",
            auth="http-smoke-token",
        ) as client:
            tools = await client.list_tools()
            denied = await client.call_tool("trigger_crawl", {})

        self.assertEqual({tool.name for tool in tools}, EXPECTED_TOOLS)
        payload = json.loads(denied.content[0].text)
        self.assertEqual(
            payload["error"]["code"],
            "PERMISSION_DENIED",
        )


if __name__ == "__main__":
    unittest.main()
