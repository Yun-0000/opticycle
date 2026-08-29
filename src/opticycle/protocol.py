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
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"


class ThesisStance(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NO_TRADE = "NO_TRADE"


class ThesisReasonCode(str, Enum):
    TREND_ALIGNED = "TREND_ALIGNED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    STALE_DATA = "STALE_DATA"
    SCHEMA_ERROR = "SCHEMA_ERROR"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    EVIDENCE_CONFLICT = "EVIDENCE_CONFLICT"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    LLM_DISABLED = "LLM_DISABLED"


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
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"
    DUPLICATE = "duplicate"
    PARTIAL_FILL = "partial_fill"
    DISCREPANCY = "mismatch"
    UNKNOWN_BROKER_STATE = "unknown"
    HALTED = "halted"


class ObservationOutcome(str, Enum):
    OK = "OK"
    NO_TRADE = "NO_TRADE"
    HALT = "HALT"


@dataclass(frozen=True, slots=True)
class ObservedDatum:
    """One observed market or account datum with provenance."""

    kind: str
    source: str
    timestamp: datetime
    freshness_seconds: Decimal
    correlation_id: str
    ok: bool
    detail: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp", ensure_utc(self.timestamp))


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
    datums: tuple[ObservedDatum, ...] = ()
    correlation_id: str = ""
    account_id: str | None = None

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
class FeatureSummary:
    """Summarized evidence features. Contains no OCC symbols, qty, or order prices."""

    underlying: str
    observation_timestamp: datetime
    correlation_id: str
    quote_age_seconds: Decimal
    is_fresh: bool
    bars_count: int
    chain_count: int
    spot_bucket: str
    trend_bucket: str
    clock_open: bool | None
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "observation_timestamp", ensure_utc(self.observation_timestamp))


@dataclass(frozen=True, slots=True)
class ThesisRecord:
    """Constrained thesis: stance only, never OCC/qty/price selection."""

    stance: ThesisStance
    confidence: Decimal
    evidence: tuple[str, ...]
    assumptions: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    observation_timestamp: datetime
    reason_code: str
    feature_correlation_id: str
    model_called: bool
    regenerations: int = 0
    accepted: bool = True
    detail: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "observation_timestamp", ensure_utc(self.observation_timestamp))
        if self.stance not in ThesisStance:
            raise ValueError("stance must be BULLISH, BEARISH, or NO_TRADE")


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


def canonical_hash(value: Mapping[str, Any] | dict[str, Any]) -> str:
    """Deterministic SHA-256 over canonical JSON. Used for evidence/account/cert binding."""
    blob = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def parse_occ_symbol(symbol: str) -> tuple[str, datetime, OptionType, Decimal]:
    """Parse OCC option symbol into root, expiration, type, and strike."""
    if not OCC_SYMBOL_RE.fullmatch(symbol):
        raise ValueError(f"Invalid OCC option symbol: {symbol!r}")
    root = symbol[:-15]
    yymmdd = symbol[-15:-9]
    kind = symbol[-9]
    strike_raw = symbol[-8:]
    expiration = datetime.strptime(yymmdd, "%y%m%d").replace(tzinfo=timezone.utc)
    strike = Decimal(strike_raw) / Decimal("1000")
    option_type = OptionType.PUT if kind == "P" else OptionType.CALL
    return root, expiration, option_type, strike


def evidence_canonical_dict(evidence: EvidenceSnapshot) -> dict[str, Any]:
    """Canonical dict for evidence_hash. Quote prices are included; no synthetic fills."""
    quotes = []
    for quote in sorted(evidence.chain_quotes, key=lambda item: item.symbol):
        quotes.append(
            {
                "ask": format_decimal(quote.ask, 4),
                "bid": format_decimal(quote.bid, 4),
                "delta": format_decimal(quote.delta, 6),
                "expiration": ensure_utc(quote.expiration).strftime("%Y-%m-%d"),
                "gamma": format_decimal(quote.gamma, 6),
                "last": format_decimal(quote.last, 4),
                "option_type": quote.option_type.value,
                "strike_price": format_decimal(quote.strike_price, 2),
                "symbol": quote.symbol,
                "theta": format_decimal(quote.theta, 6),
                "underlying": quote.underlying,
                "vega": format_decimal(quote.vega, 6),
            }
        )
    return {
        "account_id": evidence.account_id or "",
        "bars_count": evidence.bars_count,
        "chain_quotes": quotes,
        "correlation_id": evidence.correlation_id,
        "indicators": [[name, format_decimal(value, 6)] for name, value in evidence.indicators],
        "is_fresh": evidence.is_fresh,
        "quote_age_seconds": format_decimal(evidence.quote_age_seconds, 3),
        "spot_price": format_decimal(evidence.spot_price, 4),
        "timestamp": ensure_utc(evidence.timestamp).isoformat(),
        "underlying": evidence.underlying.strip().upper(),
    }


