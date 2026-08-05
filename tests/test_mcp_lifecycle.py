import asyncio
import contextlib
import io
import unittest
from unittest.mock import Mock

from fastmcp import Client

from mcp_server.cli import main
from mcp_server.context import MCPContext
from mcp_server.server import create_server
from mcp_server.tools.storage_sync import StorageSyncTools


class _AsyncDependency:
    def __init__(self):
        self.closed = 0

    async def aclose(self):
        self.closed += 1


class _FailingDependency:
    def close(self):
        raise RuntimeError("expected cleanup failure")


class _CancelledDependency:
    async def aclose(self):
        raise asyncio.CancelledError


class MCPApplicationLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_lifespan_closes_unique_dependencies_and_continues(self):
        dependency = _AsyncDependency()
        context = MCPContext.from_tools(
            project_root="/tmp/project",
            tools={
                "first": dependency,
                "duplicate": dependency,
                "failing": _FailingDependency(),
            },
        )

        with self.assertLogs("mcp_server.context", level="WARNING"):
            async with Client(create_server(context=context)):
                pass

        self.assertEqual(dependency.closed, 1)

    async def test_cancellation_is_deferred_until_others_are_closed(self):
        dependency = _AsyncDependency()
        context = MCPContext.from_tools(
            project_root="/tmp/project",
            tools={
                "cancelled": _CancelledDependency(),
                "remaining": dependency,
            },
        )

        with self.assertLogs("mcp_server.context", level="WARNING"):
            with self.assertRaises(asyncio.CancelledError):
                await context.aclose()

        self.assertEqual(dependency.closed, 1)

    def test_storage_cleanup_is_idempotent_and_stdio_safe(self):
        tools = StorageSyncTools("/tmp/project")
        backend = Mock()
        backend.cleanup.side_effect = lambda: print(
            "关闭连接失败 /tmp/cache.db: injected failure"
        )
        tools._remote_backend = backend

        stdout = io.StringIO()
        with self.assertLogs(
            "mcp_server.tools.storage_sync",
            level="WARNING",
        ) as logs:
            with contextlib.redirect_stdout(stdout):
                tools.cleanup()
                tools.cleanup()

        backend.cleanup.assert_called_once_with()
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("injected failure", "\n".join(logs.output))


class MCPCommandLineTests(unittest.TestCase):
    def test_cli_delegates_transport_options(self):
        run = Mock()

        main(
            run,
            [
                "--transport",
                "http",
                "--host",
                "localhost",
                "--port",
                "4444",
                "--project-root",
                "/tmp/project",
                "--allow-http-write",
            ],
        )

        run.assert_called_once_with(
            project_root="/tmp/project",
            transport="http",
            host="localhost",
            port=4444,
            allow_http_write=True,
            allow_insecure_public_http=None,
        )


if __name__ == "__main__":
    unittest.main()
