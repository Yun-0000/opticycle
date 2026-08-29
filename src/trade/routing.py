"""Route option ExecutionDecisions through official Alpaca MCP only.

Live submit is not available on this leftover pin path. Opticycle live
orders go through AlpacaMcpExecutor.place_certified_order_sync only.
"""

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
    """Dry-run preview only. Does not submit through alpaca-py. Never live-submits."""
    name = (backend or "").strip().lower()
    if name not in ALLOWED_BACKENDS:
        raise ExecutionRejected("official MCP is the only live execution channel")
    request = decision_to_option_order(decision)
    request.assert_options_instrument()
    dry_run = not bool(getattr(engine, "execute", True))
    if not dry_run:
        raise ExecutionRejected(
            "unauthorized: live submit requires a valid Risk Certificate via place_certified_order_sync"
        )
    executor = mcp_executor or AlpacaMcpExecutor(
        dry_run=True,
        client=getattr(engine, "mcp_client", None),
    )
    result = executor.place_option_order_sync(request)
    logger = getattr(engine, "logger", None)
    if logger is not None:
        logger.info("hackathon backend=%s result=%s", name, result)
    return True


def dry_run_option_order(
    request: OptionOrderRequest,
    backend: str = "mcp",
) -> dict[str, Any]:
    name = (backend or "mcp").strip().lower()
    request.assert_options_instrument()
    if name not in ALLOWED_BACKENDS:
        raise ExecutionRejected("official MCP is the only live execution channel")
    return AlpacaMcpExecutor(dry_run=True).place_option_order_sync(request)
