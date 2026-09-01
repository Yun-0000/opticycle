"""Unattended options-only runner: observation → decision → risk gate → MCP → journal."""

from __future__ import annotations

import contextvars
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
from opticycle.alpaca_cli_readonly import AlpacaCliReadError, AlpacaCliReadOnly
from opticycle.journal import TradeJournal
from opticycle.ledger import CHANNELS, EpisodeBuilder, OUTCOMES, snapshot_from_observation
from opticycle.observe import AlpacaReadClient, MarketReadClient, ObservationClosed, ObservationResult, observe_live
from opticycle.pin_option import (
    ObservedBook,
    ObservedChainAdapter,
    ObservedFred,
    PinMarket,
    apply_risk_budget_qty,
)
from opticycle.plans import build_cycle_plan
from opticycle.position_manager import manage_open_positions
from opticycle.pnl import SOURCE_LIVE_BROKER, pnl_from_snapshot, snapshot_from_client, snapshot_from_objects
from opticycle.preflight import assert_paper_env, dry_run_portfolio
from opticycle.replay_market import replay_pin_market
from opticycle.protocol import (
    BrokerReceipt,
    CanonicalOrderPayload,
    ObservationOutcome,
    ReconciliationStatus,
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
from trade.mcp.alpaca_mcp_executor import PLACE_OPTION_ORDER, AlpacaMcpExecutor, digest_canonical
from trade.orders import ExecutionRejected

_CURRENT_EPISODE: contextvars.ContextVar[EpisodeBuilder | None] = contextvars.ContextVar(
    "opticycle_episode", default=None
)


def _evidence_channel(*, dry_run: bool, provenance: str | None) -> str:
    if provenance:
        if provenance not in CHANNELS:
            raise ValueError(f"provenance must be one of {CHANNELS}")
        return provenance
    return "replay" if dry_run else "live_paper"


def _commit_episode(
    *,
    outcome: str,
    reason: str,
    cycle_id: str = "",
    client_order_id: str = "",
    extra: dict[str, Any] | None = None,
    episode: EpisodeBuilder | None = None,
) -> dict[str, Any] | None:
    builder = episode if episode is not None else _CURRENT_EPISODE.get()
    if builder is None:
        return None
    mapped = outcome if outcome in OUTCOMES else "HALT"
    return builder.commit(
        outcome=mapped,
        reason=reason,
        cycle_id=cycle_id,
        client_order_id=client_order_id,
        extra=extra,
    )


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
    ledger_outcome: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record = _commit_episode(
        outcome=ledger_outcome or outcome.value,
        reason=reason,
        cycle_id=cycle_id,
        client_order_id=client_order_id,
        extra=extra,
    )
    if journal_entry is None:
        journal_entry = record
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
        "record_id": (record or {}).get("record_id", ""),
        "claim": (record or {}).get("claim", ""),
        "commit_sha": (record or {}).get("commit_sha", ""),
        "channel": (record or {}).get("channel", ""),
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


def _pnl_from_broker(broker: Any) -> Any | None:
    if broker is None:
        return None
    try:
        snap = snapshot_from_client(broker, source=SOURCE_LIVE_BROKER)
        return pnl_from_snapshot(snap)
    except Exception:
        return None


def _mcp_attempt_fields(
    *,
    payload: CanonicalOrderPayload,
    mcp_result: dict[str, Any] | None,
    store: CycleStore | None,
    cycle_id: str,
) -> dict[str, Any]:
    if mcp_result:
        fields = {
            "tool": str(mcp_result.get("tool") or PLACE_OPTION_ORDER),
            "arguments_hash": str(mcp_result.get("arguments_hash") or ""),
            "submitted": bool(mcp_result.get("submitted")),
            "dry_run": bool(mcp_result.get("dry_run")),
            "order_class": "mleg",
        }
        if mcp_result.get("mcp_call_timeout"):
            fields["mcp_call_timeout"] = True
            fields["raw_result_hash"] = str(mcp_result.get("raw_result_hash") or "")
        return fields
    attempt = store.attempt(cycle_id) if store is not None else None
    if attempt:
        return {
            "tool": str(attempt.get("mcp_tool") or PLACE_OPTION_ORDER),
            "arguments_hash": str(attempt.get("arguments_hash") or ""),
            "submitted": True,
            "dry_run": False,
            "order_class": "mleg",
        }
    return {
        "tool": PLACE_OPTION_ORDER,
        "arguments_hash": digest_canonical(payload.to_mcp_arguments()),
        "submitted": True,
        "dry_run": False,
        "order_class": "mleg",
    }


def _stamp_matched_episode(
    *,
    report: Any,
    receipt: BrokerReceipt,
    pnl: Any | None,
    payload: CanonicalOrderPayload,
    mcp_result: dict[str, Any] | None,
    store: CycleStore,
    cycle_id: str,
) -> dict[str, Any]:
    """Write MCP attempt, broker readback, fill + P&L onto the open episode."""
    fill = {
        "filled_qty": int(report.filled_qty),
        "filled_avg_price": str(report.filled_avg_price) if report.filled_avg_price is not None else None,
        "realized_pnl": None if pnl is None or pnl.realized_pnl is None else str(pnl.realized_pnl),
        "unrealized_pnl": None if pnl is None or pnl.unrealized_pnl is None else str(pnl.unrealized_pnl),
        "end_of_cycle_equity": (
            None if pnl is None or pnl.end_of_cycle_equity is None else str(pnl.end_of_cycle_equity)
        ),
    }
    builder = _CURRENT_EPISODE.get()
    if builder is None:
        return fill
    mcp_attempt = _mcp_attempt_fields(
        payload=payload, mcp_result=mcp_result, store=store, cycle_id=cycle_id
    )
    builder.set(
        "candidate_set",
        {
            "payload_hash": payload.payload_hash,
            "client_order_id": payload.client_order_id,
            "order_class": payload.order_class,
            "qty": payload.qty,
            "limit_price": str(payload.limit_price),
            "legs": [
                {"symbol": leg.symbol, "side": leg.side.value, "ratio_qty": str(leg.ratio_qty)}
                for leg in payload.legs
            ],
        },
        reason="authorized MLEG candidate",
    )
    builder.set("mcp_attempt", mcp_attempt, reason="official MCP MLEG submit")
    builder.set("reconciliation", report_as_dict(report), reason="broker terminal MATCHED fill")
    builder.set("broker_receipt", receipt_as_dict(receipt), reason="broker receipt/readback for MATCHED fill")
    if fill["end_of_cycle_equity"] is not None:
        builder.set("end_of_cycle_equity", fill["end_of_cycle_equity"], reason="account equity after MATCHED fill")
    if fill["unrealized_pnl"] is not None:
        builder.set("unrealized_pnl", fill["unrealized_pnl"], reason="broker snapshot unrealized P&L")
    if fill["realized_pnl"] is not None:
        builder.set("realized_pnl", fill["realized_pnl"], reason="broker snapshot realized P&L")
    return fill


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
    broker: Any = None,
) -> dict[str, Any]:
    pending = report.status is ReconciliationStatus.PENDING and not report.halt_triggered
    pnl = None
    pnl_blocked = False
    cli_readback: dict[str, Any] = {"available": False, "reason": "official Alpaca CLI not installed"}
    cli = AlpacaCliReadOnly()
    if report.complete and cli.available():
        try:
            cli_readback = cli.reconcile_order(
                client_order_id=payload.client_order_id,
                broker_order_id=receipt.broker_order_id,
            )
        except AlpacaCliReadError as exc:
            # The CLI is an independent, read-only corroboration channel.  A
            # missing credential, network failure, or unreadable response is
            # recorded honestly as unavailable; only a successful CLI read
            # that explicitly contradicts the broker receipt is a mismatch.
            cli_readback = {"available": False, "matched": False, "reason": str(exc)}
    cli_mismatch = bool(cli_readback.get("available")) and not bool(cli_readback.get("matched"))
    if report.complete and not report.halt_triggered and not pending:
        pnl = _pnl_from_broker(broker)
        if pnl is None or not pnl.matched or pnl.end_of_cycle_equity is None:
            pnl_blocked = True
    reconciliation_blocked = report.halt_triggered or pnl_blocked
    if cli_mismatch:
        reconciliation_blocked = True
    if reconciliation_blocked:
        halt_reason = (
            "official Alpaca CLI readback mismatch"
            if cli_mismatch
            else (
                "broker P&L/equity unreadable"
                if pnl_blocked
                else ("; ".join(report.discrepancies) or report.status.value)
            )
        )
        store.halt(
            record.cycle_id,
            halt_reason,
            forbids_new=True,
        )
        ledger.trip(
            status="unknown" if pnl_blocked else report.status.value,
            reason=halt_reason,
            report_id=report.report_id,
        )
    elif pending:
        if record.state is CycleState.ACKNOWLEDGED:
            store.transition(record.cycle_id, CycleState.RECONCILING, reason="waiting for terminal broker state")
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
    builder = _CURRENT_EPISODE.get()
    if builder is not None:
        reconciliation_evidence = report_as_dict(report)
        reconciliation_evidence["cli_readback"] = cli_readback
        builder.set(
            "reconciliation",
            reconciliation_evidence,
            reason="broker result plus official Alpaca CLI read-only cross-check",
        )
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
    complete = report.complete and final.state is CycleState.COMPLETED and not pnl_blocked
    fill_pnl: dict[str, Any] = {}
    if complete:
        fill_pnl = _stamp_matched_episode(
            report=report,
            receipt=receipt,
            pnl=pnl,
            payload=payload,
            mcp_result=mcp_result,
            store=store,
            cycle_id=final.cycle_id,
        )
    evidence_row = None
    if not pending:
        extra = {
            "operational_complete": complete,
            "operational_verdict": report.status.value,
            "live_fill_claimed": False,
            "cli_readback": cli_readback,
        }
        extra.update(fill_pnl)
        if complete:
            ledger_outcome = "MATCHED"
            ledger_reason = "broker fill MATCHED"
        else:
            ledger_outcome = "HALT"
            ledger_reason = (
                final.halt_reason
                or "; ".join(report.discrepancies)
                or report.status.value
                or ""
            ) or "reconciliation halted"
        evidence_row = _commit_episode(
            outcome=ledger_outcome,
            reason=ledger_reason,
            cycle_id=final.cycle_id,
            client_order_id=final.client_order_id,
            extra=extra,
        )
    if pending:
        outcome = "PENDING"
        reason = "waiting for broker terminal state"
    elif complete:
        outcome = "MATCHED"
        reason = "broker fill MATCHED"
    else:
        outcome = ObservationOutcome.HALT.value
        reason = (
            final.halt_reason
            or "; ".join(report.discrepancies)
            or report.status.value
            or ""
        )
    return {
        "ok": complete,
        "complete": complete,
        "submitted": bool(receipt.submitted) or final.attempts > 0,
        "outcome": outcome,
        "reason": reason,
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
        "record_id": (evidence_row or {}).get("record_id", ""),
        "claim": (evidence_row or {}).get("claim", ""),
        "commit_sha": (evidence_row or {}).get("commit_sha", ""),
        "channel": (evidence_row or {}).get("channel", ""),
        "filled_qty": fill_pnl.get("filled_qty", report.filled_qty if complete else None),
        "filled_avg_price": fill_pnl.get("filled_avg_price"),
        "realized_pnl": fill_pnl.get("realized_pnl"),
        "unrealized_pnl": fill_pnl.get("unrealized_pnl"),
        "end_of_cycle_equity": fill_pnl.get("end_of_cycle_equity"),
        "cli_readback": cli_readback,
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
        broker=broker,
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
    provenance: str | None = None,
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
    builder = EpisodeBuilder(
        log.evidence,
        channel=_evidence_channel(dry_run=dry_run, provenance=provenance),
    )
    _CURRENT_EPISODE.set(builder)

    if not dry_run and ledger.is_halted():
        return _closed_cycle(
            outcome=ObservationOutcome.HALT,
            reason=ledger.reason(),
            dry_run=False,
            journal_entry=None,
            correlation_id="",
            extra={"halt_ledger": True},
        )

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
        builder.set("snapshot", snapshot_from_observation(observation), reason="live observation")
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
        exit_reader = _broker_reader(broker, observer)
        if exit_reader is None:
            closed = _close_open_cycle(
                store, cycle, outcome=ObservationOutcome.HALT, reason="broker readback unavailable"
            )
            return _closed_cycle(
                outcome=ObservationOutcome.HALT,
                reason="broker readback unavailable",
                dry_run=False,
                journal_entry=None,
                correlation_id=observation.correlation_id,
                cycle_id=closed.cycle_id if closed else "",
                client_order_id=closed.client_order_id if closed else "",
                state=closed.state.value if closed else "",
            )
        exit_result = manage_open_positions(
            settings=settings,
            positions=list(portfolio.positions),
            evidence=observation.evidence,
            broker=exit_reader,
            executor=mcp_executor or AlpacaMcpExecutor.from_env(dry_run=False),
            state_dir=log.path.with_name("exit_cycles"),
        )
        if exit_result.get("acted"):
            log.record("position_management", exit_result)
            builder.set("position_management", exit_result, reason="deterministic exit stage")
            halted = bool(exit_result.get("halt"))
            outcome = ObservationOutcome.HALT if halted else ObservationOutcome.NO_TRADE
            reason = str(exit_result.get("reason") or "position managed")
            closed = _close_open_cycle(store, cycle, outcome=outcome, reason=reason)
            if halted:
                ledger.trip(
                    status="unknown",
                    reason=reason,
                    report_id=str(exit_result.get("client_order_id") or cycle.cycle_id),
                )
            return _closed_cycle(
                outcome=outcome,
                reason=reason,
                dry_run=False,
                journal_entry=None,
                correlation_id=observation.correlation_id,
                cycle_id=closed.cycle_id if closed else "",
                client_order_id=str(exit_result.get("client_order_id") or ""),
                state=closed.state.value if closed else "",
                ledger_outcome="HALT" if halted else "NO_TRADE",
                extra={"position_management": exit_result},
            )
        if store is not None and cycle is not None:
            store.attach_snapshot(cycle.cycle_id, evidence_digest(observation.evidence))
        reader = observer if observer is not None else broker
        if reader is not None and hasattr(reader, "fetch_account"):
            snap = snapshot_from_client(reader, source=SOURCE_LIVE_BROKER)
        else:
            snap = snapshot_from_objects(
                account={
                    "equity": getattr(portfolio, "equity", None),
                    "cash": getattr(portfolio, "cash", None),
                    "id": getattr(portfolio, "account_id", None),
                },
                positions=list(getattr(portfolio, "positions", None) or []),
                fills=[],
                source=SOURCE_LIVE_BROKER,
            )
        pnl = pnl_from_snapshot(snap)
        if not pnl.matched:
            closed = _close_open_cycle(
                store,
                cycle,
                outcome=ObservationOutcome.HALT,
                reason="broker snapshot P&L identity mismatch",
            )
            return _closed_cycle(
                outcome=ObservationOutcome.HALT,
                reason="broker snapshot P&L identity mismatch",
                dry_run=False,
                journal_entry=None,
                correlation_id=observation.correlation_id,
                cycle_id=closed.cycle_id if closed else "",
                client_order_id=closed.client_order_id if closed else "",
                state=closed.state.value if closed else "",
            )
        builder.set(
            "end_of_cycle_equity",
            str(pnl.end_of_cycle_equity) if pnl.end_of_cycle_equity is not None else str(getattr(portfolio, "equity", "")),
            reason="account equity from broker snapshot; not a live fill P&L",
        )
        builder.set(
            "positions",
            list(getattr(portfolio, "positions", None) or []),
            reason="positions at observation; not a live P&L snapshot",
        )
        builder.missing("realized_pnl", "TODO: waiting for sanitized broker JSON; cloud VM must not submit")
        builder.missing("unrealized_pnl", "TODO: waiting for sanitized broker JSON; cloud VM must not submit")
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
        builder.set(
            "thesis",
            {
                "stance": thesis.stance.value,
                "reason_code": thesis.reason_code,
                "accepted": thesis.accepted,
                "confidence": str(thesis.confidence),
                "model_called": thesis.model_called,
                "detail": thesis.detail,
            },
            reason="thesis / NO_TRADE",
        )
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
            market = replay_pin_market()
        if stance is None:
            stance = ThesisStance.BULLISH
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

    try:
        sized_qty = apply_risk_budget_qty(plan.request, portfolio, settings)
    except ExecutionRejected as exc:
        closed = _close_open_cycle(
            store,
            cycle,
            outcome=ObservationOutcome.NO_TRADE,
            reason=str(exc),
        )
        return _closed_cycle(
            outcome=ObservationOutcome.NO_TRADE,
            reason=str(exc),
            dry_run=dry_run,
            journal_entry=None,
            correlation_id=(observation.correlation_id if not dry_run else ""),
            cycle_id=closed.cycle_id if closed else "",
            client_order_id=closed.client_order_id if closed else "",
            state=closed.state.value if closed else "",
            ledger_outcome="VETO",
        )

    log.record(
        "decision",
        {
            "strategy": plan.strategy,
            "underlying": plan.underlying,
            "notes": plan.notes,
            "backend": settings.execution_backend,
            "qty": sized_qty,
            "sizing": dict(plan.request.metadata.get("sizing") and plan.request.metadata or {}),
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
    builder.set(
        "candidate_set",
        {
            "strategy": plan.strategy,
            "underlying": plan.underlying,
            "payload_hash": payload.payload_hash,
            "legs": payload.to_canonical_dict()["legs"],
            "qty": payload.qty,
            "limit_price": str(payload.limit_price),
        },
        reason="candidate vertical",
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
    builder.set(
        "certificate",
        {
            "certificate_id": certificate.certificate_id,
            "payload_hash": certificate.payload_hash,
            "evidence_hash": certificate.evidence_hash,
            "binding_hash": certificate.binding_hash,
            "approval": certificate.approval,
            "veto": certificate.veto,
            "reasons": list(certificate.reasons),
        },
        reason="risk certificate",
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
            ledger_outcome="VETO",
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
    builder.set(
        "mcp_attempt",
        {
            "dry_run": True,
            "submitted": False,
            "tool": result.get("tool"),
            "arguments_hash": result.get("arguments_hash"),
        },
        reason="replay preview; not a live MLEG submit",
    )
    builder.missing("broker_receipt", "replay/dry-run is not a live broker receipt")
    builder.missing("reconciliation", "replay/dry-run is not a live fill")
    builder.missing("realized_pnl", "replay/dry-run is not a live P&L snapshot")
    builder.missing("unrealized_pnl", "replay/dry-run is not a live P&L snapshot")
    evidence_row = _commit_episode(
        outcome="NO_TRADE",
        reason="replay/dry-run does not place a live order",
        cycle_id=cycle.cycle_id if cycle is not None else "",
        client_order_id=client_order_id,
        extra={"dry_run": True, "live_fill_claimed": False},
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
        "record_id": (evidence_row or {}).get("record_id", ""),
        "claim": (evidence_row or {}).get("claim", ""),
        "commit_sha": (evidence_row or {}).get("commit_sha", ""),
        "channel": (evidence_row or {}).get("channel", ""),
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
