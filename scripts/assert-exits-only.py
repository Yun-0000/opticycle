#!/usr/bin/env python3
"""Credential-free proof that exits-only cannot reach the entry path."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from opticycle.cycle import CycleStore
from opticycle.journal import TradeJournal
from opticycle.observe import ObservationResult
from opticycle.open_session import skip_reason
from opticycle.position_manager import OpenVertical, _exit_reason, manage_open_positions
from opticycle.protocol import (
    CanonicalOrderPayload,
    EvidenceSnapshot,
    ObservationOutcome,
    OptionContractQuote,
    OptionLegSpec,
    OptionType,
    OrderSide,
    PositionIntent,
)
from opticycle.reconcile import HaltLedger
from opticycle.risk import PortfolioSnapshot, RiskEngine
from opticycle.runner import run_once
from opticycle.settings import HackathonSettings
from trade.orders import ExecutionRejected


class NoSubmitExecutor:
    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"exits-only reached executor method {name}")


class AmbiguousExitExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def place_authorized_exit_sync(self, *args: object, **kwargs: object) -> object:
        _ = args, kwargs
        self.calls += 1
        raise TimeoutError("simulated ambiguous transport response")


class ReconciledExitExecutor:
    def __init__(self) -> None:
        self.calls = 0
        self.payload: CanonicalOrderPayload | None = None

    def place_authorized_exit_sync(
        self,
        payload: CanonicalOrderPayload,
        authorization: object,
        *,
        position_snapshot_hash: str,
        settings: HackathonSettings,
        now: datetime,
    ) -> dict[str, object]:
        _ = authorization, position_snapshot_hash, settings, now
        self.calls += 1
        self.payload = payload
        return {
            "arguments_hash": "exit-arguments-hash",
            "raw_result_hash": "exit-raw-result-hash",
            "submitted": True,
            "dry_run": False,
            "raw": {"id": "exit-broker-order", "status": "filled"},
        }


class ReconciledExitBroker:
    def __init__(self, executor: ReconciledExitExecutor) -> None:
        self.executor = executor

    def fetch_account(self) -> object:
        return SimpleNamespace(account_number="PA3V84C40PJQ")

    def fetch_orders_by_client_id(self, client_order_id: str) -> list[dict[str, object]]:
        payload = self.executor.payload
        if payload is None or payload.client_order_id != client_order_id:
            return []
        return [
            {
                "id": "exit-broker-order",
                "client_order_id": payload.client_order_id,
                "order_class": payload.order_class,
                "qty": str(payload.qty),
                "limit_price": str(payload.limit_price),
                "status": "filled",
                "filled_qty": str(payload.qty),
                "filled_avg_price": str(payload.limit_price),
                "legs": [
                    {
                        "symbol": leg.symbol,
                        "ratio_qty": str(leg.ratio_qty),
                        "side": leg.side.value,
                        "position_intent": leg.position_intent.value,
                    }
                    for leg in payload.legs
                ],
            }
        ]


def _fail_entry(*args: object, **kwargs: object) -> object:
    _ = args, kwargs
    raise AssertionError("exits-only reached the new-entry path")


def _assert_mode_prerequisites() -> dict[str, object]:
    with patch.dict(
        os.environ,
        {
            "ALPACA_API_KEY": "paper-key-placeholder",
            "ALPACA_SECRET_KEY": "paper-secret-placeholder",
            "OPENAI_API_KEY": "model-key-placeholder",
            "ALPACA_LIVE_TRADE": "false",
        },
        clear=True,
    ):
        reasons = {
            "observe_only": skip_reason(submit=False),
            "exits_only": skip_reason(submit=False, exits_only=True),
            "full_lifecycle": skip_reason(submit=True),
        }
    if any(reason is not None for reason in reasons.values()):
        raise AssertionError(f"valid mode prerequisites unexpectedly blocked: {reasons}")
    return {"valid_modes": sorted(reasons)}


def _observation(now: datetime) -> ObservationResult:
    evidence = EvidenceSnapshot(
        underlying="SPY",
        spot_price=Decimal("650"),
        timestamp=now,
        bars_count=60,
        quote_age_seconds=Decimal("1"),
        is_fresh=True,
        correlation_id="exits-only-proof",
        account_id="PA3V84C40PJQ",
    )
    portfolio = PortfolioSnapshot(
        equity=100_000,
        buying_power=100_000,
        cash=100_000,
        account_id="PA3V84C40PJQ",
        paper=True,
        options_approved=True,
        positions=[],
    )
    return ObservationResult(
        outcome=ObservationOutcome.OK,
        reason="ok",
        correlation_id=evidence.correlation_id,
        datums=(),
        evidence=evidence,
        portfolio=portfolio,
    )


def _assert_no_entry() -> dict[str, object]:
    now = datetime.now(timezone.utc)
    observation = _observation(now)
    with TemporaryDirectory(prefix="opticycle-exits-only-") as tmp:
        root = Path(tmp)
        store = CycleStore(root / "cycles.sqlite")
        try:
            with (
                patch("opticycle.runner.observe_live", return_value=observation),
                patch(
                    "opticycle.runner.manage_open_positions",
                    return_value={"acted": False, "halt": False, "reason": "no exit trigger"},
                ),
                patch("opticycle.runner.require_live_llm", side_effect=_fail_entry),
                patch("opticycle.runner.build_cycle_plan", side_effect=_fail_entry),
            ):
                result = run_once(
                    HackathonSettings(),
                    dry_run=False,
                    observer=object(),
                    broker=object(),
                    mcp_executor=NoSubmitExecutor(),
                    journal=TradeJournal(root / "journal.jsonl"),
                    halt_ledger=HaltLedger(root / "halt.json"),
                    cycle_store=store,
                    provenance="live_paper",
                    allow_new_entries=False,
                )
        finally:
            store.close()
    if result.get("outcome") != ObservationOutcome.NO_TRADE.value:
        raise AssertionError("exits-only no-trigger outcome must be NO_TRADE")
    if result.get("reason") != "no_exit_triggered":
        raise AssertionError("exits-only no-trigger reason must be stable")
    if result.get("submitted") is not False:
        raise AssertionError("exits-only no-trigger run must submit zero orders")
    return {
        "entry_path_reached": False,
        "outcome": result["outcome"],
        "reason": result["reason"],
        "submitted": result["submitted"],
    }


def _assert_single_exit_stops_entry() -> dict[str, object]:
    now = datetime.now(timezone.utc)
    observation = _observation(now)
    position_result = {
        "acted": True,
        "halt": False,
        "reason": "TAKE_PROFIT_50_PERCENT",
        "client_order_id": "oc-exit-proof",
        "mcp_submit_count": 1,
        "second_submit": False,
        "reconciliation": {"status": "matched"},
    }
    with TemporaryDirectory(prefix="opticycle-single-exit-") as tmp:
        root = Path(tmp)
        store = CycleStore(root / "cycles.sqlite")
        try:
            with (
                patch("opticycle.runner.observe_live", return_value=observation),
                patch("opticycle.runner.manage_open_positions", return_value=position_result),
                patch("opticycle.runner.require_live_llm", side_effect=_fail_entry),
                patch("opticycle.runner.build_cycle_plan", side_effect=_fail_entry),
            ):
                result = run_once(
                    HackathonSettings(),
                    dry_run=False,
                    observer=object(),
                    broker=object(),
                    mcp_executor=NoSubmitExecutor(),
                    journal=TradeJournal(root / "journal.jsonl"),
                    halt_ledger=HaltLedger(root / "halt.json"),
                    cycle_store=store,
                    provenance="live_paper",
                    allow_new_entries=False,
                )
        finally:
            store.close()
    if result.get("submitted") is not True:
        raise AssertionError("one matched exit must report exactly one submit")
    if result.get("position_management") != position_result:
        raise AssertionError("exit reconciliation must remain attached to the result")
    return {
        "entry_path_reached": False,
        "mcp_submit_count": 1,
        "second_submit": False,
        "submitted": result["submitted"],
    }


def _assert_exit_triggers() -> dict[str, str]:
    now = datetime.now(timezone.utc)
    today_et = now.astimezone(ZoneInfo("America/New_York")).date()
    settings = HackathonSettings(event_flatten_at="2099-01-01T00:00:00-05:00")

    def vertical(*, dte: int, credit: str = "2.00") -> OpenVertical:
        return OpenVertical(
            short_symbol="SPY991231P00650000",
            long_symbol="SPY991231P00645000",
            qty=1,
            expiration=today_et + timedelta(days=dte),
            width=Decimal("5"),
            entry_credit=Decimal(credit),
        )

    reasons = {
        "take_profit": _exit_reason(vertical(dte=5), Decimal("0.90"), settings, now),
        "stop_loss": _exit_reason(vertical(dte=5), Decimal("4.00"), settings, now),
        "dte_force_close": _exit_reason(vertical(dte=1), Decimal("1.50"), settings, now),
        "no_trigger": _exit_reason(vertical(dte=5), Decimal("1.50"), settings, now),
    }
    expected = {
        "take_profit": "TAKE_PROFIT_50_PERCENT",
        "stop_loss": "STOP_LOSS_2X_CREDIT",
        "dte_force_close": "DTE_FORCE_CLOSE",
        "no_trigger": None,
    }
    if reasons != expected:
        raise AssertionError(f"deterministic exit triggers changed: {reasons}")
    return {key: value or "none" for key, value in reasons.items()}


def _reconciled_exit_fixture(
    *,
    now: datetime,
    dte: int,
    short_bid: str,
    short_ask: str,
    long_bid: str,
    long_ask: str,
) -> tuple[list[dict[str, str]], EvidenceSnapshot]:
    expiration = now.astimezone(ZoneInfo("America/New_York")).date() + timedelta(days=dte)
    occ_date = expiration.strftime("%y%m%d")
    short_symbol = f"SPY{occ_date}P00650000"
    long_symbol = f"SPY{occ_date}P00645000"
    positions = [
        {"symbol": short_symbol, "qty": "-1", "side": "short", "avg_entry_price": "4.00"},
        {"symbol": long_symbol, "qty": "1", "side": "long", "avg_entry_price": "2.00"},
    ]
    evidence = EvidenceSnapshot(
        underlying="SPY",
        spot_price=Decimal("650"),
        timestamp=now,
        bars_count=60,
        quote_age_seconds=Decimal("1"),
        is_fresh=True,
        chain_quotes=(
            OptionContractQuote(
                symbol=short_symbol,
                underlying="SPY",
                option_type=OptionType.PUT,
                strike_price=Decimal("650"),
                expiration=datetime.combine(expiration, datetime.min.time(), tzinfo=timezone.utc),
                bid=Decimal(short_bid),
                ask=Decimal(short_ask),
                last=(Decimal(short_bid) + Decimal(short_ask)) / Decimal("2"),
                delta=Decimal("-0.25"),
                gamma=Decimal("0.01"),
                theta=Decimal("-0.10"),
                vega=Decimal("0.10"),
                quote_timestamp=now,
            ),
            OptionContractQuote(
                symbol=long_symbol,
                underlying="SPY",
                option_type=OptionType.PUT,
                strike_price=Decimal("645"),
                expiration=datetime.combine(expiration, datetime.min.time(), tzinfo=timezone.utc),
                bid=Decimal(long_bid),
                ask=Decimal(long_ask),
                last=(Decimal(long_bid) + Decimal(long_ask)) / Decimal("2"),
                delta=Decimal("-0.15"),
                gamma=Decimal("0.01"),
                theta=Decimal("-0.08"),
                vega=Decimal("0.08"),
                quote_timestamp=now,
            ),
        ),
        correlation_id="reconciled-exit-proof",
        account_id="PA3V84C40PJQ",
        quote_timestamp=now,
    )
    return positions, evidence


def _assert_reconciled_exit_paths() -> dict[str, dict[str, object]]:
    now = datetime(2026, 9, 3, 15, 0, tzinfo=timezone.utc)
    settings = HackathonSettings(event_flatten_at="2099-01-01T00:00:00-05:00")
    cases = {
        "take_profit": {
            "dte": 5,
            "short_bid": "1.00",
            "short_ask": "1.10",
            "long_bid": "0.30",
            "long_ask": "0.40",
            "reason": "TAKE_PROFIT_50_PERCENT",
        },
        "stop_loss": {
            "dte": 5,
            "short_bid": "5.00",
            "short_ask": "5.20",
            "long_bid": "0.90",
            "long_ask": "1.00",
            "reason": "STOP_LOSS_2X_CREDIT",
        },
        "dte_force_close": {
            "dte": 1,
            "short_bid": "1.40",
            "short_ask": "1.50",
            "long_bid": "0.30",
            "long_ask": "0.40",
            "reason": "DTE_FORCE_CLOSE",
        },
    }
    reports: dict[str, dict[str, object]] = {}
    for name, case in cases.items():
        positions, evidence = _reconciled_exit_fixture(
            now=now,
            dte=int(case["dte"]),
            short_bid=str(case["short_bid"]),
            short_ask=str(case["short_ask"]),
            long_bid=str(case["long_bid"]),
            long_ask=str(case["long_ask"]),
        )
        executor = ReconciledExitExecutor()
        broker = ReconciledExitBroker(executor)
        with TemporaryDirectory(prefix=f"opticycle-{name}-") as tmp:
            result = manage_open_positions(
                settings=settings,
                positions=positions,
                evidence=evidence,
                broker=broker,
                executor=executor,
                state_dir=Path(tmp),
                now=now,
            )
        payload = executor.payload
        reconciliation = result.get("reconciliation") or {}
        intents = sorted(leg.position_intent.value for leg in (payload.legs if payload else ()))
        if result.get("reason") != case["reason"]:
            raise AssertionError(f"{name} selected the wrong deterministic exit reason")
        if executor.calls != 1 or result.get("mcp_submit_count") != 1:
            raise AssertionError(f"{name} must submit exactly one close MLEG")
        if result.get("second_submit") is not False or result.get("halt"):
            raise AssertionError(f"{name} must reconcile without a second submit")
        if reconciliation.get("status") != "matched" or not reconciliation.get("complete"):
            raise AssertionError(f"{name} close MLEG did not reconcile as MATCHED")
        if intents != ["buy_to_close", "sell_to_close"]:
            raise AssertionError(f"{name} did not preserve two-leg close intents")
        reports[name] = {
            "complete": True,
            "mcp_submit_count": 1,
            "reason": result["reason"],
            "reconciliation": reconciliation["status"],
            "second_submit": False,
        }
    return reports


def _assert_ambiguous_exit_halts() -> dict[str, object]:
    now = datetime.now(timezone.utc)
    expiration = now + timedelta(days=5)
    occ_date = expiration.strftime("%y%m%d")
    short_symbol = f"SPY{occ_date}P00650000"
    long_symbol = f"SPY{occ_date}P00645000"
    evidence = replace(
        _observation(now).evidence,
        chain_quotes=(
            OptionContractQuote(
                symbol=short_symbol,
                underlying="SPY",
                option_type=OptionType.PUT,
                strike_price=Decimal("650"),
                expiration=expiration,
                bid=Decimal("1.00"),
                ask=Decimal("1.10"),
                last=Decimal("1.05"),
                delta=Decimal("-0.25"),
                gamma=Decimal("0.01"),
                theta=Decimal("-0.10"),
                vega=Decimal("0.10"),
                quote_timestamp=now,
            ),
            OptionContractQuote(
                symbol=long_symbol,
                underlying="SPY",
                option_type=OptionType.PUT,
                strike_price=Decimal("645"),
                expiration=expiration,
                bid=Decimal("0.30"),
                ask=Decimal("0.40"),
                last=Decimal("0.35"),
                delta=Decimal("-0.15"),
                gamma=Decimal("0.01"),
                theta=Decimal("-0.08"),
                vega=Decimal("0.08"),
                quote_timestamp=now,
            ),
        ),
    )
    positions = [
        {"symbol": short_symbol, "qty": "-1", "side": "short", "avg_entry_price": "4.00"},
        {"symbol": long_symbol, "qty": "1", "side": "long", "avg_entry_price": "2.00"},
    ]
    executor = AmbiguousExitExecutor()
    with TemporaryDirectory(prefix="opticycle-ambiguous-exit-") as tmp:
        state_dir = Path(tmp)
        result = manage_open_positions(
            settings=HackathonSettings(),
            positions=positions,
            evidence=evidence,
            broker=object(),
            executor=executor,
            state_dir=state_dir,
            now=now,
        )
        states = [json.loads(path.read_text(encoding="utf-8")) for path in state_dir.glob("*.json")]
    if executor.calls != 1 or result.get("mcp_submit_count") != 1:
        raise AssertionError("ambiguous exit must make exactly one MCP submit attempt")
    if not result.get("halt") or result.get("second_submit") is not False:
        raise AssertionError("ambiguous exit must HALT without resubmitting")
    if len(states) != 1 or states[0].get("state") != "HALTED":
        raise AssertionError("ambiguous exit state must be durably HALTED")
    return {
        "halt": True,
        "mcp_submit_count": 1,
        "same_client_order_id": result.get("client_order_id") == states[0].get("payload", {}).get("client_order_id"),
        "second_submit": False,
    }


def _assert_payload_mutations_rejected() -> list[str]:
    now = datetime.now(timezone.utc)
    expiration = now + timedelta(days=5)
    occ_date = expiration.strftime("%y%m%d")
    short = OptionLegSpec(
        symbol=f"SPY{occ_date}P00650000",
        ratio_qty=1,
        side=OrderSide.SELL,
        position_intent=PositionIntent.SELL_TO_OPEN,
        option_type=OptionType.PUT,
        strike_price=Decimal("650"),
        expiration=expiration,
    )
    long = OptionLegSpec(
        symbol=f"SPY{occ_date}P00645000",
        ratio_qty=1,
        side=OrderSide.BUY,
        position_intent=PositionIntent.BUY_TO_OPEN,
        option_type=OptionType.PUT,
        strike_price=Decimal("645"),
        expiration=expiration,
    )
    payload = CanonicalOrderPayload(
        client_order_id="oc-mutation-proof",
        account_id="PA3V84C40PJQ",
        underlying="SPY",
        order_class="mleg",
        order_type="limit",
        time_in_force="day",
        qty=1,
        limit_price=Decimal("-2.00"),
        legs=(short, long),
    )
    evidence = EvidenceSnapshot(
        underlying="SPY",
        spot_price=Decimal("660"),
        timestamp=now,
        bars_count=60,
        quote_age_seconds=Decimal("1"),
        is_fresh=True,
        chain_quotes=(
            OptionContractQuote(
                symbol=short.symbol,
                underlying="SPY",
                option_type=OptionType.PUT,
                strike_price=short.strike_price,
                expiration=expiration,
                bid=Decimal("6.60"),
                ask=Decimal("6.80"),
                last=Decimal("6.70"),
                delta=Decimal("-0.25"),
                gamma=Decimal("0.01"),
                theta=Decimal("-0.10"),
                vega=Decimal("0.10"),
                quote_timestamp=now,
            ),
            OptionContractQuote(
                symbol=long.symbol,
                underlying="SPY",
                option_type=OptionType.PUT,
                strike_price=long.strike_price,
                expiration=expiration,
                bid=Decimal("4.30"),
                ask=Decimal("4.50"),
                last=Decimal("4.40"),
                delta=Decimal("-0.15"),
                gamma=Decimal("0.01"),
                theta=Decimal("-0.08"),
                vega=Decimal("0.08"),
                quote_timestamp=now,
            ),
        ),
        correlation_id="payload-mutation-proof",
        account_id="PA3V84C40PJQ",
        quote_timestamp=now,
    )
    portfolio = PortfolioSnapshot(
        equity=100_000,
        buying_power=100_000,
        cash=100_000,
        account_id="PA3V84C40PJQ",
        paper=True,
        options_approved=True,
        net_delta=0,
        net_vega=0,
        net_gamma=0,
        net_theta=0,
    )
    engine = RiskEngine(HackathonSettings())
    certificate = engine.issue(payload, portfolio, evidence, now=now)
    if not certificate.approval:
        raise AssertionError(f"mutation proof fixture was vetoed: {certificate.reasons}")

    mutations = {
        "qty": replace(payload, qty=2),
        "limit": replace(payload, limit_price=Decimal("-1.99")),
        "leg": replace(payload, legs=(replace(short, ratio_qty=2), long)),
    }
    rejected: list[str] = []
    for field, mutated in mutations.items():
        try:
            engine.verify(certificate, mutated, portfolio, evidence, now=now)
        except ExecutionRejected as exc:
            if "payload changed after certificate issue" not in str(exc):
                raise
            rejected.append(field)
        else:
            raise AssertionError(f"certificate accepted mutated {field}")
    return rejected


def main() -> int:
    result = {
        "credential_free": True,
        "ambiguous_exit": _assert_ambiguous_exit_halts(),
        "exit_triggers": _assert_exit_triggers(),
        "exits_only": _assert_no_entry(),
        "mode_contract": _assert_mode_prerequisites(),
        "reconciled_exit_paths": _assert_reconciled_exit_paths(),
        "single_exit": _assert_single_exit_stops_entry(),
        "payload_mutations_rejected": _assert_payload_mutations_rejected(),
    }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
