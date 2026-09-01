from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from opticycle.plans import build_cycle_plan
from opticycle.protocol import ThesisStance
from opticycle.runner import run_once
from opticycle.settings import HackathonSettings
from opticycle.cli import main as cli_main


def test_stock_strategy_rejected_by_settings() -> None:
    with pytest.raises(ValidationError):
        HackathonSettings(strategy="momentum")  # type: ignore[arg-type]


def test_require_options_cannot_be_disabled() -> None:
    with pytest.raises(ValidationError):
        HackathonSettings(require_options=False)


def test_wheel_strategy_rejected_by_settings() -> None:
    with pytest.raises(ValidationError):
        HackathonSettings(strategy="wheel")  # type: ignore[arg-type]


def test_cli_backend_rejected_by_settings() -> None:
    with pytest.raises(ValidationError):
        HackathonSettings(execution_backend="cli")  # type: ignore[arg-type]


def test_vertical_spread_plan_is_multileg() -> None:
    from tests.fixtures.market import make_pin_market

    plan = build_cycle_plan(
        HackathonSettings(strategy="vertical_spread"),
        market=make_pin_market(),
        stance=ThesisStance.BULLISH,
    )
    assert plan.strategy == "vertical_spread"
    assert plan.metadata.get("strategy_class") == "VerticalSpreadStrategy"
    assert plan.metadata.get("spread_type") == "bull_put"
    assert plan.metadata.get("stance") == "BULLISH"
    plan.request.assert_options_instrument()
    assert plan.request.is_multileg
    assert len(plan.request.legs or []) == 2
    assert all("P" in str(leg["symbol"]) for leg in plan.request.legs or [])
    assert plan.request.limit_price is not None
    assert float(plan.request.limit_price) < 0


def test_run_once_decision_gate_mcp_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    from opticycle.journal import TradeJournal

    from tests.fixtures.market import make_pin_market

    settings = HackathonSettings(execution_backend="mcp", strategy="vertical_spread")
    result = run_once(
        settings,
        dry_run=True,
        journal=TradeJournal(tmp_path / "journal.jsonl"),
        market=make_pin_market(),
        stance=ThesisStance.BULLISH,
    )
    assert result["ok"] is True
    assert result["backend"] == "mcp"
    assert result["dry_run"] is True
    assert result["strategy"] == "vertical_spread"
    assert result["gate"]["approved"] is True
    assert result["order"]["tool"] == "place_option_order"
    assert result["order"]["arguments"]["order_class"] == "mleg"
    lines = (tmp_path / "journal.jsonl").read_text(encoding="utf-8").strip().splitlines()
    events = [json.loads(line)["event"] for line in lines]
    assert events == ["decision", "risk_gate", "order"]


def test_cli_backend_rejected_for_live() -> None:
    with pytest.raises(ValidationError, match="mcp"):
        HackathonSettings(execution_backend="cli")  # type: ignore[arg-type]


def test_cli_once_dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    code = cli_main(
        ["run", "--profile", "hackathon", "--backend", "mcp", "--once", "--dry-run"]
    )
    assert code == 0


def test_cli_parser_rejects_cli_and_wheel() -> None:
    with pytest.raises(SystemExit):
        cli_main(["run", "--profile", "hackathon", "--backend", "cli", "--once", "--dry-run"])
    with pytest.raises(SystemExit):
        cli_main(["run", "--profile", "hackathon", "--strategy", "wheel", "--once", "--dry-run"])


def test_bearish_plan_is_bear_call_credit() -> None:
    from tests.fixtures.market import make_pin_market

    plan = build_cycle_plan(
        HackathonSettings(strategy="vertical_spread"),
        market=make_pin_market(),
        stance=ThesisStance.BEARISH,
    )
    assert plan.metadata.get("spread_type") == "bear_call"
    assert plan.metadata.get("stance") == "BEARISH"
    assert all("C" in str(leg["symbol"]) for leg in plan.request.legs or [])
    assert plan.request.limit_price is not None
    assert float(plan.request.limit_price) < 0


def test_missing_or_no_trade_stance_is_no_trade() -> None:
    from tests.fixtures.market import make_pin_market
    from trade.orders import ExecutionRejected

    market = make_pin_market()
    with pytest.raises(ExecutionRejected, match="NO_TRADE"):
        build_cycle_plan(HackathonSettings(), market=market, stance=None)
    with pytest.raises(ExecutionRejected, match="NO_TRADE"):
        build_cycle_plan(HackathonSettings(), market=market, stance=ThesisStance.NO_TRADE)


