"""Broker reconciliation: only MATCHED completes a cycle.

`submitted=True` means MCP returned a non-error payload. It is not a fill
and not completion. Unknown or mismatched broker state HALTs new trades.
Partial fills use a predefined deterministic containment plan. No model,
no channel switch, no resubmit, no CLI.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from opticycle.protocol import (
    BrokerReceipt,
    CanonicalOrderPayload,
    FieldComparison,
    ReconciliationReport,
    ReconciliationStatus,
    ensure_utc,
    format_decimal,
)
from opticycle.settings import HackathonSettings

PARTIAL_FILL_CONTAINMENT = (
    "do_not_resubmit",
    "do_not_complete",
    "do_not_switch_channel",
    "halt_new_trades",
    "leave_working_remainder",
)

_FILLED_STATUSES = frozenset({"filled", "fill", "done_for_day"})
_PARTIAL_STATUSES = frozenset({"partially_filled", "partial_fill", "partial"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return format_decimal(value, 4).rstrip("0").rstrip(".") or "0"
    name = getattr(value, "value", None)
    if name is not None and not callable(name):
        return str(name).strip()
    return str(value).strip()


def _lower(value: Any) -> str:
    return _text(value).lower()


def _decimal(value: Any) -> Decimal | None:
    text = _text(value)
    if not text:
        return None
    try:
        number = Decimal(text)
    except Exception:
        return None
    if number.is_nan():
        return None
    return number


def _attr(obj: Any, *names: str, default: Any = None) -> Any:
    if obj is None:
        return default
    for name in names:
        if isinstance(obj, dict) and name in obj and obj[name] is not None:
            return obj[name]
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value is not None:
                return value
    return default


def _compare(field: str, expected: Any, observed: Any) -> FieldComparison:
    exp = _text(expected)
    obs = _text(observed)
    if field in {"limit", "filled_avg_price", "qty", "filled_qty", "ratio"}:
        exp_num = _decimal(expected)
        obs_num = _decimal(observed)
        matched = exp_num is not None and obs_num is not None and exp_num == obs_num
        if exp_num is not None:
            exp = format_decimal(exp_num, 4)
        if obs_num is not None:
            obs = format_decimal(obs_num, 4)
    else:
        matched = exp.lower() == obs.lower() if exp and obs else exp == obs
    return FieldComparison(field=field, expected=exp, observed=obs, matched=matched)


class HaltLedger:
    """Persistent HALT so mismatch/unknown stop later live cycles."""

    def __init__(self, path: Path | str = Path("data/halt.json")) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def snapshot(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"halted": False}
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"halted": True, "reason": "halt ledger unreadable", "status": "unknown"}
        if not isinstance(loaded, dict):
            return {"halted": True, "reason": "halt ledger unreadable", "status": "unknown"}
        return loaded

    def is_halted(self) -> bool:
        return bool(self.snapshot().get("halted"))

    def reason(self) -> str:
        return str(self.snapshot().get("reason") or "halted")

    def trip(self, *, status: str, reason: str, report_id: str) -> None:
        payload = {
            "halted": True,
            "status": status,
            "reason": reason,
            "report_id": report_id,
            "tripped_at": _now().isoformat(),
        }
        self.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def extract_broker_order_id(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        for key in ("id", "order_id", "orderId", "broker_order_id"):
            value = raw.get(key)
            if value:
                return str(value)
        nested = raw.get("order") or raw.get("data") or {}
        if isinstance(nested, dict):
            return extract_broker_order_id(nested)
    value = _attr(raw, "id", "order_id")
    return str(value) if value else None


def receipt_from_mcp(
    *,
    cycle_id: str,
    payload: CanonicalOrderPayload,
    mcp_result: dict[str, Any],
    now: datetime | None = None,
) -> BrokerReceipt:
    """MCP non-error payload → submitted. Not a fill and not completion."""
    raw = mcp_result.get("raw", mcp_result)
    raw_dict = raw if isinstance(raw, dict) else {"raw": raw}
    submitted = bool(mcp_result.get("submitted")) and not bool(mcp_result.get("dry_run"))
    broker_order_id = extract_broker_order_id(raw_dict)
    raw_status = _text(_attr(raw_dict, "status", "raw_status") or ("submitted" if submitted else "dry_run"))
    return BrokerReceipt(
        receipt_id=uuid.uuid4().hex,
        cycle_id=cycle_id,
        client_order_id=payload.client_order_id,
        broker_order_id=broker_order_id,
        received_at=ensure_utc(now or _now()),
        raw_status=raw_status,
        is_success=submitted,
        error_message=None,
        response_payload=raw_dict if isinstance(raw_dict, dict) else {"raw": _text(raw)},
        submitted=submitted,
    )


def _broker_legs(order: Any) -> list[dict[str, str]]:
    raw_legs = _attr(order, "legs", "leg_orders", "legs_orders") or []
    legs: list[dict[str, str]] = []
    for item in list(raw_legs or []):
        symbol = _text(_attr(item, "symbol")).upper()
        ratio = _text(_attr(item, "ratio_qty", "ratio", "qty") or "1")
        side = _lower(_attr(item, "side"))
        intent = _lower(_attr(item, "position_intent", "intent"))
        legs.append(
            {
                "symbol": symbol,
                "ratio_qty": ratio,
                "side": side,
                "position_intent": intent,
            }
        )
    return sorted(legs, key=lambda leg: (leg["symbol"], leg["side"], leg["ratio_qty"]))


def _expected_legs(payload: CanonicalOrderPayload) -> list[dict[str, str]]:
    legs = [
        {
            "symbol": leg.symbol,
            "ratio_qty": str(leg.ratio_qty),
            "side": leg.side.value,
            "position_intent": leg.position_intent.value,
        }
        for leg in payload.legs
    ]
    return sorted(legs, key=lambda leg: (leg["symbol"], leg["side"], leg["ratio_qty"]))


def _read_orders(broker: Any, payload: CanonicalOrderPayload, receipt: BrokerReceipt) -> list[Any] | None:
    client_id = payload.client_order_id
    try:
        listed = None
        if hasattr(broker, "fetch_orders_by_client_id"):
            listed = broker.fetch_orders_by_client_id(client_id)
        orders = list(listed or [])
        if not orders and hasattr(broker, "fetch_order"):
            fetched = broker.fetch_order(order_id=receipt.broker_order_id, client_order_id=client_id)
            if fetched is not None:
                if isinstance(fetched, list):
                    orders = list(fetched)
                else:
                    orders = [fetched]
        return orders
    except Exception:
        return None


def reconcile(
    *,
    payload: CanonicalOrderPayload,
    receipt: BrokerReceipt,
    broker: Any,
    settings: HackathonSettings,
    now: datetime | None = None,
    cycle_id: str | None = None,
) -> ReconciliationReport:
    clock = ensure_utc(now or _now())
    report_id = uuid.uuid4().hex
    cycle = cycle_id or payload.client_order_id
    designated = settings.paper_account_id or payload.account_id
    comparisons: list[FieldComparison] = []
    discrepancies: list[str] = []

    try:
        account = broker.fetch_account() if broker is not None else None
    except Exception:
        return _unknown(report_id, cycle, payload, receipt, clock, "account read failed")

    if account is None or broker is None:
        return _unknown(report_id, cycle, payload, receipt, clock, "broker account missing")

    account_id = _text(_attr(account, "id", "account_number", "account_id"))
    comparisons.append(_compare("account", designated, account_id))
    if not comparisons[-1].matched:
        discrepancies.append("account")

    orders = _read_orders(broker, payload, receipt)
    if orders is None:
        return _unknown(report_id, cycle, payload, receipt, clock, "order read failed")
    if not orders:
        return _unknown(report_id, cycle, payload, receipt, clock, "order missing")
    if len(orders) > 1:
        return ReconciliationReport(
            report_id=report_id,
            cycle_id=cycle,
            client_order_id=payload.client_order_id,
            broker_order_id=receipt.broker_order_id,
            status=ReconciliationStatus.DUPLICATE,
            reconciled_at=clock,
            broker_status="duplicate",
            filled_qty=0,
            filled_avg_price=None,
            discrepancies=("duplicate client_order_id",),
            halt_triggered=True,
            comparisons=tuple(comparisons),
            containment=(),
            account_id=account_id,
        )

    order = orders[0]
    broker_order_id = _text(_attr(order, "id", "order_id"))
    comparisons.append(_compare("order_id", receipt.broker_order_id or broker_order_id, broker_order_id))
    comparisons.append(
        _compare("client_order_id", payload.client_order_id, _attr(order, "client_order_id"))
    )
    comparisons.append(
        _compare("order_class", payload.order_class, _attr(order, "order_class", "class"))
    )
    comparisons.append(_compare("qty", payload.qty, _attr(order, "qty", "quantity")))
    comparisons.append(
        _compare("limit", payload.limit_price, _attr(order, "limit_price", "limit"))
    )
    broker_status = _lower(_attr(order, "status"))
    filled_qty_raw = _attr(order, "filled_qty", "filled_quantity") or 0
    filled_qty_dec = _decimal(filled_qty_raw) or Decimal("0")
    filled_qty = int(filled_qty_dec)
    filled_price = _decimal(_attr(order, "filled_avg_price", "filled_average_price", "avg_fill_price"))

    expected_legs = _expected_legs(payload)
    observed_legs = _broker_legs(order)
    comparisons.append(_compare("legs", json.dumps(expected_legs), json.dumps(observed_legs)))
    for index, expected in enumerate(expected_legs):
        observed = observed_legs[index] if index < len(observed_legs) else {}
        comparisons.append(_compare(f"leg[{index}].symbol", expected["symbol"], observed.get("symbol")))
        comparisons.append(_compare(f"leg[{index}].ratio", expected["ratio_qty"], observed.get("ratio_qty")))
        comparisons.append(_compare(f"leg[{index}].side", expected["side"], observed.get("side")))
        comparisons.append(
            _compare(f"leg[{index}].intent", expected["position_intent"], observed.get("position_intent"))
        )

    is_partial_status = broker_status in _PARTIAL_STATUSES or (
        0 < filled_qty < int(payload.qty)
    )
    is_filled_status = broker_status in _FILLED_STATUSES
    expected_status = "filled" if not is_partial_status else "partially_filled"
    comparisons.append(_compare("status", expected_status, broker_status or "unknown"))
    comparisons.append(_compare("filled_qty", payload.qty if is_filled_status else filled_qty, filled_qty))
    comparisons.append(
        _compare("filled_avg_price", payload.limit_price if is_filled_status else (filled_price or ""), filled_price)
    )

    for item in comparisons:
        if not item.matched and item.field not in discrepancies:
            discrepancies.append(item.field)

    identity_fields = {
        "account",
        "client_order_id",
        "order_class",
        "qty",
        "limit",
        "legs",
    }
    identity_ok = all(
        item.matched for item in comparisons if item.field in identity_fields or item.field.startswith("leg[")
    )
    if receipt.broker_order_id:
        identity_ok = identity_ok and all(
            item.matched for item in comparisons if item.field == "order_id"
        )

    if is_partial_status and identity_ok:
        return ReconciliationReport(
            report_id=report_id,
            cycle_id=cycle,
            client_order_id=payload.client_order_id,
            broker_order_id=broker_order_id or receipt.broker_order_id,
            status=ReconciliationStatus.PARTIAL_FILL,
            reconciled_at=clock,
            broker_status=broker_status or "partially_filled",
            filled_qty=filled_qty,
            filled_avg_price=filled_price,
            discrepancies=("partial fill",),
            halt_triggered=True,
            comparisons=tuple(comparisons),
            containment=PARTIAL_FILL_CONTAINMENT,
            account_id=account_id,
        )

    if is_filled_status and identity_ok and filled_qty == int(payload.qty) and filled_price is not None:
        price_ok = all(item.matched for item in comparisons if item.field == "filled_avg_price")
        if price_ok and all(item.matched for item in comparisons if item.field in {"status", "filled_qty"}):
            return ReconciliationReport(
                report_id=report_id,
                cycle_id=cycle,
                client_order_id=payload.client_order_id,
                broker_order_id=broker_order_id or receipt.broker_order_id,
                status=ReconciliationStatus.MATCHED,
                reconciled_at=clock,
                broker_status=broker_status,
                filled_qty=filled_qty,
                filled_avg_price=filled_price,
                discrepancies=(),
                halt_triggered=False,
                comparisons=tuple(comparisons),
                containment=(),
                account_id=account_id,
            )

    return ReconciliationReport(
        report_id=report_id,
        cycle_id=cycle,
        client_order_id=payload.client_order_id,
        broker_order_id=broker_order_id or receipt.broker_order_id,
        status=ReconciliationStatus.MISMATCH,
        reconciled_at=clock,
        broker_status=broker_status or "mismatch",
        filled_qty=filled_qty,
        filled_avg_price=filled_price,
        discrepancies=tuple(discrepancies) or ("field mismatch",),
        halt_triggered=True,
        comparisons=tuple(comparisons),
        containment=(),
        account_id=account_id,
    )


def _unknown(
    report_id: str,
    cycle: str,
    payload: CanonicalOrderPayload,
    receipt: BrokerReceipt,
    clock: datetime,
    reason: str,
) -> ReconciliationReport:
    return ReconciliationReport(
        report_id=report_id,
        cycle_id=cycle,
        client_order_id=payload.client_order_id,
        broker_order_id=receipt.broker_order_id,
        status=ReconciliationStatus.UNKNOWN,
        reconciled_at=clock,
        broker_status="unknown",
        filled_qty=0,
        filled_avg_price=None,
        discrepancies=(reason,),
        halt_triggered=True,
        comparisons=(),
        containment=(),
        account_id=payload.account_id,
    )


def report_as_dict(report: ReconciliationReport) -> dict[str, Any]:
    return {
        "report_id": report.report_id,
        "cycle_id": report.cycle_id,
        "client_order_id": report.client_order_id,
        "broker_order_id": report.broker_order_id,
        "status": report.status.value,
        "broker_status": report.broker_status,
        "filled_qty": report.filled_qty,
        "filled_avg_price": str(report.filled_avg_price) if report.filled_avg_price is not None else None,
        "discrepancies": list(report.discrepancies),
        "halt_triggered": report.halt_triggered,
        "complete": report.complete,
        "containment": list(report.containment),
        "account_id": report.account_id,
        "comparisons": [item.canonical_dict() for item in report.comparisons],
    }


def receipt_as_dict(receipt: BrokerReceipt) -> dict[str, Any]:
    return {
        "receipt_id": receipt.receipt_id,
        "cycle_id": receipt.cycle_id,
        "client_order_id": receipt.client_order_id,
        "broker_order_id": receipt.broker_order_id,
        "received_at": receipt.received_at.isoformat(),
        "raw_status": receipt.raw_status,
        "is_success": receipt.is_success,
        "submitted": receipt.submitted,
        "error_message": receipt.error_message,
        "response_payload": receipt.response_payload,
    }
