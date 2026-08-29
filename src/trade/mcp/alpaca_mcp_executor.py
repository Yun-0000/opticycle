"""Alpaca MCP Server adapter for paper option orders.

Primary execution path: spawn `uvx alpaca-mcp-server==2.3.0` and call
`place_option_order`. Tests inject a mock client; CI never needs live keys.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from ..orders import OptionOrderRequest

MCP_SERVER_SPEC = "alpaca-mcp-server==2.3.0"
PLACE_OPTION_ORDER = "place_option_order"


class McpToolClient(Protocol):
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Call a named MCP tool."""


ClientFactory = Callable[[], Any]


def mcp_env_from_os(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Build a paper-only environment for the MCP server subprocess."""
    env = {key: value for key, value in os.environ.items() if value is not None}
    env["ALPACA_PAPER_TRADE"] = "true"
    env["ALPACA_LIVE_TRADE"] = "false"
    if extra:
        env.update(extra)
    return env


def _stdio_params(server_spec: str, env: dict[str, str]) -> Any:
    from mcp import StdioServerParameters

    return StdioServerParameters(
        command="uvx",
        args=[server_spec],
        env=env,
    )


def default_mcp_client_factory(
    server_spec: str = MCP_SERVER_SPEC,
    env: dict[str, str] | None = None,
) -> Any:
    """Construct an MCP Client pointed at the pinned Alpaca MCP server."""
    from mcp import Client

    params = _stdio_params(server_spec, env or mcp_env_from_os())
    try:
        return Client(params)
    except TypeError:
        from mcp.client.stdio import stdio_client

        return Client(stdio_client(params))


def parse_mcp_result(result: Any) -> dict[str, Any]:
    if result is None:
        raise RuntimeError("MCP tool returned no result")
    if isinstance(result, dict):
        if result.get("isError") or result.get("is_error"):
            raise RuntimeError(f"MCP tool error: {result}")
        return result
    if getattr(result, "is_error", False):
        text = _content_text(result)
        raise RuntimeError(text or "MCP tool returned is_error")
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        return structured
    text = _content_text(result)
    if text:
        try:
            loaded = json.loads(text)
            if isinstance(loaded, dict):
                return loaded
        except json.JSONDecodeError:
            return {"raw": text}
    return {"ok": True, "raw": repr(result)}


def _content_text(result: Any) -> str:
    chunks: list[str] = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text:
            chunks.append(str(text))
        elif isinstance(block, dict) and block.get("text"):
            chunks.append(str(block["text"]))
    return "\n".join(chunks)


@dataclass
class AlpacaMcpExecutor:
    """Execute option orders through Alpaca MCP Server 2.3.0."""

    client: McpToolClient | None = None
    client_factory: ClientFactory | None = None
    server_spec: str = MCP_SERVER_SPEC
    dry_run: bool = False
    env: dict[str, str] | None = None

    @classmethod
    def from_env(cls, *, dry_run: bool = False) -> "AlpacaMcpExecutor":
        return cls(dry_run=dry_run, env=mcp_env_from_os())

    async def place_option_order(self, request: OptionOrderRequest) -> dict[str, Any]:
        request.assert_options_instrument()
        arguments = request.to_mcp_args()
        if self.dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "backend": "mcp",
                "tool": PLACE_OPTION_ORDER,
                "arguments": arguments,
            }
        client = await self._client()
        result = await client.call_tool(PLACE_OPTION_ORDER, arguments)
        parsed = parse_mcp_result(result)
        parsed.setdefault("backend", "mcp")
        parsed.setdefault("ok", True)
        return parsed

    def place_option_order_sync(self, request: OptionOrderRequest) -> dict[str, Any]:
        return asyncio.run(self.place_option_order(request))

    async def _client(self) -> McpToolClient:
        if self.client is not None:
            return self.client
        factory = self.client_factory or (
            lambda: default_mcp_client_factory(self.server_spec, self.env)
        )
        opened = factory()
        if hasattr(opened, "__aenter__"):
            self.client = await opened.__aenter__()
            return self.client
        self.client = opened
        return opened