def test_pin_does_not_use_rsi_trend_get_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.fixtures.market import make_pin_market
    import opticycle.pin_option as pin

    calls = {"get_signal": 0}
    original_install = pin._install_pin_modules

    def wrapped_install(market):
        loaded = original_install(market)
        cls = loaded["VerticalSpreadStrategy"]
        original_signal = cls.get_signal

        def guarded(self, *args, **kwargs):
            calls["get_signal"] += 1
            raise AssertionError("VerticalSpreadStrategy.get_signal must not pick legs")
            return original_signal(self, *args, **kwargs)

        monkeypatch.setattr(cls, "get_signal", guarded)
        return loaded

    monkeypatch.setattr(pin, "_install_pin_modules", wrapped_install)
    plan = pin.build_pin_cycle_plan(
        HackathonSettings(),
        market=make_pin_market(),
        stance=ThesisStance.BULLISH,
    )
    assert plan.metadata["spread_type"] == "bull_put"
    assert calls["get_signal"] == 0


def test_debit_spread_types_are_no_trade() -> None:
    from tests.fixtures.market import make_pin_market
    from trade.orders import ExecutionRejected
    import opticycle.pin_option as pin

    market = make_pin_market()
    settings = HackathonSettings()
    loaded = pin._install_pin_modules(market)
    strategy = loaded["VerticalSpreadStrategy"](
        {"dte_min": 7, "dte_max": 45, "max_stock_price": 10_000, "min_stock_price": 1}
    )
    strategy.provider = market.provider
    strategy.fred = market.fred
    with pytest.raises(ExecutionRejected, match="NO_TRADE"):
        pin._credit_candidate_for_type(strategy, market, "SPY", "bull_call")
    with pytest.raises(ExecutionRejected, match="NO_TRADE"):
        pin._credit_candidate_for_type(strategy, market, "SPY", "bear_put")


def test_live_runner_passes_thesis_stance_to_build_cycle_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import datetime, timezone
    from opticycle.journal import TradeJournal
    from tests.test_live_observation import _PartialClient, _account
    from tests.test_thesis_agent import ScriptedLlm, _valid_payload
    from opticycle.thesis import summarize_features
    from pathlib import Path
    import tempfile

    captured: dict = {}

    def fake_build(settings, **kwargs):
        captured.update(kwargs)
        from trade.orders import ExecutionRejected

        raise ExecutionRejected("NO_TRADE: captured stance")

    monkeypatch.setattr("opticycle.runner.build_cycle_plan", fake_build)
    now = datetime.now(timezone.utc)
    bars = [
        type("Bar", (), {"open": 499, "high": 501, "low": 498, "close": 500, "volume": 1_000_000, "timestamp": now})()
        for _ in range(20)
    ]
    snap = type(
        "Snap",
        (),
        {
            "latest_quote": type("Q", (), {"bid_price": 1.2, "ask_price": 1.4})(),
            "latest_trade": type("T", (), {"price": 1.3})(),
            "greeks": type("G", (), {"delta": -0.2, "gamma": 0.01, "theta": -0.05, "vega": 0.1})(),
        },
    )()
    observer = _PartialClient(
        account=_account(),
        quote={"SPY": type("Quote", (), {"bid_price": 500.0, "ask_price": 500.2, "timestamp": now})()},
        bars={"SPY": bars},
        chain={"SPY260918P00500000": snap, "SPY260918P00490000": snap},
    )

    def evaluate(self, evidence):
        from opticycle.protocol import ThesisRecord
        from decimal import Decimal

        features = summarize_features(evidence)
        payload = _valid_payload(features, "BULLISH")
        return ThesisRecord(
            stance=ThesisStance.BULLISH,
            confidence=Decimal("0.82"),
            evidence=tuple(payload["evidence"]),
            assumptions=tuple(payload["assumptions"]),
            invalidation_conditions=tuple(payload["invalidation_conditions"]),
            observation_timestamp=evidence.timestamp,
            reason_code="TREND_ALIGNED",
            feature_correlation_id=evidence.correlation_id,
            model_called=True,
            accepted=True,
        )

    monkeypatch.setattr("opticycle.thesis.ThesisAgent.evaluate", evaluate)
    result = run_once(
        HackathonSettings(),
        dry_run=False,
        observer=observer,
        llm_client=ScriptedLlm([{}]),
        journal=TradeJournal(Path(tempfile.mkdtemp()) / "journal.jsonl"),
    )
    assert captured.get("stance") == ThesisStance.BULLISH
    assert result["ok"] is False
    assert result["outcome"] == "NO_TRADE"
