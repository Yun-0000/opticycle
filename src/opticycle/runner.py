"""Unattended options-only runner: observation → decision → risk gate → MCP → journal."""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from opticycle.cycle import (
    POST_SUBMIT_STATES,
    TERMINAL_STATES,
    CycleRecord,
    CycleState,
    CycleStore,
)
from opticycle.journal import TradeJournal
from opticycle.observe import AlpacaReadClient, MarketReadClient, ObservationClosed, ObservationResult, observe_live
from opticycle.pin_option import ObservedBook, ObservedChainAdapter, ObservedFred, PinMarket
from opticycle.plans import build_cycle_plan
from opticycle.preflight import assert_paper_env, dry_run_portfolio
from opticycle.protocol import (
    BrokerReceipt,
    CanonicalOrderPayload,
    ObservationOutcome,
    ThesisStance,
    ensure_utc,
    evidence_digest,
)
from opticycle.reconcile import (
    HaltLedger,
    receipt_as_dict,
    receipt_from_mcp,
    reconcile,
    report_as_dict,
)
from opticycle.risk import (
    RiskEngine,
    evidence_from_chain_rows,
    payload_from_request,
)
from opticycle.settings import ALLOWED_STRATEGIES, HackathonSettings
from opticycle.thesis import ThesisDisabled, ThesisAgent, persist_thesis_episode, require_live_llm
from trade.mcp.alpaca_mcp_executor import AlpacaMcpExecutor
from trade.orders import ExecutionRejected


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
    cycle_id: str = "",
    client_order_id: str = "",
    state: str = "",
) -> dict[str, Any]:
    return {
        "ok": False,
        "complete": False,
        "submitted": False,
        "outcome": outcome.value,
        "reason": reason,
        "backend": "mcp",
        "dry_run": dry_run,
        "order": None,
        "journal": journal_entry,
        "correlation_id": correlation_id,
        "cycle_id": cycle_id,
        "client_order_id": client_order_id,
        "state": state,
    }


def _broker_reader(broker: MarketReadClient | None, observer: MarketReadClient | None) -> Any:
    reader = broker or observer
    if reader is not None:
        return reader
    try:
        return AlpacaReadClient.from_env()
    except ObservationClosed:
        return None


def _close_open_cycle(
    store: CycleStore | None,
    cycle: CycleRecord | None,
    *,
    outcome: ObservationOutcome,
    reason: str,
) -> CycleRecord | None:
    if store is None or cycle is None:
        return cycle
    current = store.load(cycle.cycle_id)
    if current.state in TERMINAL_STATES:
        return current
    if outcome == ObservationOutcome.HALT or current.state in POST_SUBMIT_STATES:
        return store.halt(current.cycle_id, reason, forbids_new=current.state in POST_SUBMIT_STATES)
    return store.veto(current.cycle_id, reason)


def _receipt_from_record(record: CycleRecord, payload: CanonicalOrderPayload) -> BrokerReceipt:
    _ = payload
    return BrokerReceipt(
        receipt_id=uuid.uuid4().hex,
        cycle_id=record.cycle_id,
        client_order_id=record.client_order_id,
        broker_order_id=record.broker_order_id,
        received_at=ensure_utc(),
        raw_status=record.broker_status or "recovered",
        is_success=record.attempts > 0 or bool(record.broker_order_id),
        submitted=record.attempts > 0,
        response_payload={"recovered": True, "state": record.state.value},
    )


