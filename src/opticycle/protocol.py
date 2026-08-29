"""Opticycle unified protocol domain objects.

All financial amounts use Decimal. All timestamps are UTC datetimes.
Every canonical order payload derives a deterministic SHA-256 payload_hash
covering sorted legs, ratio, side, intent, qty, limit_price, order_class, and account.
MCP tool arguments are produced strictly from CanonicalOrderPayload.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any, Mapping, Sequence

OCC_SYMBOL_RE = re.compile(r"^[A-Z]{1,6}\d{6}[CP]\d{8}$")


def ensure_utc(dt: datetime | None = None) -> datetime:
    """Return timezone-aware UTC datetime with microsecond precision."""
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_decimal(d: Decimal, places: int = 2) -> str:
    """Canonical string formatting for financial decimal numbers."""
    q = Decimal("10") ** -places
    return str(d.quantize(q, rounding=ROUND_HALF_UP))


class StrategyKind(str, Enum):
    VERTICAL_SPREAD = "vertical_spread"


class ThesisAction(str, Enum):
    OPEN_SPREAD = "OPEN_SPREAD"
    NO_TRADE = "NO_TRADE"
    HOLD = "HOLD"


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class PositionIntent(str, Enum):
    BUY_TO_OPEN = "buy_to_open"
    BUY_TO_CLOSE = "buy_to_close"
    SELL_TO_OPEN = "sell_to_open"
    SELL_TO_CLOSE = "sell_to_close"


class OptionType(str, Enum):
    CALL = "call"
    PUT = "put"


class SpreadType(str, Enum):
    BULL_PUT = "bull_put"
    BEAR_CALL = "bear_call"
    BULL_CALL = "bull_call"
    BEAR_PUT = "bear_put"


class ExecutionChannel(str, Enum):
    MCP = "mcp"


class ExecutionStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    FAILED = "failed"
    HALTED = "halted"


class ReconciliationStatus(str, Enum):
    MATCHED = "matched"
    DISCREPANCY = "discrepancy"
    UNKNOWN_BROKER_STATE = "unknown_broker_state"
    HALTED = "halted"


@dataclass(frozen=True, slots=True)
class OptionContractQuote:
    """Point-in-time quote for a single OCC option contract."""
    symbol: str
    underlying: str
    option_type: OptionType
    strike_price: Decimal
    expiration: datetime
    bid: Decimal
    ask: Decimal
    last: Decimal
    delta: Decimal
    gamma: Decimal = Decimal("0")
    theta: Decimal = Decimal("0")
    vega: Decimal = Decimal("0")
    open_interest: int = 0
    volume: int = 0

    def __post_init__(self) -> None:
        if not OCC_SYMBOL_RE.fullmatch(self.symbol):
            raise ValueError(f"Invalid OCC option symbol: {self.symbol!r}")
        if self.strike_price <= Decimal("0"):
            raise ValueError("strike_price must be positive")


@dataclass(frozen=True, slots=True)
class EvidenceSnapshot:
    """Fresh market observation snapshot for the underlying and option chain."""
    underlying: str
    spot_price: Decimal
    timestamp: datetime
    bars_count: int
    quote_age_seconds: Decimal
    is_fresh: bool
    chain_quotes: tuple[OptionContractQuote, ...] = ()
    indicators: tuple[tuple[str, Decimal], ...] = ()

    def __post_init__(self) -> None:
        if self.spot_price <= Decimal("0"):
            raise ValueError("spot_price must be positive")
        object.__setattr__(self, "timestamp", ensure_utc(self.timestamp))


@dataclass(frozen=True, slots=True)
class OptionLegSpec:
    """Strictly typed specification for a single option spread leg."""
    symbol: str
    ratio_qty: int
    side: OrderSide
    position_intent: PositionIntent
    option_type: OptionType
    strike_price: Decimal
    expiration: datetime

    def __post_init__(self) -> None:
        if not OCC_SYMBOL_RE.fullmatch(self.symbol):
            raise ValueError(f"Invalid OCC option symbol: {self.symbol!r}")
        if self.ratio_qty <= 0:
            raise ValueError("ratio_qty must be positive integer")
        if self.strike_price <= Decimal("0"):
            raise ValueError("strike_price must be positive")
        object.__setattr__(self, "expiration", ensure_utc(self.expiration))

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "expiration": self.expiration.strftime("%Y-%m-%d"),
            "option_type": self.option_type.value,
            "position_intent": self.position_intent.value,
            "ratio_qty": str(self.ratio_qty),
            "side": self.side.value,
            "strike_price": format_decimal(self.strike_price, 2),
            "symbol": self.symbol,
        }


@dataclass(frozen=True, slots=True)
class OptionCandidate:
    """Proposed multi-leg options candidate emitted by the strategy."""
    underlying: str
    spread_type: SpreadType
    legs: tuple[OptionLegSpec, ...]
    net_limit_price: Decimal
    max_loss: Decimal
    max_profit: Decimal
    width: Decimal
    dte: int
    is_credit: bool
    score: Decimal

    def __post_init__(self) -> None:
        if len(self.legs) < 2:
            raise ValueError("OptionCandidate must have at least 2 legs for multi-leg spread")
        if self.width <= Decimal("0"):
            raise ValueError("spread width must be positive")


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    """Deterministic trading decision emitted from market evaluation."""
    cycle_id: str
    underlying: str
    action: ThesisAction
    strategy: StrategyKind
    timestamp: datetime
    reason: str
    confidence: Decimal
    candidate: OptionCandidate | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp", ensure_utc(self.timestamp))
        if self.action == ThesisAction.OPEN_SPREAD and self.candidate is None:
            raise ValueError("OPEN_SPREAD decision must include an OptionCandidate")


@dataclass(frozen=True, slots=True)
class CanonicalOrderPayload:
    """Immutable, canonically-ordered multi-leg option order payload."""
    client_order_id: str
    account_id: str
    underlying: str
    order_class: str
    order_type: str
    time_in_force: str
    qty: int
    limit_price: Decimal
    legs: tuple[OptionLegSpec, ...]
    payload_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.client_order_id or not self.client_order_id.strip():
            raise ValueError("client_order_id must be a non-empty string")
        if not self.account_id or not self.account_id.strip():
            raise ValueError("account_id must be a non-empty string")
        if self.qty <= 0:
            raise ValueError("qty must be positive")
        if self.order_class != "mleg":
            raise ValueError("order_class must be 'mleg'")
        if not self.legs or len(self.legs) < 2:
            raise ValueError("CanonicalOrderPayload requires at least 2 legs")

        # Sort legs canonically by symbol, then side, then strike
        sorted_legs = tuple(sorted(self.legs, key=lambda leg: (leg.symbol, leg.side.value, leg.strike_price)))
        object.__setattr__(self, "legs", sorted_legs)

        # Compute deterministic payload hash over canonical JSON structure
        canonical_dict = self.to_canonical_dict()
        canonical_json = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":"))
        computed_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
        object.__setattr__(self, "payload_hash", computed_hash)

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id.strip(),
            "client_order_id": self.client_order_id.strip(),
            "legs": [leg.canonical_dict() for leg in self.legs],
            "limit_price": format_decimal(self.limit_price, 2),
            "order_class": self.order_class,
            "order_type": self.order_type,
            "qty": self.qty,
            "time_in_force": self.time_in_force,
            "underlying": self.underlying.strip().upper(),
        }

    def to_mcp_arguments(self) -> dict[str, Any]:
        """Produce exact alpaca-mcp-server tool arguments from canonical payload."""
        mcp_legs = []
        for leg in self.legs:
            leg_dict: dict[str, Any] = {
                "symbol": leg.symbol,
                "ratio_qty": str(leg.ratio_qty),
                "side": leg.side.value,
                "position_intent": leg.position_intent.value,
            }
            mcp_legs.append(leg_dict)

        return {
            "order_class": "mleg",
            "type": self.order_type,
            "time_in_force": self.time_in_force,
            "qty": str(self.qty),
            "limit_price": format_decimal(self.limit_price, 2),
            "legs": mcp_legs,
            "client_order_id": self.client_order_id,
        }


@dataclass(frozen=True, slots=True)
class RiskCertificate:
    """Cryptographic/hash proof binding deterministic risk checks to payload."""
    certificate_id: str
    cycle_id: str
    payload_hash: str
    client_order_id: str
    account_id: str
    passed: bool
    reasons: tuple[str, ...]
    portfolio_equity: Decimal
    buying_power: Decimal
    projected_delta: Decimal
    projected_vega: Decimal
    max_risk_allowed: Decimal
    timestamp: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp", ensure_utc(self.timestamp))
        if len(self.payload_hash) != 64:
            raise ValueError("payload_hash must be exactly 64 hex characters")


@dataclass(frozen=True, slots=True)
class ExecutionAttempt:
    """Record of an execution dispatch to the sole live MCP channel."""
    attempt_id: str
    cycle_id: str
    channel: ExecutionChannel
    payload_hash: str
    client_order_id: str
    sent_at: datetime
    mcp_tool_name: str
    mcp_arguments: dict[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "sent_at", ensure_utc(self.sent_at))
        if self.channel != ExecutionChannel.MCP:
            raise ValueError("Only MCP execution channel is permitted")


@dataclass(frozen=True, slots=True)
class BrokerReceipt:
    """Immediate response from Alpaca broker via MCP."""
    receipt_id: str
    cycle_id: str
    client_order_id: str
    broker_order_id: str | None
    received_at: datetime
    raw_status: str
    is_success: bool
    error_message: str | None = None
    response_payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "received_at", ensure_utc(self.received_at))


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    """Post-trade broker state reconciliation verifying fills and positions."""
    report_id: str
    cycle_id: str
    client_order_id: str
    broker_order_id: str | None
    status: ReconciliationStatus
    reconciled_at: datetime
    broker_status: str
    filled_qty: int
    filled_avg_price: Decimal | None
    discrepancies: tuple[str, ...] = ()
    halt_triggered: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "reconciled_at", ensure_utc(self.reconciled_at))


@dataclass(frozen=True, slots=True)
class DecisionEpisode:
    """Complete, end-to-end cryptographic audit trail of one trading cycle."""
    cycle_id: str
    underlying: str
    started_at: datetime
    finished_at: datetime | None
    evidence: EvidenceSnapshot
    decision: DecisionRecord
    certificate: RiskCertificate | None = None
    order_payload: CanonicalOrderPayload | None = None
    execution: ExecutionAttempt | None = None
    receipt: BrokerReceipt | None = None
    reconciliation: ReconciliationReport | None = None
    terminal_state: ExecutionStatus = ExecutionStatus.PENDING

    def __post_init__(self) -> None:
        object.__setattr__(self, "started_at", ensure_utc(self.started_at))
        if self.finished_at is not None:
            object.__setattr__(self, "finished_at", ensure_utc(self.finished_at))
