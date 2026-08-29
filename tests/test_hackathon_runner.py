from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from opticycle.plans import build_cycle_plan
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

    plan = build_cycle_plan(HackathonSettings(strategy="vertical_spread"), market=make_pin_market())
    assert plan.strategy == "vertical_spread"
    assert plan.metadata.get("strategy_class") == "VerticalSpreadStrategy"
    plan.request.assert_options_instrument()
    assert plan.request.is_multileg
    assert len(plan.request.legs or []) == 2


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
    code = cli_main(["run", "--profile", "hackathon", "--backend", "mcp", "--once", "--dry-run"])
    assert code == 0


def test_cli_parser_rejects_cli_and_wheel() -> None:
    with pytest.raises(SystemExit):
        cli_main(["run", "--profile", "hackathon", "--backend", "cli", "--once", "--dry-run"])
    with pytest.raises(SystemExit):
        cli_main(["run", "--profile", "hackathon", "--strategy", "wheel", "--once", "--dry-run"])
