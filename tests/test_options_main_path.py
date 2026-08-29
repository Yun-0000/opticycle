"""Main autonomous path: decision → risk gate → MCP/CLI option order."""

from __future__ import annotations

from pathlib import Path

from gaussoptions.risk import RiskGate, PortfolioSnapshot
from gaussoptions.runner import run_once
from gaussoptions.settings import HackathonSettings
from trade.mcp.alpaca_mcp_executor import MCP_SERVER_SPEC, PLACE_OPTION_ORDER, _stdio_params
from trade.orders import ExecutionRejected, OptionOrderRequest


def test_mcp_stdio_spawns_pinned_server() -> None:
    params = _stdio_params(MCP_SERVER_SPEC, {"ALPACA_PAPER_TRADE": "true"})
    assert params.command == "uvx"
    assert params.args == ["alpaca-mcp-server==2.3.0"]


def test_options_main_path_mcp_dry_run(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = run_once(HackathonSettings(execution_backend="mcp", strategy="wheel"), dry_run=True)
    assert result["ok"] is True
    assert result["strategy"] == "wheel"
    assert result["order"]["tool"] == PLACE_OPTION_ORDER
    assert result["order"]["arguments"]["symbol"]
    assert result["gate"]["approved"] is True


def test_options_main_path_cli_vertical_spread(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = run_once(
        HackathonSettings(execution_backend="cli", strategy="vertical_spread"),
        dry_run=True,
    )
    assert result["strategy"] == "vertical_spread"
    assert "--order-class" in result["order"]["argv"]
    assert "mleg" in result["order"]["argv"]


def test_stock_symbol_blocked_by_risk_gate() -> None:
    settings = HackathonSettings()
    request = OptionOrderRequest(qty=1, symbol="SPY", side="buy")
    try:
        RiskGate(settings).evaluate(
            request,
            PortfolioSnapshot(equity=100000, buying_power=100000, cash=100000),
        )
    except ExecutionRejected as exc:
        assert "OCC" in str(exc)
    else:
        raise AssertionError("stock symbol must be rejected")
