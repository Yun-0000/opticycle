"""Official Alpaca MCP Server adapter for certified paper MLEG orders.

Live submit talks only to `uvx alpaca-mcp-server==2.3.0` and only through
`place_certified_order_sync`. `place_option_order` cannot submit live.
Tests inject a mock client; this module never places a real broker order
in CI. alpaca-py is not used here.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from ..orders import OCC_SYMBOL_RE, ExecutionRejected, OptionOrderRequest

MCP_SERVER_SPEC = "alpaca-mcp-server==2.3.0"
FASTMCP_UVX_SPEC = "fastmcp>=3.1.0,<4"
PLACE_OPTION_ORDER = "place_option_order"
PAPER_API_HOST = "https://paper-api.alpaca.markets"
DESIGNATED_PAPER_ACCOUNT = "PA3V84C40PJQ"
MCP_CALL_TIMEOUT_SEC = 45.0


class McpCallTimeout(RuntimeError):
    """call_tool did not return; the broker may already have accepted the MLEG."""


class McpToolClient(Protocol):
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Call a named MCP tool."""


ClientFactory = Callable[[], Any]


def mcp_env_from_os(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Build a paper-only environment. Live host flags cannot override paper."""
    env = {key: value for key, value in os.environ.items() if value is not None}
    if extra:
        env.update(extra)
    env["ALPACA_PAPER_TRADE"] = "true"
    env["ALPACA_LIVE_TRADE"] = "false"
    env["APCA_API_BASE_URL"] = PAPER_API_HOST
    env["ALPACA_API_BASE_URL"] = PAPER_API_HOST
    env["TRADE_API_URL"] = PAPER_API_HOST
    return env


def assert_paper_mcp_env(env: dict[str, str] | None) -> dict[str, str]:
    forced = mcp_env_from_os(env)
    if str(forced.get("ALPACA_PAPER_TRADE", "")).lower() != "true":
        raise ExecutionRejected("paper host required")
    if str(forced.get("ALPACA_LIVE_TRADE", "")).lower() == "true":
        raise ExecutionRejected("paper host required")
    host = str(forced.get("APCA_API_BASE_URL") or "")
    if host != PAPER_API_HOST:
        raise ExecutionRejected("paper host required")
    for key, value in list(forced.items()):
        lowered = str(value).lower()
        if "api.alpaca.markets" in lowered and "paper-api.alpaca.markets" not in lowered:
            raise ExecutionRejected("paper host required")
        _ = key
    return forced


def _stdio_params(server_spec: str, env: dict[str, str]) -> Any:
    if server_spec != MCP_SERVER_SPEC:
        raise ExecutionRejected("official alpaca-mcp-server==2.3.0 is the only live MCP server")
    from mcp import StdioServerParameters

    return StdioServerParameters(
        command="uvx",
        args=["--with", FASTMCP_UVX_SPEC, server_spec],
        env=assert_paper_mcp_env(env),
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
    """Parse an MCP tool result without inventing ok=true success."""
    if result is None:
        raise RuntimeError("MCP tool returned no result")
    if isinstance(result, dict):
        if result.get("isError") or result.get("is_error"):
            raise RuntimeError(f"MCP tool error: {result}")
        return dict(result)
    if getattr(result, "is_error", False) or getattr(result, "isError", False):
        text = _content_text(result)
        raise RuntimeError(text or "MCP tool returned is_error")
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        return dict(structured)
    text = _content_text(result)
    if text:
        try:
            loaded = json.loads(text)
            if isinstance(loaded, dict):
                return loaded
        except json.JSONDecodeError:
            return {"raw": text}
    return {"raw": _serialize_raw(result)}


def serialize_mcp_raw(result: Any) -> Any:
    """Full raw MCP payload. Never reduced to {ok: true}."""
    return _serialize_raw(result)


def _serialize_raw(result: Any) -> Any:
    if result is None:
        return None
    if isinstance(result, (str, int, float, bool)):
        return result
    if isinstance(result, dict):
        return {key: _serialize_raw(value) for key, value in result.items()}
    if isinstance(result, (list, tuple)):
        return [_serialize_raw(item) for item in result]
    payload: dict[str, Any] = {}
    for attr in ("is_error", "isError", "structured_content", "structuredContent"):
        if hasattr(result, attr):
            payload[attr] = _serialize_raw(getattr(result, attr))
    content = []
    for block in getattr(result, "content", None) or []:
        if hasattr(block, "text"):
            content.append({"type": "text", "text": str(block.text)})
        elif isinstance(block, dict):
            content.append(_serialize_raw(block))
        else:
            content.append({"repr": repr(block)})
    if content:
        payload["content"] = content
    if payload:
        return payload
    return {"repr": repr(result)}


def digest_canonical(value: Any) -> str:
    blob = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


async def call_mcp_tool(
    client: McpToolClient,
    name: str,
    arguments: dict[str, Any],
    *,
    timeout: float = MCP_CALL_TIMEOUT_SEC,
) -> Any:
    """Call an MCP tool with a bounded wait. Does not invent a broker result."""
    try:
        pending = client.call_tool(name, arguments)
    except TypeError:
        pending = client.call_tool(name, arguments=arguments)
    try:
        return await asyncio.wait_for(pending, timeout=timeout)
    except (asyncio.TimeoutError, TimeoutError) as exc:
        raise McpCallTimeout(
            f"{name} exceeded {timeout:.0f}s; broker GET-by-client_order_id required"
        ) from exc


def _content_text(result: Any) -> str:
    chunks: list[str] = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text:
            chunks.append(str(text))
        elif isinstance(block, dict) and block.get("text"):
            chunks.append(str(block["text"]))
    return "\n".join(chunks)


def assert_certified_mleg_arguments(arguments: dict[str, Any], payload: Any) -> None:
    """MCP tool args must be exactly CanonicalOrderPayload.to_mcp_arguments()."""
    bound = payload.to_mcp_arguments()
    if arguments != bound:
        raise ExecutionRejected("MCP MLEG arguments must come only from the certified CanonicalOrderPayload")
    if arguments.get("order_class") != "mleg":
        raise ExecutionRejected("mleg-only: live submit requires order_class=mleg")
    legs = arguments.get("legs")
    if not isinstance(legs, list) or len(legs) < 2:
        raise ExecutionRejected("mleg-only: live submit requires at least two OCC legs")
    if arguments.get("symbol"):
        raise ExecutionRejected("mleg-only: top-level stock symbol is not permitted")
    for index, leg in enumerate(legs):
        symbol = str((leg or {}).get("symbol") or "")
        if not OCC_SYMBOL_RE.fullmatch(symbol):
            raise ExecutionRejected(f"options-only: leg[{index}] is not an OCC option symbol")
        if not str((leg or {}).get("side") or ""):
            raise ExecutionRejected(f"options-only: leg[{index}] is missing side")
        if not str((leg or {}).get("position_intent") or ""):
            raise ExecutionRejected(f"options-only: leg[{index}] is missing position_intent")


def _mcp_submit_envelope(
    *,
    arguments: dict[str, Any],
    raw: Any,
    dry_run: bool,
    submitted: bool,
) -> dict[str, Any]:
    timestamp = datetime.now(timezone.utc).isoformat()
    serialized = _serialize_raw(raw)
    return {
        "backend": "mcp",
        "server_spec": MCP_SERVER_SPEC,
        "tool": PLACE_OPTION_ORDER,
        "arguments": arguments,
        "arguments_hash": digest_canonical(arguments),
        "timestamp": timestamp,
        "raw": serialized,
        "raw_result_hash": digest_canonical(serialized),
        "dry_run": dry_run,
        "submitted": submitted,
    }


@dataclass
class AlpacaMcpExecutor:
    """Execute certified MLEG option orders through Alpaca MCP Server 2.3.0."""

    client: McpToolClient | None = None
    client_factory: ClientFactory | None = None
    server_spec: str = MCP_SERVER_SPEC
    dry_run: bool = False
    env: dict[str, str] | None = None
    mcp_call_timeout_sec: float = MCP_CALL_TIMEOUT_SEC

    def __post_init__(self) -> None:
        if self.server_spec != MCP_SERVER_SPEC:
            raise ExecutionRejected("official alpaca-mcp-server==2.3.0 is the only live MCP server")
        self.env = assert_paper_mcp_env(self.env)

    @classmethod
    def from_env(cls, *, dry_run: bool = False) -> "AlpacaMcpExecutor":
        return cls(dry_run=dry_run, env=mcp_env_from_os())

    async def place_option_order(self, request: OptionOrderRequest) -> dict[str, Any]:
        """Dry-run preview only. Cannot submit a live order without a Risk Certificate."""
        request.assert_options_instrument()
        if not self.dry_run:
            raise ExecutionRejected(
                "unauthorized: live submit requires a valid Risk Certificate via place_certified_order_sync"
            )
        arguments = request.to_mcp_args()
        return {
            "dry_run": True,
            "submitted": False,
            "backend": "mcp",
            "tool": PLACE_OPTION_ORDER,
            "arguments": arguments,
        }

    def place_option_order_sync(self, request: OptionOrderRequest) -> dict[str, Any]:
        return asyncio.run(self.place_option_order(request))

    def place_certified_order_sync(
        self,
        payload: Any,
        certificate: Any,
        portfolio: Any,
        evidence: Any,
        *,
        now: Any = None,
        settings: Any = None,
    ) -> dict[str, Any]:
        """Sole live submit path: certified CanonicalOrderPayload over official MCP MLEG."""
        from opticycle.risk import RiskEngine
        from opticycle.settings import HackathonSettings

        resolved = settings or HackathonSettings()
        if getattr(resolved, "mcp_server_spec", MCP_SERVER_SPEC) != MCP_SERVER_SPEC:
            raise ExecutionRejected("official alpaca-mcp-server==2.3.0 is the only live MCP server")
        if self.server_spec != MCP_SERVER_SPEC:
            raise ExecutionRejected("official alpaca-mcp-server==2.3.0 is the only live MCP server")
        self.env = assert_paper_mcp_env(self.env)
        designated = resolved.paper_account_id or DESIGNATED_PAPER_ACCOUNT
        if payload.account_id != designated:
            raise ExecutionRejected("account mismatch: designated paper account required")
        if certificate is not None and certificate.account_id != designated:
            raise ExecutionRejected("account mismatch: designated paper account required")
        engine = RiskEngine(resolved)
        engine.assert_executable(certificate, payload, portfolio, evidence, now=now)
        if payload.payload_hash != certificate.payload_hash:
            raise ExecutionRejected("payload changed after certificate issue")
        if payload.order_class != "mleg":
            raise ExecutionRejected("mleg-only: live submit requires order_class=mleg")
        arguments = payload.to_mcp_arguments()
        assert_certified_mleg_arguments(arguments, payload)
        return self._dispatch_certified_mcp(arguments)

    def _dispatch_certified_mcp(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return asyncio.run(self._place_certified_mcp_arguments(arguments))

    async def _place_certified_mcp_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if arguments.get("order_class") != "mleg":
            raise ExecutionRejected("mleg-only: live submit requires order_class=mleg")
        if self.dry_run:
            return _mcp_submit_envelope(
                arguments=arguments,
                raw={"dry_run": True, "submitted": False, "tool": PLACE_OPTION_ORDER},
                dry_run=True,
                submitted=False,
            )
        client = await self._client()
        try:
            result = await call_mcp_tool(
                client,
                PLACE_OPTION_ORDER,
                arguments,
                timeout=self.mcp_call_timeout_sec,
            )
        except McpCallTimeout:
            timestamp = datetime.now(timezone.utc).isoformat()
            return {
                "backend": "mcp",
                "server_spec": MCP_SERVER_SPEC,
                "tool": PLACE_OPTION_ORDER,
                "arguments": arguments,
                "arguments_hash": digest_canonical(arguments),
                "timestamp": timestamp,
                "raw": {
                    "mcp_call_timeout": True,
                    "tool": PLACE_OPTION_ORDER,
                    "note": (
                        "place_option_order did not return after timeout; "
                        "broker may already have accepted; GET-by-client_order_id required"
                    ),
                },
                "raw_result_hash": "",
                "dry_run": False,
                "submitted": False,
                "mcp_call_timeout": True,
            }
        if result is None:
            raise RuntimeError("MCP tool returned no result")
        if isinstance(result, dict) and (result.get("isError") or result.get("is_error")):
            raise RuntimeError(f"MCP tool error: {result}")
        if getattr(result, "is_error", False) or getattr(result, "isError", False):
            raise RuntimeError(f"MCP tool error: {_serialize_raw(result)}")
        return _mcp_submit_envelope(
            arguments=arguments,
            raw=result,
            dry_run=False,
            submitted=True,
        )

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
