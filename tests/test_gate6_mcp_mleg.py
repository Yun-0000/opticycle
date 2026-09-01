"""Gate 6: official MCP MLEG is the only live order channel.

Uncertified place_option_order cannot submit. Certified CanonicalOrderPayload
bound to a Risk Certificate is the only live submit path. No real broker call.
"""

from __future__ import annotations

import asyncio
import importlib
import json
from datetime import datetime
from pathlib import Path

import pytest

from opticycle.journal import TradeJournal
from opticycle.protocol import ThesisStance
from opticycle.runner import run_once
from opticycle.settings import HackathonSettings
from tests.test_risk_certificate import (
    ACCOUNT_ID,
    FakeMcpClient,
    _bull_put_legs,
    _bull_put_quotes,
    _evidence,
    _payload,
    _portfolio,
    _settings,
)
from trade.mcp.alpaca_mcp_executor import (
    DESIGNATED_PAPER_ACCOUNT,
    MCP_SERVER_SPEC,
    PAPER_API_HOST,
    PLACE_OPTION_ORDER,
    AlpacaMcpExecutor,
    digest_canonical,
    mcp_env_from_os,
)
from trade.orders import ExecutionRejected, OptionOrderRequest

ROOT = Path(__file__).resolve().parents[1]


class RecordingMcpClient:
    def __init__(self, payload: dict) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.payload = payload

    async def call_tool(self, name: str, arguments: dict) -> dict:
        self.calls.append((name, arguments))
        return dict(self.payload)


def _uncertified_mleg() -> OptionOrderRequest:
    return OptionOrderRequest(
        qty=1,
        order_class="mleg",
        limit_price=1.20,
        legs=[
            {
                "symbol": "SPY260918P00550000",
                "ratio_qty": "1",
                "side": "sell",
                "position_intent": "sell_to_open",
            },
            {
                "symbol": "SPY260918P00540000",
                "ratio_qty": "1",
                "side": "buy",
                "position_intent": "buy_to_open",
            },
        ],
    )


def _issue_cert():
    from opticycle.risk import RiskEngine

    engine = RiskEngine(_settings())
    payload = _payload(_bull_put_legs())
    evidence = _evidence(_bull_put_quotes())
    portfolio = _portfolio()
    cert = engine.issue(payload, portfolio, evidence)
    assert cert.approval is True
    return engine, payload, cert, portfolio, evidence


def test_uncertified_place_option_order_cannot_submit() -> None:
    client = FakeMcpClient()
    executor = AlpacaMcpExecutor(client=client, dry_run=False)
    with pytest.raises(ExecutionRejected, match="place_certified_order_sync"):
        executor.place_option_order_sync(_uncertified_mleg())
    with pytest.raises(ExecutionRejected, match="place_certified_order_sync"):
        executor.place_option_order_sync(
            OptionOrderRequest(
                qty=1,
                symbol="SPY250919P00475000",
                side="sell",
                order_type="limit",
                limit_price=1.25,
                position_intent="sell_to_open",
            )
        )
    assert client.calls == []


def test_certified_mleg_is_the_only_live_submit() -> None:
    raw = {
        "id": "mcp-mleg-99",
        "status": "accepted",
        "client_order_id": "cycle-gate5-001",
        "order_class": "mleg",
        "legs": [{"symbol": "SPY260918P00550000"}, {"symbol": "SPY260918P00540000"}],
        "filled_avg_price": None,
        "submitted_at": "2026-08-29T12:00:00Z",
    }
    client = RecordingMcpClient(raw)
    _, payload, cert, portfolio, evidence = _issue_cert()
    executor = AlpacaMcpExecutor(client=client, dry_run=False)
    result = executor.place_certified_order_sync(
        payload, cert, portfolio, evidence, settings=_settings()
    )
    assert client.calls == [(PLACE_OPTION_ORDER, payload.to_mcp_arguments())]
    assert result["tool"] == PLACE_OPTION_ORDER
    assert result["submitted"] is True
    assert result["dry_run"] is False
    assert result["server_spec"] == "alpaca-mcp-server==2.3.0"
    assert result["arguments"] == payload.to_mcp_arguments()
    assert result["arguments"]["order_class"] == "mleg"
    assert result["raw"] == raw
    assert "ok" not in result
    assert result["arguments_hash"] == digest_canonical(payload.to_mcp_arguments())
    assert result["raw_result_hash"] == digest_canonical(raw)
    assert datetime.fromisoformat(result["timestamp"].replace("Z", "+00:00"))


class HangingMcpClient:
    async def call_tool(self, name: str, arguments: dict) -> dict:
        await asyncio.sleep(30)
        return {"id": "too-late", "status": "accepted"}


