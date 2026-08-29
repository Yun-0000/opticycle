"""Route option ExecutionDecisions through official Alpaca MCP only."""

from __future__ import annotations

from typing import Any

from .mcp.alpaca_mcp_executor import AlpacaMcpExecutor
from .orders import ExecutionRejected, OptionOrderRequest, decision_to_option_order

ALLOWED_BACKENDS = ("mcp",)


def execute_via_backend(
    engine: Any,
    decision: Any,
    backend: str,
    *,
    mcp_executor: AlpacaMcpExecutor | None = None,
) -> bool:
    """Send an options decision through official MCP. Never uses alpaca-py submit_order."""
    name = (backend or "").strip().lower()
    if name not in ALLOWED_BACKENDS:
        raise ExecutionRejected("official MCP is the only live execution channel")
    request = decision_to_option_order(decision)
    request.assert_options_instrument()
    dry_run = not bool(getattr(engine, "execute", True))
    executor = mcp_executor or AlpacaMcpExecutor(
        dry_run=dry_run,
        client=getattr(engine, "mcp_client", None),
    )
    result = executor.place_option_order_sync(request)
    logger = getattr(engine, "logger", None)
    if logger is not None:
        logger.info("hackathon backend=%s result=%s", name, result)
    if dry_run:
        return True
    return bool(result.get("ok") or result.get("id") or result.get("order_id"))


def dry_run_option_order(
    request: OptionOrderRequest,
    backend: str = "mcp",
) -> dict[str, Any]:
    name = (backend or "mcp").strip().lower()
    request.assert_options_instrument()
    if name not in ALLOWED_BACKENDS:
        raise ExecutionRejected("official MCP is the only live execution channel")
    return AlpacaMcpExecutor(dry_run=True).place_option_order_sync(request)
