"""Deterministic lifecycle management for open SPY credit verticals."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from opticycle.cycle import payload_from_dict
from opticycle.protocol import (
    BrokerReceipt,
    CanonicalOrderPayload,
    EvidenceSnapshot,
    PositionIntent,
    ReconciliationStatus,
    canonical_hash,
    ensure_utc,
    parse_occ_symbol,
)
from opticycle.reconcile import receipt_from_mcp, reconcile, report_as_dict
from opticycle.risk import payload_from_request, quotes_by_symbol
from opticycle.settings import HackathonSettings
from trade.mcp.alpaca_mcp_executor import AlpacaMcpExecutor
from trade.orders import ExecutionRejected, OptionOrderRequest

ET = ZoneInfo("America/New_York")
DEFAULT_STATE_DIR = Path("data/exit_cycles")
EXIT_TTL_SECONDS = 60


def _get(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        parsed = Decimal(str(value))
    except Exception:
        return None
    return None if parsed.is_nan() else parsed


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _signed_qty(position: Any) -> Decimal:
    qty = _dec(_get(position, "qty")) or Decimal("0")
    side = str(getattr(_get(position, "side"), "value", _get(position, "side", "")) or "").lower()
    if "short" in side:
        return -abs(qty)
    if "long" in side:
        return abs(qty)
    return qty


@dataclass(frozen=True, slots=True)
class OpenVertical:
    short_symbol: str
    long_symbol: str
    qty: int
    expiration: date
    width: Decimal
    entry_credit: Decimal | None
    short_avg_entry: Decimal | None = None
    long_avg_entry: Decimal | None = None

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "entry_credit": "" if self.entry_credit is None else str(_money(self.entry_credit)),
            "expiration": self.expiration.isoformat(),
            "long_avg_entry": "" if self.long_avg_entry is None else str(_money(self.long_avg_entry)),
            "long_symbol": self.long_symbol,
            "qty": self.qty,
            "short_avg_entry": "" if self.short_avg_entry is None else str(_money(self.short_avg_entry)),
            "short_symbol": self.short_symbol,
            "width": str(_money(self.width)),
        }


def pair_open_verticals(positions: list[Any]) -> list[OpenVertical]:
    """Pair long/short OCC legs without assuming broker list order."""
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for item in positions:
        symbol = str(_get(item, "symbol", "") or "").upper()
        try:
            root, expiration, option_type, strike = parse_occ_symbol(symbol)
        except ValueError:
            continue
        signed = _signed_qty(item)
        if signed == 0:
            continue
        key = (root, expiration.date().isoformat(), option_type.value)
        grouped.setdefault(key, []).append(
            {
                "symbol": symbol,
                "expiration": expiration.date(),
                "strike": strike,
                "signed_qty": signed,
                "remaining": abs(signed),
                "avg_entry": _dec(_get(item, "avg_entry_price")),
            }
        )

    pairs: list[OpenVertical] = []
    for (_root, _expiry, kind), legs in sorted(grouped.items()):
        shorts = [row for row in legs if row["signed_qty"] < 0]
        longs = [row for row in legs if row["signed_qty"] > 0]
        for short in sorted(shorts, key=lambda row: row["strike"]):
            compatible = [
                long
                for long in longs
                if long["remaining"] > 0
                and (
                    (kind == "put" and long["strike"] < short["strike"])
                    or (kind == "call" and long["strike"] > short["strike"])
                )
            ]
            if not compatible:
                continue
            long = min(compatible, key=lambda row: abs(row["strike"] - short["strike"]))
            qty = int(min(short["remaining"], long["remaining"]))
            if qty <= 0:
                continue
            short["remaining"] -= qty
            long["remaining"] -= qty
            short_avg = short["avg_entry"]
            long_avg = long["avg_entry"]
            entry_credit = None
            if short_avg is not None and long_avg is not None:
                possible = short_avg - long_avg
                if possible > 0:
                    entry_credit = possible
            pairs.append(
                OpenVertical(
                    short_symbol=short["symbol"],
                    long_symbol=long["symbol"],
                    qty=qty,
                    expiration=short["expiration"],
                    width=abs(short["strike"] - long["strike"]),
                    entry_credit=entry_credit,
                    short_avg_entry=short_avg,
                    long_avg_entry=long_avg,
                )
            )
    return pairs


def open_contracts_and_risk(positions: list[Any]) -> tuple[int, Decimal]:
    pairs = pair_open_verticals(positions)
    contracts = sum(item.qty for item in pairs)
    risk = Decimal("0")
    for item in pairs:
        credit = item.entry_credit or Decimal("0")
        risk += max(item.width - credit, Decimal("0")) * Decimal("100") * item.qty
    return contracts, _money(risk)


def _current_debit(vertical: OpenVertical, evidence: EvidenceSnapshot) -> tuple[Decimal | None, Decimal | None]:
    quotes = quotes_by_symbol(evidence)
    short = quotes.get(vertical.short_symbol)
    long = quotes.get(vertical.long_symbol)
    if short is None or long is None or short.bid <= 0 or short.ask <= 0 or long.bid <= 0 or long.ask <= 0:
        return None, None
    mark = max(((short.bid + short.ask) - (long.bid + long.ask)) / Decimal("2"), Decimal("0.01"))
    executable = max(short.ask - long.bid, Decimal("0.01"))
    return _money(mark), _money(min(executable + Decimal("0.20"), vertical.width))


def _exit_reason(
    vertical: OpenVertical,
    current_debit: Decimal | None,
    settings: HackathonSettings,
    now: datetime,
) -> str | None:
    today_et = ensure_utc(now).astimezone(ET).date()
    dte = (vertical.expiration - today_et).days
    flatten_at = datetime.fromisoformat(settings.event_flatten_at)
    if flatten_at.tzinfo is None:
        flatten_at = flatten_at.replace(tzinfo=ET)
    if ensure_utc(now) >= ensure_utc(flatten_at) and dte <= settings.event_flatten_dte:
        return "EVENT_RISK_FLATTEN"
    if dte <= settings.force_close_dte:
        return "DTE_FORCE_CLOSE"
    if current_debit is None or vertical.entry_credit is None or vertical.entry_credit <= 0:
        return None
    if current_debit >= vertical.entry_credit * Decimal(str(settings.stop_loss_multiple)):
        return "STOP_LOSS_2X_CREDIT"
    target_debit = vertical.entry_credit * (Decimal("1") - Decimal(str(settings.take_profit_fraction)))
    if current_debit <= target_debit:
        return "TAKE_PROFIT_50_PERCENT"
    return None


@dataclass(frozen=True, slots=True)
class ExitAuthorization:
    authorization_id: str
    payload_hash: str
    position_snapshot_hash: str
    client_order_id: str
    account_id: str
    reason: str
    issued_at: datetime
    expires_at: datetime
    binding_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "issued_at", ensure_utc(self.issued_at))
        object.__setattr__(self, "expires_at", ensure_utc(self.expires_at))
        object.__setattr__(self, "binding_hash", canonical_hash(self._binding_dict()))

    def _binding_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "authorization_id": self.authorization_id,
            "client_order_id": self.client_order_id,
            "expires_at": self.expires_at.isoformat(),
            "issued_at": self.issued_at.isoformat(),
            "payload_hash": self.payload_hash,
            "position_snapshot_hash": self.position_snapshot_hash,
            "reason": self.reason,
        }

    def verify(
        self,
        payload: CanonicalOrderPayload,
        *,
        position_snapshot_hash: str,
        settings: HackathonSettings,
        now: datetime | None = None,
    ) -> None:
        clock = ensure_utc(now or datetime.now(timezone.utc))
        if canonical_hash(self._binding_dict()) != self.binding_hash:
            raise ExecutionRejected("unauthorized: exit authorization mutated")
        if clock >= self.expires_at:
            raise ExecutionRejected("exit authorization expired")
        if payload.payload_hash != self.payload_hash:
            raise ExecutionRejected("exit payload changed after authorization")
        if position_snapshot_hash != self.position_snapshot_hash:
            raise ExecutionRejected("position snapshot changed after exit authorization")
        if payload.client_order_id != self.client_order_id:
            raise ExecutionRejected("exit client_order_id mismatch")
        designated = settings.paper_account_id or self.account_id
        if payload.account_id != designated or self.account_id != designated:
            raise ExecutionRejected("exit account mismatch")
        if self.reason not in {
            "TAKE_PROFIT_50_PERCENT",
            "STOP_LOSS_2X_CREDIT",
            "DTE_FORCE_CLOSE",
            "EVENT_RISK_FLATTEN",
        }:
            raise ExecutionRejected("exit reason is not deterministic")


def _write_state(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _recover_pending(
    *,
    state_dir: Path,
    broker: Any,
    settings: HackathonSettings,
) -> dict[str, Any] | None:
    if not state_dir.is_dir():
        return None
    for path in sorted(state_dir.glob("*.json")):
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {"acted": True, "halt": True, "reason": "exit state unreadable"}
        if state.get("state") not in {"SUBMITTING", "PENDING", "ACKNOWLEDGED"}:
            continue
        payload = payload_from_dict(dict(state["payload"]))
        receipt = BrokerReceipt(
            receipt_id=uuid.uuid4().hex,
            cycle_id=str(state.get("authorization_id") or payload.client_order_id),
            client_order_id=payload.client_order_id,
            broker_order_id=str(state.get("broker_order_id") or "") or None,
            received_at=datetime.now(timezone.utc),
            raw_status="recovered",
            is_success=True,
            submitted=True,
            response_payload={"recovered": True},
        )
        report = reconcile(
            payload=payload,
            receipt=receipt,
            broker=broker,
            settings=settings,
            cycle_id=receipt.cycle_id,
        )
        state["state"] = report.status.value.upper()
        state["reconciliation"] = report_as_dict(report)
        _write_state(path, state)
        return {
            "acted": True,
            "halt": report.halt_triggered,
            "reason": "recovered exit without resubmit",
            "client_order_id": payload.client_order_id,
            "reconciliation": report_as_dict(report),
            "second_submit": False,
        }
    return None


def manage_open_positions(
    *,
    settings: HackathonSettings,
    positions: list[Any],
    evidence: EvidenceSnapshot,
    broker: Any,
    executor: AlpacaMcpExecutor,
    state_dir: Path = DEFAULT_STATE_DIR,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Manage one triggered vertical per cycle, then require broker readback."""
    clock = ensure_utc(now or datetime.now(timezone.utc))
    recovered = _recover_pending(state_dir=state_dir, broker=broker, settings=settings)
    if recovered is not None:
        return recovered

    for vertical in pair_open_verticals(positions):
        current_debit, limit = _current_debit(vertical, evidence)
        reason = _exit_reason(vertical, current_debit, settings, clock)
        if reason is None:
            continue
        if current_debit is None or limit is None:
            return {
                "acted": True,
                "halt": True,
                "reason": f"{reason}: fresh close quotes missing",
                "second_submit": False,
            }
        client_order_id = f"oc-exit-{uuid.uuid4().hex[:16]}"
        request = OptionOrderRequest(
            qty=vertical.qty,
            order_type="limit",
            time_in_force="day",
            limit_price=float(limit),
            client_order_id=client_order_id,
            order_class="mleg",
            legs=[
                {
                    "symbol": vertical.short_symbol,
                    "ratio_qty": "1",
                    "side": "buy",
                    "position_intent": PositionIntent.BUY_TO_CLOSE.value,
                },
                {
                    "symbol": vertical.long_symbol,
                    "ratio_qty": "1",
                    "side": "sell",
                    "position_intent": PositionIntent.SELL_TO_CLOSE.value,
                },
            ],
            reason=reason,
        )
        account_id = settings.paper_account_id or str(evidence.account_id or "")
        payload = payload_from_request(
            request,
            account_id=account_id,
            client_order_id=client_order_id,
            underlying=evidence.underlying,
        )
        position_snapshot = {
            "current_debit": str(current_debit),
            "limit": str(limit),
            "reason": reason,
            "vertical": vertical.canonical_dict(),
        }
        position_hash = canonical_hash(position_snapshot)
        authorization = ExitAuthorization(
            authorization_id=uuid.uuid4().hex,
            payload_hash=payload.payload_hash,
            position_snapshot_hash=position_hash,
            client_order_id=client_order_id,
            account_id=account_id,
            reason=reason,
            issued_at=clock,
            expires_at=clock + timedelta(seconds=EXIT_TTL_SECONDS),
        )
        state_path = state_dir / f"{client_order_id}.json"
        state: dict[str, Any] = {
            "schema": "opticycle.exit-cycle.v1",
            "state": "SUBMITTING",
            "authorization_id": authorization.authorization_id,
            "authorization_binding_hash": authorization.binding_hash,
            "payload": payload.to_canonical_dict(),
            "payload_hash": payload.payload_hash,
            "position_snapshot_hash": position_hash,
            "position_snapshot": position_snapshot,
            "mcp_submit_count": 0,
            "second_submit": False,
        }
        _write_state(state_path, state)
        try:
            result = executor.place_authorized_exit_sync(
                payload,
                authorization,
                position_snapshot_hash=position_hash,
                settings=settings,
                now=clock,
            )
        except Exception as exc:
            state.update({"state": "HALTED", "error": type(exc).__name__})
            _write_state(state_path, state)
            return {
                "acted": True,
                "halt": True,
                "reason": f"exit MCP failed: {type(exc).__name__}",
                "client_order_id": client_order_id,
                "second_submit": False,
            }
        state["mcp_submit_count"] = 1
        state["arguments_hash"] = result.get("arguments_hash")
        state["raw_result_hash"] = result.get("raw_result_hash")
        receipt = receipt_from_mcp(
            cycle_id=authorization.authorization_id,
            payload=payload,
            mcp_result=result,
            now=clock,
        )
        state["broker_order_id"] = receipt.broker_order_id
        report = reconcile(
            payload=payload,
            receipt=receipt,
            broker=broker,
            settings=settings,
            now=clock,
            cycle_id=authorization.authorization_id,
        )
        state["state"] = report.status.value.upper()
        state["reconciliation"] = report_as_dict(report)
        _write_state(state_path, state)
        return {
            "acted": True,
            "halt": report.halt_triggered,
            "reason": reason,
            "client_order_id": client_order_id,
            "payload_hash": payload.payload_hash,
            "authorization_binding_hash": authorization.binding_hash,
            "mcp_submit_count": 1,
            "second_submit": False,
            "reconciliation": report_as_dict(report),
        }
    return {"acted": False, "halt": False, "reason": "no exit trigger"}