def _finalize_reconciliation(
    *,
    store: CycleStore,
    record: CycleRecord,
    payload: CanonicalOrderPayload,
    receipt: BrokerReceipt,
    report: Any,
    ledger: HaltLedger,
    log: TradeJournal,
    mcp_result: dict[str, Any] | None,
    settings: HackathonSettings,
) -> dict[str, Any]:
    if report.halt_triggered:
        store.halt(
            record.cycle_id,
            "; ".join(report.discrepancies) or report.status.value,
            forbids_new=True,
        )
        ledger.trip(
            status=report.status.value,
            reason="; ".join(report.discrepancies) or report.status.value,
            report_id=report.report_id,
        )
    else:
        if record.state is CycleState.RECONCILING:
            store.transition(record.cycle_id, CycleState.RECONCILED, reason="matched")
        elif record.state is CycleState.ACKNOWLEDGED:
            store.transition(record.cycle_id, CycleState.RECONCILING, reason="reconcile")
            store.transition(record.cycle_id, CycleState.RECONCILED, reason="matched")
        elif record.state is not CycleState.RECONCILED:
            store.transition(record.cycle_id, CycleState.RECONCILED, reason="matched")
        store.transition(record.cycle_id, CycleState.COMPLETED, reason="complete")
    final = store.load(record.cycle_id)
    recon_entry = log.record(
        "reconciliation",
        {
            "authorized_payload": payload.to_canonical_dict(),
            "mcp_raw": (mcp_result or {}).get("raw"),
            "broker_receipt": receipt_as_dict(receipt),
            "comparisons": [item.canonical_dict() for item in report.comparisons],
            "verdict": report.status.value,
            "complete": report.complete,
            "halt_triggered": report.halt_triggered,
            "containment": list(report.containment),
            "discrepancies": list(report.discrepancies),
            "report": report_as_dict(report),
            "cycle_id": final.cycle_id,
            "state": final.state.value,
            "client_order_id": final.client_order_id,
        },
    )
    complete = report.complete and final.state is CycleState.COMPLETED
    return {
        "ok": complete,
        "complete": complete,
        "submitted": bool(receipt.submitted) or final.attempts > 0,
        "outcome": ObservationOutcome.OK.value if complete else ObservationOutcome.HALT.value,
        "reason": "" if complete else ("; ".join(report.discrepancies) or report.status.value or final.halt_reason or ""),
        "backend": settings.execution_backend,
        "dry_run": False,
        "order": mcp_result,
        "receipt": receipt_as_dict(receipt),
        "reconciliation": report_as_dict(report),
        "journal": recon_entry,
        "cycle_id": final.cycle_id,
        "client_order_id": final.client_order_id,
        "payload_hash": final.payload_hash,
        "state": final.state.value,
        "recovered": mcp_result is None,
    }


def _reconcile_open_cycle(
    *,
    store: CycleStore,
    record: CycleRecord,
    payload: CanonicalOrderPayload,
    receipt: BrokerReceipt,
    broker: Any,
    ledger: HaltLedger,
    log: TradeJournal,
    settings: HackathonSettings,
    mcp_result: dict[str, Any] | None,
) -> dict[str, Any]:
    current = record
    if current.state is CycleState.ACKNOWLEDGED:
        current = store.transition(current.cycle_id, CycleState.RECONCILING, reason="reconcile")
    report = reconcile(
        payload=payload,
        receipt=receipt,
        broker=broker,
        settings=settings,
        cycle_id=current.cycle_id,
    )
    return _finalize_reconciliation(
        store=store,
        record=store.load(current.cycle_id),
        payload=payload,
        receipt=receipt,
        report=report,
        ledger=ledger,
        log=log,
        mcp_result=mcp_result,
        settings=settings,
    )