def evidence_digest(evidence: EvidenceSnapshot) -> str:
    return canonical_hash(evidence_canonical_dict(evidence))


@dataclass(frozen=True, slots=True)
class RiskLimits:
    """Single limit set for replay, live, and demo. LLM cannot supply these."""

    max_position_pct: Decimal
    max_daily_trades: int
    max_open_positions: int
    max_abs_delta: Decimal
    max_abs_vega: Decimal
    max_abs_gamma: Decimal
    max_abs_theta: Decimal
    max_concentration_pct: Decimal
    max_daily_loss: Decimal
    max_open_risk: Decimal
    max_quote_age_seconds: Decimal
    equity_tolerance: Decimal
    starting_capital: Decimal
    certificate_ttl_seconds: int
    paper_only: bool
    require_options: bool

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "certificate_ttl_seconds": self.certificate_ttl_seconds,
            "equity_tolerance": format_decimal(self.equity_tolerance, 4),
            "max_abs_delta": format_decimal(self.max_abs_delta, 4),
            "max_abs_gamma": format_decimal(self.max_abs_gamma, 4),
            "max_abs_theta": format_decimal(self.max_abs_theta, 4),
            "max_abs_vega": format_decimal(self.max_abs_vega, 4),
            "max_concentration_pct": format_decimal(self.max_concentration_pct, 4),
            "max_daily_loss": format_decimal(self.max_daily_loss, 2),
            "max_daily_trades": self.max_daily_trades,
            "max_open_positions": self.max_open_positions,
            "max_open_risk": format_decimal(self.max_open_risk, 2),
            "max_position_pct": format_decimal(self.max_position_pct, 4),
            "max_quote_age_seconds": format_decimal(self.max_quote_age_seconds, 3),
            "paper_only": self.paper_only,
            "require_options": self.require_options,
            "starting_capital": format_decimal(self.starting_capital, 2),
        }


@dataclass(frozen=True, slots=True)
class LegRisk:
    """Per-leg quote-derived price and greeks. Prices come only from market data."""

    symbol: str
    side: str
    ratio_qty: int
    bid: Decimal
    ask: Decimal
    delta: Decimal
    vega: Decimal
    gamma: Decimal
    theta: Decimal

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "ask": format_decimal(self.ask, 4),
            "bid": format_decimal(self.bid, 4),
            "delta": format_decimal(self.delta, 6),
            "gamma": format_decimal(self.gamma, 6),
            "ratio_qty": self.ratio_qty,
            "side": self.side,
            "symbol": self.symbol,
            "theta": format_decimal(self.theta, 6),
            "vega": format_decimal(self.vega, 6),
        }


@dataclass(frozen=True, slots=True)
class CalculatedRisk:
    """Deterministic risk on the exact MLEG vertical from real quotes and account."""

    is_credit: bool
    width: Decimal
    net_credit: Decimal
    net_debit: Decimal
    max_loss: Decimal
    max_profit: Decimal
    buying_power_impact: Decimal
    concentration_pct: Decimal
    daily_trades: int
    open_risk: Decimal
    daily_loss: Decimal
    quote_age_seconds: Decimal
    quote_fresh: bool
    combo_delta: Decimal
    combo_vega: Decimal
    combo_gamma: Decimal
    combo_theta: Decimal
    portfolio_delta: Decimal
    portfolio_vega: Decimal
    portfolio_gamma: Decimal
    portfolio_theta: Decimal
    legs: tuple[LegRisk, ...]
    portfolio_equity: Decimal
    buying_power: Decimal

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "buying_power": format_decimal(self.buying_power, 2),
            "buying_power_impact": format_decimal(self.buying_power_impact, 2),
            "combo_delta": format_decimal(self.combo_delta, 6),
            "combo_gamma": format_decimal(self.combo_gamma, 6),
            "combo_theta": format_decimal(self.combo_theta, 6),
            "combo_vega": format_decimal(self.combo_vega, 6),
            "concentration_pct": format_decimal(self.concentration_pct, 6),
            "daily_loss": format_decimal(self.daily_loss, 2),
            "daily_trades": self.daily_trades,
            "is_credit": self.is_credit,
            "legs": [leg.canonical_dict() for leg in self.legs],
            "max_loss": format_decimal(self.max_loss, 2),
            "max_profit": format_decimal(self.max_profit, 2),
            "net_credit": format_decimal(self.net_credit, 4),
            "net_debit": format_decimal(self.net_debit, 4),
            "open_risk": format_decimal(self.open_risk, 2),
            "portfolio_delta": format_decimal(self.portfolio_delta, 6),
            "portfolio_equity": format_decimal(self.portfolio_equity, 2),
            "portfolio_gamma": format_decimal(self.portfolio_gamma, 6),
            "portfolio_theta": format_decimal(self.portfolio_theta, 6),
            "portfolio_vega": format_decimal(self.portfolio_vega, 6),
            "quote_age_seconds": format_decimal(self.quote_age_seconds, 3),
            "quote_fresh": self.quote_fresh,
            "width": format_decimal(self.width, 4),
        }