def test_certified_mcp_timeout_keeps_arguments_hash_without_inventing_raw_result() -> None:
    _, payload, cert, portfolio, evidence = _issue_cert()
    executor = AlpacaMcpExecutor(
        client=HangingMcpClient(),
        dry_run=False,
        mcp_call_timeout_sec=0.05,
    )
    result = executor.place_certified_order_sync(
        payload, cert, portfolio, evidence, settings=_settings()
    )
    assert result["mcp_call_timeout"] is True
    assert result["submitted"] is False
    assert result["raw_result_hash"] == ""
    assert result["tool"] == PLACE_OPTION_ORDER
    assert result["arguments"] == payload.to_mcp_arguments()
    assert result["arguments_hash"] == digest_canonical(payload.to_mcp_arguments())
    assert result["raw"]["mcp_call_timeout"] is True
    assert "ok" not in result


def test_certified_submit_does_not_collapse_success_to_ok_true() -> None:
    raw = {"id": "broker-1", "status": "new", "qty": "1"}
    client = RecordingMcpClient(raw)
    _, payload, cert, portfolio, evidence = _issue_cert()
    result = AlpacaMcpExecutor(client=client, dry_run=False).place_certified_order_sync(
        payload, cert, portfolio, evidence, settings=_settings()
    )
    assert result["raw"] == raw
    assert "ok" not in result
    assert result["raw"] != {"ok": True}


def test_paper_host_and_designated_account_are_forced() -> None:
    env = mcp_env_from_os({"ALPACA_PAPER_TRADE": "false", "ALPACA_LIVE_TRADE": "true", "APCA_API_BASE_URL": "https://api.alpaca.markets"})
    assert env["ALPACA_PAPER_TRADE"] == "true"
    assert env["ALPACA_LIVE_TRADE"] == "false"
    assert env["APCA_API_BASE_URL"] == PAPER_API_HOST
    assert DESIGNATED_PAPER_ACCOUNT == ACCOUNT_ID
    from trade.mcp.alpaca_mcp_executor import _stdio_params

    params = _stdio_params(MCP_SERVER_SPEC, {"ALPACA_PAPER_TRADE": "false"})
    assert params.command == "uvx"
    assert params.args == ["--with", "fastmcp>=3.1.0,<4", "alpaca-mcp-server==2.3.0"]
    assert params.env["APCA_API_BASE_URL"] == PAPER_API_HOST
    assert params.env["ALPACA_PAPER_TRADE"] == "true"


def test_non_official_server_spec_is_rejected() -> None:
    with pytest.raises(ExecutionRejected, match="alpaca-mcp-server==2.3.0"):
        AlpacaMcpExecutor(server_spec="alpaca-mcp-server==9.9.9", dry_run=True)


def test_journal_persists_tool_argument_and_raw_hashes(tmp_path: Path) -> None:
    from tests.fixtures.market import make_pin_market

    journal = TradeJournal(tmp_path / "journal.jsonl")
    result = run_once(
        HackathonSettings(),
        dry_run=True,
        journal=journal,
        market=make_pin_market(),
        stance=ThesisStance.BULLISH,
    )
    assert result["ok"] is True
    order = result["order"]
    assert order["tool"] == PLACE_OPTION_ORDER
    assert order["arguments"]["order_class"] == "mleg"
    assert order["submitted"] is False
    assert order["arguments_hash"]
    assert order["raw_result_hash"]
    assert order["timestamp"]
    lines = (tmp_path / "journal.jsonl").read_text(encoding="utf-8").strip().splitlines()
    events = [json.loads(line) for line in lines]
    order_event = next(item for item in events if item["event"] == "order")
    assert order_event["tool"] == PLACE_OPTION_ORDER
    assert order_event["arguments_hash"] == order["arguments_hash"]
    assert order_event["raw_result_hash"] == order["raw_result_hash"]
    assert order_event["timestamp"] == order["timestamp"]


def test_cli_is_not_importable_on_live_profile() -> None:
    with pytest.raises(ImportError, match="not importable"):
        importlib.import_module("trade.cli")
    with pytest.raises(ImportError, match="not importable"):
        importlib.import_module("trade.cli.alpaca_cli_executor")


def test_live_runner_source_only_calls_certified_submit() -> None:
    text = (ROOT / "src" / "opticycle" / "runner.py").read_text(encoding="utf-8")
    assert "place_certified_order_sync" in text
    assert "place_option_order_sync" not in text
    assert "place_option_order(" not in text
    assert "dry_run_option_order" not in text


def test_alpacapy_is_read_verify_only() -> None:
    forbidden = ("submit_order", "close_position", "cancel_order", "replace_order")
    production = list((ROOT / "src" / "opticycle").glob("*.py")) + list(
        (ROOT / "src" / "trade").rglob("*.py")
    )
    for path in production:
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{path} still references {token}"


def test_observe_forces_paper_trading_client() -> None:
    text = (ROOT / "src" / "opticycle" / "observe.py").read_text(encoding="utf-8")
    assert "TradingClient(key, secret, paper=True)" in text
    assert "TradingClient(key, secret, paper=paper)" not in text