def _resume_post_submit(
    *,
    store: CycleStore,
    record: CycleRecord,
    ledger: HaltLedger,
    log: TradeJournal,
    settings: HackathonSettings,
    broker: MarketReadClient | None,
    observer: MarketReadClient | None,
) -> dict[str, Any]:
    """Kill/restart recovery. Same cycle, payload, client id. No second order."""
    payload = record.payload()
    if payload is None:
        halted = store.halt(record.cycle_id, "recovered cycle missing payload", forbids_new=True)
        ledger.trip(status="unknown", reason=halted.halt_reason or "unknown", report_id=halted.cycle_id)
        return _closed_cycle(
            outcome=ObservationOutcome.HALT,
            reason=halted.halt_reason or "unknown",
            dry_run=False,
            journal_entry=None,
            correlation_id="",
            cycle_id=halted.cycle_id,
            client_order_id=halted.client_order_id,
            state=halted.state.value,
        )
    reader = _broker_reader(broker, observer)
    if record.state is CycleState.SUBMITTING:
        if reader is None:
            halted = store.halt(record.cycle_id, "unknown broker state", forbids_new=True)
            ledger.trip(status="unknown", reason="unknown broker state", report_id=halted.cycle_id)
            return _closed_cycle(
                outcome=ObservationOutcome.HALT,
                reason="unknown broker state",
                dry_run=False,
                journal_entry=None,
                correlation_id="",
                cycle_id=halted.cycle_id,
                client_order_id=halted.client_order_id,
                state=halted.state.value,
            )
        receipt = _receipt_from_record(record, payload)
        try:
            listed = None
            if hasattr(reader, "fetch_orders_by_client_id"):
                listed = reader.fetch_orders_by_client_id(record.client_order_id)
            orders = list(listed or [])
        except Exception:
            orders = None
        if orders is None:
            halted = store.halt(record.cycle_id, "unknown broker state", forbids_new=True)
            ledger.trip(status="unknown", reason="unknown broker state", report_id=halted.cycle_id)
            return _closed_cycle(
                outcome=ObservationOutcome.HALT,
                reason="unknown broker state",
                dry_run=False,
                journal_entry=None,
                correlation_id="",
                cycle_id=halted.cycle_id,
                client_order_id=halted.client_order_id,
                state=halted.state.value,
            )
        if not orders:
            halted = store.halt(record.cycle_id, "unknown broker state", forbids_new=True)
            ledger.trip(status="unknown", reason="unknown broker state forbids a new cycle", report_id=halted.cycle_id)
            return _closed_cycle(
                outcome=ObservationOutcome.HALT,
                reason="unknown broker state",
                dry_run=False,
                journal_entry=None,
                correlation_id="",
                cycle_id=halted.cycle_id,
                client_order_id=halted.client_order_id,
                state=halted.state.value,
            )
        order = orders[0]
        broker_order_id = str(getattr(order, "id", None) or getattr(order, "order_id", None) or record.broker_order_id or "")
        broker_status = str(getattr(order, "status", "") or "recovered")
        acked = store.transition(
            record.cycle_id,
            CycleState.ACKNOWLEDGED,
            broker_order_id=broker_order_id or None,
            broker_status=broker_status,
            reason="recovered submit without resubmit",
        )
        receipt = BrokerReceipt(
            receipt_id=uuid.uuid4().hex,
            cycle_id=acked.cycle_id,
            client_order_id=acked.client_order_id,
            broker_order_id=acked.broker_order_id,
            received_at=ensure_utc(),
            raw_status=broker_status,
            is_success=True,
            submitted=True,
            response_payload={"recovered": True, "id": broker_order_id, "status": broker_status},
        )
        return _reconcile_open_cycle(
            store=store,
            record=acked,
            payload=payload,
            receipt=receipt,
            broker=reader,
            ledger=ledger,
            log=log,
            settings=settings,
            mcp_result=None,
        )
    receipt = _receipt_from_record(record, payload)
    return _reconcile_open_cycle(
        store=store,
        record=record,
        payload=payload,
        receipt=receipt,
        broker=reader,
        ledger=ledger,
        log=log,
        settings=settings,
        mcp_result=None,
    )