@dataclass(frozen=True, slots=True)
class RiskCertificate:
    """Hash-bound authorization for one exact MLEG order. LLM cannot modify it."""

    certificate_id: str
    cycle_id: str
    payload_hash: str
    evidence_hash: str
    account_hash: str
    client_order_id: str
    account_id: str
    approval: bool
    veto: bool
    reasons: tuple[str, ...]
    limits: RiskLimits
    calculated_risk: CalculatedRisk
    issued_at: datetime
    expires_at: datetime
    binding_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "issued_at", ensure_utc(self.issued_at))
        object.__setattr__(self, "expires_at", ensure_utc(self.expires_at))
        if len(self.payload_hash) != 64:
            raise ValueError("payload_hash must be exactly 64 hex characters")
        if len(self.evidence_hash) != 64:
            raise ValueError("evidence_hash must be exactly 64 hex characters")
        if len(self.account_hash) != 64:
            raise ValueError("account_hash must be exactly 64 hex characters")
        if self.approval == self.veto:
            raise ValueError("certificate must be either approval or veto, not both")
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be after issued_at")
        computed = canonical_hash(self._binding_dict())
        object.__setattr__(self, "binding_hash", computed)

    def _binding_dict(self) -> dict[str, Any]:
        return {
            "account_hash": self.account_hash,
            "account_id": self.account_id,
            "approval": self.approval,
            "calculated_risk": self.calculated_risk.canonical_dict(),
            "certificate_id": self.certificate_id,
            "client_order_id": self.client_order_id,
            "cycle_id": self.cycle_id,
            "evidence_hash": self.evidence_hash,
            "expires_at": ensure_utc(self.expires_at).isoformat(),
            "issued_at": ensure_utc(self.issued_at).isoformat(),
            "limits": self.limits.canonical_dict(),
            "payload_hash": self.payload_hash,
            "reasons": list(self.reasons),
            "veto": self.veto,
        }

    @property
    def passed(self) -> bool:
        return self.approval and not self.veto

    @property
    def timestamp(self) -> datetime:
        return self.issued_at

    @property
    def portfolio_equity(self) -> Decimal:
        return self.calculated_risk.portfolio_equity

    @property
    def buying_power(self) -> Decimal:
        return self.calculated_risk.buying_power

    @property
    def projected_delta(self) -> Decimal:
        return self.calculated_risk.portfolio_delta

    @property
    def projected_vega(self) -> Decimal:
        return self.calculated_risk.portfolio_vega

    @property
    def max_risk_allowed(self) -> Decimal:
        return self.limits.max_open_risk


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
class FieldComparison:
    """One authorized-vs-broker field comparison."""

    field: str
    expected: str
    observed: str
    matched: bool

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "expected": self.expected,
            "field": self.field,
            "matched": self.matched,
            "observed": self.observed,
        }


@dataclass(frozen=True, slots=True)
class BrokerReceipt:
    """Immediate MCP response. Success here is not a fill and not completion."""
    receipt_id: str
    cycle_id: str
    client_order_id: str
    broker_order_id: str | None
    received_at: datetime
    raw_status: str
    is_success: bool
    error_message: str | None = None
    response_payload: dict[str, Any] = field(default_factory=dict)
    submitted: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "received_at", ensure_utc(self.received_at))


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    """Post-trade broker state reconciliation. Only MATCHED completes a cycle."""
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
    comparisons: tuple[FieldComparison, ...] = ()
    containment: tuple[str, ...] = ()
    account_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "reconciled_at", ensure_utc(self.reconciled_at))

    @property
    def complete(self) -> bool:
        return self.status == ReconciliationStatus.MATCHED and not self.halt_triggered


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
    thesis: ThesisRecord | None = None
    terminal_state: ExecutionStatus = ExecutionStatus.PENDING

    def __post_init__(self) -> None:
        object.__setattr__(self, "started_at", ensure_utc(self.started_at))
        if self.finished_at is not None:
            object.__setattr__(self, "finished_at", ensure_utc(self.finished_at))
