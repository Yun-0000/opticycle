"""Unattended options-only runner: observation → decision → risk gate → MCP → journal."""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from opticycle.journal import TradeJournal
from opticycle.observe import MarketReadClient, ObservationResult, observe_live
from opticycle.pin_option import ObservedBook, ObservedChainAdapter, ObservedFred, PinMarket
from opticycle.plans import build_cycle_plan
from opticycle.preflight import assert_paper_env, dry_run_portfolio
from opticycle.protocol import ObservationOutcome, ThesisStance
from opticycle.risk import (
    RiskEngine,
    evidence_from_chain_rows,
    option_request_from_payload,
    payload_from_request,
)
from opticycle.settings import ALLOWED_STRATEGIES, HackathonSettings
from opticycle.thesis import ThesisDisabled, ThesisAgent, persist_thesis_episode, require_live_llm
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
    llm_client: Any | None = None,
    stance: ThesisStance | str | None = None,
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
        if observation.evidence is None:
            return _closed_cycle(
                outcome=ObservationOutcome.HALT,
                reason="live evidence missing",
                dry_run=False,
                journal_entry=None,
                correlation_id=observation.correlation_id,
            )
        try:
            thesis_client = require_live_llm(llm_client)
        except ThesisDisabled as exc:
            return _closed_cycle(
                outcome=ObservationOutcome.HALT,
                reason=str(exc),
                dry_run=False,
                journal_entry=None,
                correlation_id=observation.correlation_id,
            )
        thesis = ThesisAgent(thesis_client).evaluate(observation.evidence)
        persist_thesis_episode(log, observation.evidence, thesis)
        if thesis.reason_code == "LLM_DISABLED":
            return _closed_cycle(
                outcome=ObservationOutcome.HALT,
                reason="live path requires a real model call",
                dry_run=False,
                journal_entry=None,
                correlation_id=observation.correlation_id,
            )
        if thesis.stance == ThesisStance.NO_TRADE or not thesis.accepted:
            return _closed_cycle(
                outcome=ObservationOutcome.NO_TRADE,
                reason=thesis.reason_code,
                dry_run=False,
                journal_entry=None,
                correlation_id=observation.correlation_id,
            )
        if not thesis.model_called:
            return _closed_cycle(
                outcome=ObservationOutcome.HALT,
                reason="live path requires a real model call",
                dry_run=False,
                journal_entry=None,
                correlation_id=observation.correlation_id,
            )
        pin_market = _pin_market_from_observation(observation)
        spot = pin_market.spot
        try:
            plan = build_cycle_plan(
                settings,
                market=pin_market,
                dry_run=False,
                stance=thesis.stance,
            )
        except ExecutionRejected as exc:
            if str(exc).startswith("NO_TRADE"):
                return _closed_cycle(
                    outcome=ObservationOutcome.NO_TRADE,
                    reason=str(exc),
                    dry_run=False,
                    journal_entry=None,
                    correlation_id=observation.correlation_id,
                )
            raise
    else:
        if market is None:
            raise ExecutionRejected("dry-run requires injected market")
        portfolio = dry_run_portfolio(settings)
        pin_market = market
        spot = float(pin_market.spot)
        try:
            plan = build_cycle_plan(
                settings,
                market=pin_market,
                dry_run=True,
                stance=stance,
            )
        except ExecutionRejected as exc:
            if str(exc).startswith("NO_TRADE"):
                return _closed_cycle(
                    outcome=ObservationOutcome.NO_TRADE,
                    reason=str(exc),
                    dry_run=True,
                    journal_entry=None,
                    correlation_id="",
                )
            raise

    log.record(
        "decision",
        {
            "strategy": plan.strategy,
            "underlying": plan.underlying,
            "notes": plan.notes,
            "backend": settings.execution_backend,
        },
    )

    account_id = str(portfolio.account_id or settings.paper_account_id or "")
    client_order_id = plan.request.client_order_id or f"oc-{uuid.uuid4().hex[:16]}"
    plan.request.client_order_id = client_order_id
    payload = payload_from_request(
        plan.request,
        account_id=account_id,
        client_order_id=client_order_id,
        underlying=plan.underlying,
    )
    if dry_run:
        evidence = evidence_from_chain_rows(
            underlying=plan.underlying,
            spot=Decimal(str(spot)),
            rows=pin_market.chain,
            account_id=account_id,
            timestamp=datetime.now(timezone.utc),
            quote_age_seconds=Decimal("0"),
            bars_count=int(len(pin_market.bars)),
        )
        correlation_id = evidence.correlation_id
    else:
        if observation.evidence is None:
            return _closed_cycle(
                outcome=ObservationOutcome.HALT,
                reason="live evidence missing",
                dry_run=False,
                journal_entry=None,
                correlation_id=observation.correlation_id,
            )
        evidence = observation.evidence
        correlation_id = observation.correlation_id

    engine = RiskEngine(settings)
    certificate = engine.issue(
        payload,
        portfolio,
        evidence,
        cycle_id=client_order_id,
        mode="demo" if dry_run else "live",
    )
    log.record(
        "risk_gate",
        {
            "approved": certificate.approval,
            "reasons": list(certificate.reasons),
            "payload_hash": certificate.payload_hash,
            "evidence_hash": certificate.evidence_hash,
            "account_hash": certificate.account_hash,
            "binding_hash": certificate.binding_hash,
            "max_loss": str(certificate.calculated_risk.max_loss),
            "net_credit": str(certificate.calculated_risk.net_credit),
            "net_debit": str(certificate.calculated_risk.net_debit),
            "combo_greeks": {
                "delta": str(certificate.calculated_risk.combo_delta),
                "vega": str(certificate.calculated_risk.combo_vega),
                "gamma": str(certificate.calculated_risk.combo_gamma),
                "theta": str(certificate.calculated_risk.combo_theta),
            },
        },
    )
    if certificate.veto:
        return _closed_cycle(
            outcome=ObservationOutcome.NO_TRADE,
            reason="; ".join(certificate.reasons) or "risk certificate veto",
            dry_run=dry_run,
            journal_entry=None,
            correlation_id=correlation_id,
        )

    certified_request = option_request_from_payload(payload)
    if dry_run:
        engine.verify(certificate, payload, portfolio, evidence)
        result = dry_run_option_order(certified_request, "mcp")
    else:
        executor = mcp_executor or AlpacaMcpExecutor.from_env(dry_run=False)
        result = executor.place_certified_order_sync(
            payload,
            certificate,
            portfolio,
            evidence,
            settings=settings,
        )

    entry = log.record(
        "order",
        {
            "backend": settings.execution_backend,
            "dry_run": dry_run,
            "result": result,
            "symbol": plan.request.symbol,
            "legs": plan.request.legs,
            "payload_hash": payload.payload_hash,
            "certificate_id": certificate.certificate_id,
        },
    )
    return {
        "ok": True,
        "strategy": plan.strategy,
        "backend": settings.execution_backend,
        "dry_run": dry_run,
        "gate": {"approved": certificate.approval, "reasons": list(certificate.reasons)},
        "certificate": {
            "payload_hash": certificate.payload_hash,
            "evidence_hash": certificate.evidence_hash,
            "account_hash": certificate.account_hash,
            "approval": certificate.approval,
            "veto": certificate.veto,
        },
        "order": result,
        "journal": entry,
    }


def run_loop(
    settings: HackathonSettings,
    *,
    dry_run: bool,
    once: bool,
    stance: ThesisStance | str | None = None,
) -> int:
    cycle = run_once(settings, dry_run=dry_run, stance=stance)
    print(cycle)
    if once:
        return 0 if cycle.get("ok") else 1
    interval = settings.interval_minutes * 60
    while True:
        time.sleep(interval)
        cycle = run_once(settings, dry_run=dry_run, stance=stance)
        print(cycle)