def _live_submit_and_reconcile(
    *,
    store: CycleStore,
    record: CycleRecord,
    payload: CanonicalOrderPayload,
    certificate: Any,
    portfolio: Any,
    evidence: Any,
    executor: AlpacaMcpExecutor,
    broker: Any,
    ledger: HaltLedger,
    log: TradeJournal,
    settings: HackathonSettings,
    plan: Any,
) -> dict[str, Any]:
    submitting = store.transition(record.cycle_id, CycleState.SUBMITTING, reason="persist before mcp")
    result = executor.place_certified_order_sync(
        payload,
        certificate,
        portfolio,
        evidence,
        settings=settings,
    )
    receipt = receipt_from_mcp(
        cycle_id=submitting.cycle_id,
        payload=payload,
        mcp_result=result,
    )
    store.record_attempt(
        submitting.cycle_id,
        mcp_tool=str(result.get("tool") or "place_option_order"),
        arguments_hash=str(result.get("arguments_hash") or ""),
        broker_order_id=receipt.broker_order_id,
        raw_status=receipt.raw_status,
        raw_hash=str(result.get("raw_result_hash") or ""),
    )
    acked = store.transition(
        submitting.cycle_id,
        CycleState.ACKNOWLEDGED,
        broker_order_id=receipt.broker_order_id,
        broker_status=receipt.raw_status,
        reason="mcp acknowledged",
    )
    log.record(
        "order",
        {
            "backend": settings.execution_backend,
            "dry_run": False,
            "result": result,
            "symbol": plan.request.symbol,
            "legs": plan.request.legs,
            "payload_hash": payload.payload_hash,
            "certificate_id": certificate.certificate_id,
            "tool": result.get("tool"),
            "arguments_hash": result.get("arguments_hash"),
            "timestamp": result.get("timestamp"),
            "raw_result_hash": result.get("raw_result_hash"),
            "authorized_payload": payload.to_canonical_dict(),
            "cycle_id": acked.cycle_id,
            "client_order_id": acked.client_order_id,
            "state": acked.state.value,
        },
    )
    log.record(
        "broker_receipt",
        {
            "authorized_payload": payload.to_canonical_dict(),
            "mcp_raw": result.get("raw"),
            "receipt": receipt_as_dict(receipt),
            "submitted": receipt.submitted,
            "complete": False,
            "cycle_id": acked.cycle_id,
            "client_order_id": acked.client_order_id,
        },
    )
    return _reconcile_open_cycle(
        store=store,
        record=acked,
        payload=payload,
        receipt=receipt,
        broker=broker,
        ledger=ledger,
        log=log,
        settings=settings,
        mcp_result=result,
    )


