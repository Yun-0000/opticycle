from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from gaussoptions.plans import build_cycle_plan
from gaussoptions.runner import run_once
from gaussoptions.settings import HackathonSettings
from gaussoptions.cli import main as cli_main


def test_stock_strategy_rejected_by_settings() -> None:
    with pytest.raises(ValidationError):
        HackathonSettings(strategy="momentum")  # type: ignore[arg-type]


def test_require_options_cannot_be_disabled() -> None:
    with pytest.raises(ValidationError):
        HackathonSettings(require_options=False)


def test_wheel_plan_is_occ_put() -> None:
    plan = build_cycle_plan(HackathonSettings(strategy="wheel"), underlying_price=500)
    assert plan.strategy == "wheel"
    assert plan.metadata.get("strategy_class") == "WheelStrategy"
    assert plan.metadata.get("pin") == "31374551"
    plan.request.assert_options_instrument()
    assert plan.request.symbol is not None
    assert "P" in plan.request.symbol
    assert plan.request.position_intent == "sell_to_open"


def test_vertical_spread_plan_is_multileg() -> None:
    plan = build_cycle_plan(HackathonSettings(strategy="vertical_spread"), underlying_price=500)
    assert plan.strategy == "vertical_spread"
    assert plan.metadata.get("strategy_class") == "VerticalSpreadStrategy"
    plan.request.assert_options_instrument()
    assert plan.request.is_multileg
    assert len(plan.request.legs or []) == 2


def test_run_once_decision_gate_mcp_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    from gaussoptions.journal import TradeJournal

    settings = HackathonSettings(execution_backend="mcp", strategy="wheel")
    result = run_once(settings, dry_run=True, journal=TradeJournal(tmp_path / "journal.jsonl"))
    assert result["ok"] is True
    assert result["backend"] == "mcp"
    assert result["dry_run"] is True
    assert result["gate"]["approved"] is True
    assert result["order"]["tool"] == "place_option_order"
    assert result["order"]["arguments"]["symbol"].count("P") >= 1
    lines = (tmp_path / "journal.jsonl").read_text(encoding="utf-8").strip().splitlines()
    events = [json.loads(line)["event"] for line in lines]
    assert events == ["decision", "risk_gate", "order"]


def test_run_once_cli_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    settings = HackathonSettings(execution_backend="cli", strategy="vertical_spread")
    result = run_once(settings, dry_run=True)
    assert result["order"]["backend"] == "cli"
    assert result["order"]["argv"][1:3] == ["order", "submit"]
    assert "--order-class" in result["order"]["argv"]


def test_cli_once_dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    code = cli_main(["run", "--profile", "hackathon", "--backend", "mcp", "--once", "--dry-run"])
    assert code == 0
