from __future__ import annotations

from types import SimpleNamespace

import pytest

from trade.cli.alpaca_cli_executor import AlpacaCliExecutor
from trade.mcp.alpaca_mcp_executor import AlpacaMcpExecutor, PLACE_OPTION_ORDER
from trade.orders import ExecutionRejected
from trade.routing import execute_via_backend


class FakeMcpClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, name: str, arguments: dict) -> dict:
        self.calls.append((name, arguments))
        return {"id": "routed-mcp", "ok": True}


def _option_decision(**kwargs) -> SimpleNamespace:
    payload = dict(
        symbol="SPY250919P00475000",
        side="sell",
        quantity=1,
        order_type="limit",
        limit_price=1.25,
        action="SELL_TO_OPEN",
        reason="cash-secured put",
        metadata={},
    )
    payload.update(kwargs)
    return SimpleNamespace(**payload)


def test_routing_mcp_sends_option_order() -> None:
    client = FakeMcpClient()
    engine = SimpleNamespace(execute=True, logger=None, mcp_client=client)
    ok = execute_via_backend(
        engine,
        _option_decision(),
        "mcp",
        mcp_executor=AlpacaMcpExecutor(client=client, dry_run=False),
    )
    assert ok is True
    assert client.calls[0][0] == PLACE_OPTION_ORDER


def test_routing_rejects_stock_only_decision() -> None:
    engine = SimpleNamespace(execute=True, logger=None)
    with pytest.raises(ExecutionRejected, match="OCC option symbol"):
        execute_via_backend(engine, _option_decision(symbol="AAPL"), "mcp")


def test_routing_cli_fallback_argv() -> None:
    captured: dict[str, list[str]] = {}

    def runner(argv, **kwargs):
        captured["argv"] = argv
        return SimpleNamespace(returncode=0, stdout='{"id":"cli-1"}', stderr="")

    engine = SimpleNamespace(execute=True, logger=None)
    ok = execute_via_backend(
        engine,
        _option_decision(),
        "cli",
        cli_executor=AlpacaCliExecutor(dry_run=False, runner=runner),
    )
    assert ok is True
    assert captured["argv"][:3] == ["alpaca", "order", "submit"]
    assert "--symbol" in captured["argv"]
    assert "SPY250919P00475000" in captured["argv"]
    assert "--position-intent" in captured["argv"]


def test_routing_cli_rejects_live_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPACA_LIVE_TRADE", "true")
    engine = SimpleNamespace(execute=True, logger=None)

    def runner(argv, **kwargs):
        raise AssertionError("must not spawn CLI on live")

    with pytest.raises(ExecutionRejected, match="paper"):
        execute_via_backend(
            engine,
            _option_decision(),
            "cli",
            cli_executor=AlpacaCliExecutor(dry_run=False, runner=runner),
        )


def test_routing_dry_run_returns_true_without_live_call() -> None:
    client = FakeMcpClient()
    engine = SimpleNamespace(execute=False, logger=None)
    ok = execute_via_backend(
        engine,
        _option_decision(),
        "mcp",
        mcp_executor=AlpacaMcpExecutor(client=client, dry_run=True),
    )
    assert ok is True
    assert client.calls == []
