"""Alpaca CLI adapter kept out of the live execution path.

Official paper execution is alpaca-mcp-server==2.3.0 MLEG only.
This module is not imported by the live Opticycle profile and is not
an execution channel.
"""

from __future__ import annotations

from typing import Any

from ..orders import ExecutionRejected, OptionOrderRequest

ALPACA_CLI_TAG = "v0.0.14"


class AlpacaCliExecutor:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise ExecutionRejected("Alpaca CLI is not a live execution channel")

    def place_option_order(self, request: OptionOrderRequest) -> dict[str, Any]:
        raise ExecutionRejected("Alpaca CLI is not a live execution channel")
