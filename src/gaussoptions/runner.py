"""Unattended options-only runner: decision → risk gate → MCP/CLI → journal."""

from __future__ import annotations

import os
import time
from dataclasses import asdict
from typing import Any

from gaussoptions.journal import TradeJournal
from gaussoptions.plans import build_cycle_plan
from gaussoptions.preflight import assert_paper_env, dry_run_portfolio
from gaussoptions.risk import RiskGate, contract_greeks, scale_greeks
from gaussoptions.settings import ALLOWED_STRATEGIES, HackathonSettings
from trade.cli.alpaca_cli_executor import AlpacaCliExecutor
from trade.mcp.alpaca_mcp_executor import AlpacaMcpExecutor
from trade.routing import dry_run_option_order


def configure_backend(settings: HackathonSettings) -> None:
    os.environ["EXECUTION_BACKEND"] = settings.execution_backend
    os.environ["ALPACA_PAPER_TRADE"] = "true"
    os.environ["ALPACA_LIVE_TRADE"] = "false"


def run_once(
    settings: HackathonSettings | None = None,
    *,
    dry_run: bool = True,
    journal: TradeJournal | None = None,
    mcp_executor: AlpacaMcpExecutor | None = None,
    cli_executor: AlpacaCliExecutor | None = None,
    underlying_price: float = 500.0,
) -> dict[str, Any]:
    settings = settings or HackathonSettings()
    configure_backend(settings)
    assert_paper_env(settings)
    if settings.strategy not in ALLOWED_STRATEGIES:
        raise ValueError("stock-only strategies are disabled")
    _require_option_strategy_modules()
    log = journal or TradeJournal()
    portfolio = dry_run_portfolio(settings)
    plan = build_cycle_plan(settings, underlying_price=underlying_price)
    log.record(
        "decision",
        {
            "strategy": plan.strategy,
            "underlying": plan.underlying,
            "notes": plan.notes,
            "backend": settings.execution_backend,
        },
    )

    greeks = contract_greeks(
        "p",
        underlying_price,
        underlying_price * 0.95,
        21 / 365,
        0.04,
        0.20,
    )
    scaled = scale_greeks(greeks, plan.request.qty, plan.request.side or "sell")
    gate = RiskGate(settings).evaluate(
        plan.request,
        portfolio,
        underlying_price=underlying_price,
        option_price=plan.request.limit_price,
        proposed_delta=scaled["delta"],
        proposed_vega=scaled["vega"],
    )
    log.record(
        "risk_gate",
        {"approved": gate.approved, "reasons": gate.reasons, "greeks": scaled},
    )
    gate.raise_if_rejected()

    if dry_run:
        result = dry_run_option_order(plan.request, settings.execution_backend)
    elif settings.execution_backend == "cli":
        executor = cli_executor or AlpacaCliExecutor(dry_run=False)
        result = executor.place_option_order(plan.request)
    else:
        executor = mcp_executor or AlpacaMcpExecutor.from_env(dry_run=False)
        result = executor.place_option_order_sync(plan.request)

    entry = log.record(
        "order",
        {
            "backend": settings.execution_backend,
            "dry_run": dry_run,
            "result": result,
            "symbol": plan.request.symbol,
            "legs": plan.request.legs,
        },
    )
    return {
        "ok": True,
        "strategy": plan.strategy,
        "backend": settings.execution_backend,
        "dry_run": dry_run,
        "gate": asdict(gate),
        "order": result,
        "journal": entry,
    }


def run_loop(settings: HackathonSettings, *, dry_run: bool, once: bool) -> int:
    cycle = run_once(settings, dry_run=dry_run)
    print(cycle)
    if once:
        return 0 if cycle.get("ok") else 1
    interval = settings.interval_minutes * 60
    while True:
        time.sleep(interval)
        cycle = run_once(settings, dry_run=dry_run)
        print(cycle)


def _require_option_strategy_modules() -> None:
    """Confirm the pinned option strategies are present without importing stock paths."""
    from pathlib import Path

    option_dir = (
        Path(__file__).resolve().parents[2]
        / "vendor"
        / "pin-31374551"
        / "src"
        / "strategy"
        / "option"
    )
    wheel = (option_dir / "wheel.py").read_text(encoding="utf-8")
    spread = (option_dir / "vertical_spread.py").read_text(encoding="utf-8")
    if 'name="wheel"' not in wheel:
        raise RuntimeError("wheel option strategy is missing from the pin snapshot")
    if 'name="vertical_spread"' not in spread:
        raise RuntimeError("vertical_spread option strategy is missing from the pin snapshot")
