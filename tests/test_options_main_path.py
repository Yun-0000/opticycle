from src.gaussoptions.profile import HackathonProfile
from src.gaussoptions.risk import check_order
from src.gaussoptions.runner import run_once
from src.trade.cli.alpaca_cli_executor import AlpacaCliExecutor
from src.trade.mcp.alpaca_mcp_executor import AlpacaMcpExecutor


def test_mcp_options_path():
    calls = []

    def call_tool(name, payload):
        calls.append((name, dict(payload)))
        return {"id": "ord-mcp", "status": "accepted"}

    result = run_once(
        HackathonProfile(execution_backend="mcp"),
        AlpacaMcpExecutor(call_tool),
        {"option_symbol": "SPY250919P00580000", "qty": 1, "notional": 2000},
        {"equity": 100000, "trades_today": 0},
    )
    assert result["backend"] == "mcp"
    assert result["decision"]["asset_class"] == "option"
    assert result["decision"]["strategy"] == "wheel"
    assert calls[0][0] == "place_order"
    assert calls[0][1]["asset_class"] == "option"
    assert result["execution"]["backend"] == "mcp"


def test_cli_options_fallback():
    runs = []

    def run(argv):
        runs.append(list(argv))
        return {"id": "ord-cli", "status": "accepted"}

    result = run_once(
        HackathonProfile(execution_backend="cli"),
        AlpacaCliExecutor(run),
        {"option_symbol": "SPY250919C00600000", "qty": 1, "notional": 1500},
        {"equity": 100000, "trades_today": 1},
    )
    assert result["execution"]["backend"] == "cli"
    assert "option" in runs[0]


def test_stock_order_blocked():
    profile = HackathonProfile()
    try:
        check_order(profile, {"asset_class": "us_equity", "notional": 100}, {"equity": 100000, "trades_today": 0})
    except ValueError as exc:
        assert "stock-only" in str(exc)
    else:
        raise AssertionError("expected stock-only block")
