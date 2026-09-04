"""P&L and end-of-cycle equity reconcile to a broker snapshot.

The snapshot is account + positions + fills. Fixture numbers stay labeled
fixture and must never be stamped as live. Live MLEG / fill / receipt / P&L
stay incomplete until a real broker fill exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal, Mapping, Sequence

from opticycle.protocol import FieldComparison, format_decimal

SOURCE_FIXTURE = "fixture"
SOURCE_LIVE_BROKER = "live_broker"
SnapshotSource = Literal["fixture", "live_broker"]
EQUITY_TOLERANCE = Decimal("0.01")


class PnlError(Exception):
    """Broker snapshot P&L cannot be claimed as live."""


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return format_decimal(value, 4).rstrip("0").rstrip(".") or "0"
    return str(value).strip()


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
        if isinstance(obj, Mapping) and name in obj and obj[name] is not None:
            return obj[name]
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value is not None:
                return value
    return default


def _row(obj: Any, keys: Sequence[str]) -> dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, Mapping):
        return {str(key): obj[key] for key in obj}
    out: dict[str, Any] = {}
    for key in keys:
        value = _attr(obj, key)
        if value is not None:
            out[key] = value
    return out


ACCOUNT_KEYS = (
    "id",
    "account_number",
    "equity",
    "cash",
    "long_market_value",
    "short_market_value",
    "last_equity",
)
POSITION_KEYS = ("symbol", "qty", "market_value", "unrealized_pl", "avg_entry_price", "side")
FILL_KEYS = ("symbol", "qty", "filled_qty", "price", "filled_avg_price", "side", "realized_pl", "status")


@dataclass(frozen=True, slots=True)
class BrokerSnapshot:
    account: dict[str, Any]
    positions: tuple[dict[str, Any], ...]
    fills: tuple[dict[str, Any], ...]
    source: SnapshotSource

    def as_dict(self) -> dict[str, Any]:
        return {
            "account": dict(self.account),
            "positions": [dict(row) for row in self.positions],
            "fills": [dict(row) for row in self.fills],
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class PnlReconcileReport:
    matched: bool
    source: SnapshotSource
    end_of_cycle_equity: Decimal | None
    realized_pnl: Decimal | None
    unrealized_pnl: Decimal | None
    realized_present: bool
    live_claimed: bool
    comparisons: tuple[FieldComparison, ...] = ()
    discrepancies: tuple[str, ...] = ()
    snapshot: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "matched": self.matched,
            "source": self.source,
            "end_of_cycle_equity": str(self.end_of_cycle_equity) if self.end_of_cycle_equity is not None else None,
            "realized_pnl": str(self.realized_pnl) if self.realized_pnl is not None else None,
            "unrealized_pnl": str(self.unrealized_pnl) if self.unrealized_pnl is not None else None,
            "realized_present": self.realized_present,
            "live_claimed": self.live_claimed,
            "discrepancies": list(self.discrepancies),
            "comparisons": [item.canonical_dict() for item in self.comparisons],
            "snapshot_source": self.source,
        }


def snapshot_from_objects(
    *,
    account: Any,
    positions: Any = None,
    fills: Any = None,
    source: SnapshotSource,
) -> BrokerSnapshot:
    if source not in {SOURCE_FIXTURE, SOURCE_LIVE_BROKER}:
        raise PnlError(f"unknown broker snapshot source {source!r}")
    pos_rows = tuple(_row(item, POSITION_KEYS) for item in list(positions or []))
    fill_rows = tuple(_row(item, FILL_KEYS) for item in list(fills or []))
    return BrokerSnapshot(
        account=_row(account, ACCOUNT_KEYS),
        positions=pos_rows,
        fills=fill_rows,
        source=source,
    )


def snapshot_from_client(client: Any, *, source: SnapshotSource) -> BrokerSnapshot:
    account = client.fetch_account() if client is not None else None
    positions = client.fetch_positions() if client is not None and hasattr(client, "fetch_positions") else []
    fills = client.fetch_fills() if client is not None and hasattr(client, "fetch_fills") else []
    return snapshot_from_objects(account=account, positions=positions, fills=fills, source=source)


def _compare(field: str, expected: Any, observed: Any) -> FieldComparison:
    exp_num = _decimal(expected)
    obs_num = _decimal(observed)
    if exp_num is not None and obs_num is not None:
        matched = abs(exp_num - obs_num) <= EQUITY_TOLERANCE
        return FieldComparison(
            field=field,
            expected=format_decimal(exp_num, 4),
            observed=format_decimal(obs_num, 4),
            matched=matched,
        )
    exp = _text(expected)
    obs = _text(observed)
    return FieldComparison(field=field, expected=exp, observed=obs, matched=exp == obs and bool(exp))


def pnl_from_snapshot(snapshot: BrokerSnapshot) -> PnlReconcileReport:
    """Derive P&L/equity from the snapshot and check identity. Never invent a live fill."""
    equity = _decimal(_attr(snapshot.account, "equity"))
    cash = _decimal(_attr(snapshot.account, "cash"))
    long_mv = _decimal(_attr(snapshot.account, "long_market_value"))
    short_mv = _decimal(_attr(snapshot.account, "short_market_value"))
    if long_mv is None:
        market_values = [_decimal(_attr(row, "market_value")) for row in snapshot.positions]
        if market_values and all(item is not None for item in market_values):
            long_mv = sum(market_values, Decimal("0"))  # type: ignore[arg-type]
    unrealized_parts = [_decimal(_attr(row, "unrealized_pl")) or Decimal("0") for row in snapshot.positions]
    unrealized = sum(unrealized_parts, Decimal("0"))
    realized_parts = [_decimal(_attr(row, "realized_pl")) for row in snapshot.fills]
    realized_present = any(part is not None for part in realized_parts)
    realized = sum((part for part in realized_parts if part is not None), Decimal("0")) if realized_present else None

    comparisons: list[FieldComparison] = []
    discrepancies: list[str] = []
    if equity is None:
        discrepancies.append("equity missing")
        comparisons.append(_compare("end_of_cycle_equity", "present", ""))
    else:
        comparisons.append(_compare("end_of_cycle_equity", equity, equity))

    comparisons.append(_compare("unrealized_pnl", unrealized, unrealized))

    if cash is not None and long_mv is not None:
        # Alpaca signs short_market_value negative. Identity is cash + long + short.
        reconstructed = cash + long_mv + (short_mv if short_mv is not None else Decimal("0"))
        item = _compare("equity_identity", equity, reconstructed)
        comparisons.append(item)
        if equity is None or not item.matched:
            discrepancies.append("equity_identity")

    matched = not discrepancies and equity is not None
    return PnlReconcileReport(
        matched=matched,
        source=snapshot.source,
        end_of_cycle_equity=equity,
        realized_pnl=realized,
        unrealized_pnl=unrealized,
        realized_present=realized_present,
        live_claimed=False,
        comparisons=tuple(comparisons),
        discrepancies=tuple(discrepancies),
        snapshot=snapshot.as_dict(),
    )


def may_claim_live_pnl(snapshot: BrokerSnapshot, *, real_fill: bool) -> bool:
    """Fixture numbers are never live. Live claim requires a real broker fill."""
    if snapshot.source != SOURCE_LIVE_BROKER:
        return False
    return bool(real_fill)
