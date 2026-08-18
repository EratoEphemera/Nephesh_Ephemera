from __future__ import annotations

import unittest

from mcp_experiments.server import _combined_transport_app


class CombinedTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_mcp_path_uses_streamable_http(self) -> None:
        calls: list[str] = []

        async def sse(scope, receive, send):
            calls.append("sse")

        async def streamable(scope, receive, send):
            calls.append("streamable")

        import mcp_experiments.server as server

        original_sse = server.mcp.sse_app
        original_streamable = server.mcp.streamable_http_app
        server.mcp.sse_app = lambda: sse  # type: ignore[method-assign]
        server.mcp.streamable_http_app = lambda: streamable  # type: ignore[method-assign]
        try:
            app = _combined_transport_app()
            scope = {"type": "http", "path": "/mcp"}
            await app(scope, lambda: None, lambda message: None)
            self.assertEqual(calls, ["streamable"])
        finally:
            server.mcp.sse_app = original_sse  # type: ignore[method-assign]
            server.mcp.streamable_http_app = original_streamable  # type: ignore[method-assign]

    async def test_legacy_paths_use_sse(self) -> None:
        calls: list[str] = []

        async def sse(scope, receive, send):
            calls.append("sse")

        async def streamable(scope, receive, send):
            calls.append("streamable")

        import mcp_experiments.server as server

        original_sse = server.mcp.sse_app
        original_streamable = server.mcp.streamable_http_app
        server.mcp.sse_app = lambda: sse  # type: ignore[method-assign]
        server.mcp.streamable_http_app = lambda: streamable  # type: ignore[method-assign]
        try:
            app = _combined_transport_app()
            scope = {"type": "http", "path": "/sse"}
            await app(scope, lambda: None, lambda message: None)
            self.assertEqual(calls, ["sse"])
        finally:
            server.mcp.sse_app = original_sse  # type: ignore[method-assign]
            server.mcp.streamable_http_app = original_streamable  # type: ignore[method-assign]

    async def test_lifespan_uses_streamable_http_manager(self) -> None:
        calls: list[str] = []

        async def sse(scope, receive, send):
            calls.append("sse")

        async def streamable(scope, receive, send):
            calls.append("streamable")

        import mcp_experiments.server as server

        original_sse = server.mcp.sse_app
        original_streamable = server.mcp.streamable_http_app
        server.mcp.sse_app = lambda: sse  # type: ignore[method-assign]
        server.mcp.streamable_http_app = lambda: streamable  # type: ignore[method-assign]
        try:
            app = _combined_transport_app()
            scope = {"type": "lifespan", "path": ""}
            await app(scope, lambda: None, lambda message: None)
            self.assertEqual(calls, ["streamable"])
        finally:
            server.mcp.sse_app = original_sse  # type: ignore[method-assign]
            server.mcp.streamable_http_app = original_streamable  # type: ignore[method-assign]


if __name__ == "__main__":
    unittest.main()