def run_once(
    settings: HackathonSettings | None = None,
    *,
    dry_run: bool = True,
    journal: TradeJournal | None = None,
    mcp_executor: AlpacaMcpExecutor | None = None,
    observer: MarketReadClient | None = None,
    broker: MarketReadClient | None = None,
    market: PinMarket | None = None,
    underlying_price: float | None = None,
    llm_client: Any | None = None,
    stance: ThesisStance | str | None = None,
    halt_ledger: HaltLedger | None = None,
    cycle_store: CycleStore | None = None,
) -> dict[str, Any]:
    settings = settings or HackathonSettings()
    configure_backend(settings)
    assert_paper_env(settings)
    if settings.strategy not in ALLOWED_STRATEGIES:
        raise ValueError("only SPY defined-risk vertical is enabled")
    log = journal or TradeJournal()
    ledger = halt_ledger or HaltLedger(log.path.with_name("halt.json"))
    store = cycle_store or (None if dry_run else CycleStore(log.path.with_name("cycles.sqlite")))
    cycle: CycleRecord | None = None

    if not dry_run and ledger.is_halted():
        return {
            "ok": False,
            "complete": False,
            "submitted": False,
            "outcome": ObservationOutcome.HALT.value,
            "reason": ledger.reason(),
            "backend": "mcp",
            "dry_run": False,
            "order": None,
            "journal": None,
            "correlation_id": "",
        }

    if not dry_run:
        if market is not None:
            raise ExecutionRejected("live path cannot accept fixture market")
        if underlying_price is not None:
            raise ExecutionRejected("live path cannot use a hardcoded underlying price")
        assert store is not None
        if store.forbids_new_cycle():
            return _closed_cycle(
                outcome=ObservationOutcome.HALT,
                reason="unknown broker state forbids a new cycle",
                dry_run=False,
                journal_entry=None,
                correlation_id="",
            )
        active = store.active_cycle()
        if active is not None and active.state in POST_SUBMIT_STATES:
            return _resume_post_submit(
                store=store,
                record=active,
                ledger=ledger,
                log=log,
                settings=settings,
                broker=broker,
                observer=observer,
            )
        if active is not None and active.state not in TERMINAL_STATES:
            store.halt(
                active.cycle_id,
                "pre-submit restart abandoned without broker execution",
                forbids_new=False,
            )
        cycle = store.begin_cycle()
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
            closed = _close_open_cycle(
                store, cycle, outcome=observation.outcome, reason=observation.reason
            )
            return _closed_cycle(
                outcome=observation.outcome,
                reason=observation.reason,
                dry_run=False,
                journal_entry=None,
                correlation_id=observation.correlation_id,
                cycle_id=closed.cycle_id if closed else "",
                client_order_id=closed.client_order_id if closed else "",
                state=closed.state.value if closed else "",
            )
        portfolio = observation.portfolio
        if portfolio is None:
            closed = _close_open_cycle(
                store, cycle, outcome=ObservationOutcome.HALT, reason="account snapshot missing"
            )
            return _closed_cycle(
                outcome=ObservationOutcome.HALT,
                reason="account snapshot missing",
                dry_run=False,
                journal_entry=None,
                correlation_id=observation.correlation_id,
                cycle_id=closed.cycle_id if closed else "",
                client_order_id=closed.client_order_id if closed else "",
                state=closed.state.value if closed else "",
            )
        if observation.evidence is None:
            closed = _close_open_cycle(
                store, cycle, outcome=ObservationOutcome.HALT, reason="live evidence missing"
            )
            return _closed_cycle(
                outcome=ObservationOutcome.HALT,
                reason="live evidence missing",
                dry_run=False,
                journal_entry=None,
                correlation_id=observation.correlation_id,
                cycle_id=closed.cycle_id if closed else "",
                client_order_id=closed.client_order_id if closed else "",
                state=closed.state.value if closed else "",
            )
        if store is not None and cycle is not None:
            store.attach_snapshot(cycle.cycle_id, evidence_digest(observation.evidence))
        try:
            thesis_client = require_live_llm(llm_client)
        except ThesisDisabled as exc:
            closed = _close_open_cycle(
                store, cycle, outcome=ObservationOutcome.HALT, reason=str(exc)
            )
            return _closed_cycle(
                outcome=ObservationOutcome.HALT,
                reason=str(exc),
                dry_run=False,
                journal_entry=None,
                correlation_id=observation.correlation_id,
                cycle_id=closed.cycle_id if closed else "",
                client_order_id=closed.client_order_id if closed else "",
                state=closed.state.value if closed else "",
            )
        thesis = ThesisAgent(thesis_client).evaluate(observation.evidence)
        persist_thesis_episode(log, observation.evidence, thesis)
        if thesis.reason_code == "LLM_DISABLED":
            closed = _close_open_cycle(
                store, cycle, outcome=ObservationOutcome.HALT, reason="live path requires a real model call"
            )
            return _closed_cycle(
                outcome=ObservationOutcome.HALT,
                reason="live path requires a real model call",
                dry_run=False,
                journal_entry=None,
                correlation_id=observation.correlation_id,
                cycle_id=closed.cycle_id if closed else "",
                client_order_id=closed.client_order_id if closed else "",
                state=closed.state.value if closed else "",
            )
        if thesis.stance == ThesisStance.NO_TRADE or not thesis.accepted:
            closed = _close_open_cycle(
                store, cycle, outcome=ObservationOutcome.NO_TRADE, reason=thesis.reason_code
            )
            return _closed_cycle(
                outcome=ObservationOutcome.NO_TRADE,
                reason=thesis.reason_code,
                dry_run=False,
                journal_entry=None,
                correlation_id=observation.correlation_id,
                cycle_id=closed.cycle_id if closed else "",
                client_order_id=closed.client_order_id if closed else "",
                state=closed.state.value if closed else "",
            )
        if not thesis.model_called:
            closed = _close_open_cycle(
                store, cycle, outcome=ObservationOutcome.HALT, reason="live path requires a real model call"
            )
            return _closed_cycle(
                outcome=ObservationOutcome.HALT,
                reason="live path requires a real model call",
                dry_run=False,
                journal_entry=None,
                correlation_id=observation.correlation_id,
                cycle_id=closed.cycle_id if closed else "",
                client_order_id=closed.client_order_id if closed else "",
                state=closed.state.value if closed else "",
            )
        if store is not None and cycle is not None:
            cycle = store.transition(cycle.cycle_id, CycleState.THESIS_READY, reason="thesis accepted")
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
                closed = _close_open_cycle(
                    store, cycle, outcome=ObservationOutcome.NO_TRADE, reason=str(exc)
                )
                return _closed_cycle(
                    outcome=ObservationOutcome.NO_TRADE,
                    reason=str(exc),
                    dry_run=False,
                    journal_entry=None,
                    correlation_id=observation.correlation_id,
                    cycle_id=closed.cycle_id if closed else "",
                    client_order_id=closed.client_order_id if closed else "",
                    state=closed.state.value if closed else "",
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
    if cycle is not None:
        client_order_id = cycle.client_order_id
    else:
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
            closed = _close_open_cycle(
                store, cycle, outcome=ObservationOutcome.HALT, reason="live evidence missing"
            )
            return _closed_cycle(
                outcome=ObservationOutcome.HALT,
                reason="live evidence missing",
                dry_run=False,
                journal_entry=None,
                correlation_id=observation.correlation_id,
                cycle_id=closed.cycle_id if closed else "",
                client_order_id=closed.client_order_id if closed else "",
                state=closed.state.value if closed else "",
            )
        evidence = observation.evidence
        correlation_id = observation.correlation_id
        if store is not None and cycle is not None:
            cycle = store.transition(
                cycle.cycle_id,
                CycleState.CANDIDATES_READY,
                payload=payload,
                reason="candidates ready",
            )

    engine = RiskEngine(settings)
    certificate = engine.issue(
        payload,
        portfolio,
        evidence,
        cycle_id=cycle.cycle_id if cycle is not None else client_order_id,
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
        closed = _close_open_cycle(
            store, cycle, outcome=ObservationOutcome.NO_TRADE,
            reason="; ".join(certificate.reasons) or "risk certificate veto",
        )
        return _closed_cycle(
            outcome=ObservationOutcome.NO_TRADE,
            reason="; ".join(certificate.reasons) or "risk certificate veto",
            dry_run=dry_run,
            journal_entry=None,
            correlation_id=correlation_id,
            cycle_id=closed.cycle_id if closed else "",
            client_order_id=closed.client_order_id if closed else "",
            state=closed.state.value if closed else "",
        )
    if store is not None and cycle is not None:
        cycle = store.authorize(cycle.cycle_id, payload, certificate)

    executor = mcp_executor or AlpacaMcpExecutor.from_env(dry_run=dry_run)
    if not dry_run:
        assert store is not None and cycle is not None
        reader = _broker_reader(broker, observer)
        return _live_submit_and_reconcile(
            store=store,
            record=cycle,
            payload=payload,
            certificate=certificate,
            portfolio=portfolio,
            evidence=evidence,
            executor=executor,
            broker=reader,
            ledger=ledger,
            log=log,
            settings=settings,
            plan=plan,
        )

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
            "tool": result.get("tool"),
            "arguments_hash": result.get("arguments_hash"),
            "timestamp": result.get("timestamp"),
            "raw_result_hash": result.get("raw_result_hash"),
            "authorized_payload": payload.to_canonical_dict(),
        },
    )
    return {
        "ok": True,
        "complete": False,
        "submitted": False,
        "strategy": plan.strategy,
        "backend": settings.execution_backend,
        "dry_run": True,
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
