"""Unattended options-only runner: observation → decision → risk gate → MCP → journal."""

from __future__ import annotations

import os
import time
from dataclasses import asdict
from typing import Any

from opticycle.journal import TradeJournal
from opticycle.observe import MarketReadClient, ObservationResult, observe_live
from opticycle.pin_option import ObservedBook, ObservedChainAdapter, ObservedFred, PinMarket
from opticycle.plans import build_cycle_plan
from opticycle.preflight import assert_paper_env, dry_run_portfolio
from opticycle.protocol import ObservationOutcome
from opticycle.risk import RiskGate, contract_greeks, scale_greeks
from opticycle.settings import ALLOWED_STRATEGIES, HackathonSettings
from trade.mcp.alpaca_mcp_executor import AlpacaMcpExecutor
from trade.orders import ExecutionRejected
from trade.routing import dry_run_option_order


def configure_backend(settings: HackathonSettings) -> None:
    if settings.execution_backend != "mcp":
        raise ValueError("official MCP is the only live execution channel")
    os.environ["EXECUTION_BACKEND"] = "mcp"
    os.environ["ALPACA_PAPER_TRADE"] = "true"
    os.environ["ALPACA_LIVE_TRADE"] = "false"


def _pin_market_from_observation(obs: ObservationResult) -> PinMarket:
    if obs.evidence is None or obs.portfolio is None or obs.bars is None or obs.chain is None:
        raise ExecutionRejected("live observation is incomplete")
    equity = float(obs.portfolio.equity)
    cash = float(obs.portfolio.cash)
    return PinMarket(
        spot=float(obs.evidence.spot_price),
        bars=obs.bars,
        chain=obs.chain,
        equity=equity,
        cash=cash,
        book=ObservedBook(equity=equity, cash=cash),
        provider=ObservedChainAdapter(obs.chain),
        fred=ObservedFred(),
    )


def _closed_cycle(
    *,
    outcome: ObservationOutcome,
    reason: str,
    dry_run: bool,
    journal_entry: dict[str, Any] | None,
    correlation_id: str,
) -> dict[str, Any]:
    return {
        "ok": False,
        "outcome": outcome.value,
        "reason": reason,
        "backend": "mcp",
        "dry_run": dry_run,
        "order": None,
        "journal": journal_entry,
        "correlation_id": correlation_id,
    }


def run_once(
    settings: HackathonSettings | None = None,
    *,
    dry_run: bool = True,
    journal: TradeJournal | None = None,
    mcp_executor: AlpacaMcpExecutor | None = None,
    observer: MarketReadClient | None = None,
    market: PinMarket | None = None,
    underlying_price: float | None = None,
) -> dict[str, Any]:
    settings = settings or HackathonSettings()
    configure_backend(settings)
    assert_paper_env(settings)
    if settings.strategy not in ALLOWED_STRATEGIES:
        raise ValueError("only SPY defined-risk vertical is enabled")
    log = journal or TradeJournal()

    if not dry_run:
        if market is not None:
            raise ExecutionRejected("live path cannot accept fixture market")
        if underlying_price is not None:
            raise ExecutionRejected("live path cannot use a hardcoded underlying price")
        observation = observe_live(settings, client=observer)
        log.record(
            "observation",
            {
                "outcome": observation.outcome.value,
                "reason": observation.reason,
                "correlation_id": observation.correlation_id,
                "datums": [
                    {
                        "kind": datum.kind,
                        "source": datum.source,
                        "timestamp": datum.timestamp.isoformat(),
                        "freshness_seconds": str(datum.freshness_seconds),
                        "correlation_id": datum.correlation_id,
                        "ok": datum.ok,
                        "detail": datum.detail,
                    }
                    for datum in observation.datums
                ],
            },
        )
        if observation.outcome != ObservationOutcome.OK:
            return _closed_cycle(
                outcome=observation.outcome,
                reason=observation.reason,
                dry_run=False,
                journal_entry=None,
                correlation_id=observation.correlation_id,
            )
        portfolio = observation.portfolio
        if portfolio is None:
            return _closed_cycle(
                outcome=ObservationOutcome.HALT,
                reason="account snapshot missing",
                dry_run=False,
                journal_entry=None,
                correlation_id=observation.correlation_id,
            )
        pin_market = _pin_market_from_observation(observation)
        spot = pin_market.spot
        plan = build_cycle_plan(settings, market=pin_market, dry_run=False)
    else:
        if market is None:
            raise ExecutionRejected("dry-run requires injected market")
        portfolio = dry_run_portfolio(settings)
        pin_market = market
        spot = float(pin_market.spot)
        plan = build_cycle_plan(settings, market=pin_market, dry_run=True)

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
        spot,
        spot * 0.95,
        21 / 365,
        0.04,
        0.20,
    )
    scaled = scale_greeks(greeks, plan.request.qty, plan.request.side or "sell")
    gate = RiskGate(settings).evaluate(
        plan.request,
        portfolio,
        underlying_price=spot,
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
        result = dry_run_option_order(plan.request, "mcp")
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
