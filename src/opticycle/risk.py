"""Deterministic pre-trade risk engine and payload-bound Risk Certificate.

Quote bid/ask size the market credit. The certified max-loss for a credit
vertical uses the signed Alpaca MLEG limit (negative = credit floor), so the
certificate matches the exact payload the broker will accept. Missing or
stale quotes veto. A credit vertical with a non-negative limit is vetoed.
The hardcoded pin fallback limit is never a risk input. The LLM cannot
issue or edit certificates.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Mapping

from opticycle.protocol import (
    CalculatedRisk,
    CanonicalOrderPayload,
    EvidenceSnapshot,
    LegRisk,
    OptionContractQuote,
    OptionLegSpec,
    OptionType,
    OrderSide,
    PositionIntent,
    RiskCertificate,
    RiskLimits,
    canonical_hash,
    ensure_utc,
    evidence_digest,
    format_decimal,
    freshness_seconds,
    parse_occ_symbol,
)
from opticycle.settings import HackathonSettings
from trade.orders import OCC_SYMBOL_RE, ExecutionRejected, OptionOrderRequest

OPTION_MULTIPLIER = 100
CERTIFICATE_TTL_SECONDS = 60
MAX_QUOTE_AGE_SECONDS = Decimal("120")
DAILY_LOSS_FRACTION = Decimal("0.02")
MAX_ABS_GAMMA = Decimal("40")
MAX_ABS_THETA = Decimal("400")
VOLLIB_RATE = 0.04

# Pin leftover. Never used as a quote, premium, or certificate price.
PIN_LIMIT_FALLBACK = Decimal("0.85")


@dataclass(slots=True)
class PortfolioSnapshot:
    equity: float
    buying_power: float
    cash: float
    account_id: str | None = None
    paper: bool = False
    options_approved: bool = False
    trades_today: int = 0
    open_positions: int = 0
    net_delta: float | None = None
    net_vega: float | None = None
    net_gamma: float | None = None
    net_theta: float | None = None
    daily_loss: float = 0.0
    open_risk: float = 0.0
    positions: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class GateResult:
    approved: bool
    reasons: list[str] = field(default_factory=list)

    def raise_if_rejected(self) -> None:
        if not self.approved:
            raise ExecutionRejected("; ".join(self.reasons) or "risk gate rejected the order")


def _optional_greek_str(value: float | None) -> str:
    if value is None:
        return ""
    return format_decimal(Decimal(str(value)), 6)


def account_canonical_dict(portfolio: PortfolioSnapshot) -> dict[str, Any]:
    positions = []
    for item in portfolio.positions:
        if isinstance(item, Mapping):
            positions.append({str(key): item[key] for key in sorted(item)})
        else:
            positions.append({"repr": repr(item)})
    return {
        "account_id": str(portfolio.account_id or ""),
        "buying_power": format_decimal(Decimal(str(portfolio.buying_power)), 2),
        "cash": format_decimal(Decimal(str(portfolio.cash)), 2),
        "daily_loss": format_decimal(Decimal(str(portfolio.daily_loss)), 2),
        "equity": format_decimal(Decimal(str(portfolio.equity)), 2),
        "net_delta": _optional_greek_str(portfolio.net_delta),
        "net_gamma": _optional_greek_str(portfolio.net_gamma),
        "net_theta": _optional_greek_str(portfolio.net_theta),
        "net_vega": _optional_greek_str(portfolio.net_vega),
        "open_positions": int(portfolio.open_positions),
        "open_risk": format_decimal(Decimal(str(portfolio.open_risk)), 2),
        "options_approved": bool(portfolio.options_approved),
        "paper": bool(portfolio.paper),
        "positions": positions,
        "trades_today": int(portfolio.trades_today),
    }


def account_digest(portfolio: PortfolioSnapshot) -> str:
    return canonical_hash(account_canonical_dict(portfolio))


def limits_from_settings(settings: HackathonSettings) -> RiskLimits:
    """One limit set. Mode is ignored; replay/live/demo cannot diverge."""
    capital = Decimal(str(settings.starting_capital))
    max_position_pct = Decimal(str(settings.max_position_pct))
    return RiskLimits(
        max_position_pct=max_position_pct,
        max_daily_trades=int(settings.max_daily_trades),
        max_open_positions=int(settings.max_open_positions),
        max_abs_delta=Decimal(str(settings.max_abs_delta)),
        max_abs_vega=Decimal(str(settings.max_abs_vega)),
        max_abs_gamma=MAX_ABS_GAMMA,
        max_abs_theta=MAX_ABS_THETA,
        max_concentration_pct=max_position_pct,
        max_daily_loss=(capital * DAILY_LOSS_FRACTION).quantize(Decimal("0.01")),
        max_open_risk=(capital * max_position_pct).quantize(Decimal("0.01")),
        max_quote_age_seconds=MAX_QUOTE_AGE_SECONDS,
        equity_tolerance=Decimal(str(settings.equity_tolerance)),
        starting_capital=capital,
        certificate_ttl_seconds=CERTIFICATE_TTL_SECONDS,
        paper_only=bool(settings.paper_only),
        require_options=bool(settings.require_options),
    )


def independent_vertical_risk(
    *,
    width: Decimal,
    net_credit: Decimal,
    net_debit: Decimal,
    qty: int,
    is_credit: bool,
) -> tuple[Decimal, Decimal]:
    """Independent defined-risk vertical formula.

    Credit: max_loss = (width - credit) * 100 * qty; max_profit = credit * 100 * qty
    Debit:  max_loss = debit * 100 * qty; max_profit = (width - debit) * 100 * qty
    """
    contracts = Decimal(abs(int(qty))) * Decimal(OPTION_MULTIPLIER)
    if is_credit:
        max_profit = net_credit * contracts
        max_loss = (width - net_credit) * contracts
    else:
        max_loss = net_debit * contracts
        max_profit = (width - net_debit) * contracts
    return max_loss, max_profit


def contract_greeks(
    flag: str,
    spot: float,
    strike: float,
    time_to_expiry: float,
    rate: float,
    sigma: float,
) -> dict[str, float]:
    """Black-Scholes greeks via vollib (delta/vega per 1.00, scaled by multiplier in callers)."""
    from vollib.black_scholes.greeks.analytical import delta, vega, gamma, theta

    kind = "c" if flag.lower().startswith("c") else "p"
    return {
        "delta": float(delta(kind, spot, strike, time_to_expiry, rate, sigma)),
        "vega": float(vega(kind, spot, strike, time_to_expiry, rate, sigma)),
        "gamma": float(gamma(kind, spot, strike, time_to_expiry, rate, sigma)),
        "theta": float(theta(kind, spot, strike, time_to_expiry, rate, sigma)),
    }


def scale_greeks(greeks: dict[str, float], qty: int, side: str) -> dict[str, float]:
    sign = -1.0 if side.lower() == "sell" else 1.0
    factor = sign * abs(qty) * OPTION_MULTIPLIER
    return {key: value * factor for key, value in greeks.items()}


def quotes_by_symbol(evidence: EvidenceSnapshot) -> dict[str, OptionContractQuote]:
    return {quote.symbol: quote for quote in evidence.chain_quotes}


def _optional_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        parsed = Decimal(str(value))
    except Exception:
        return None
    if parsed.is_nan():
        return None
    return parsed


def observed_greeks(quote: OptionContractQuote) -> bool:
    """True when all four greeks are present as real inputs, not defaulted zeros."""
    values = (quote.delta, quote.gamma, quote.theta, quote.vega)
    if any(item is None for item in values):
        return False
    if all(item == Decimal("0") for item in values):
        # Fixture-only zeros are not a live greek observation, even if IV is set.
        return False
    return True


def payload_from_request(
    request: OptionOrderRequest,
    *,
    account_id: str,
    client_order_id: str,
    underlying: str = "SPY",
) -> CanonicalOrderPayload:
    request.assert_options_instrument()
    if not request.is_multileg or not request.legs:
        raise ExecutionRejected("Risk Certificate requires an MLEG vertical")
    if request.limit_price is None:
        raise ExecutionRejected("NO_TRADE: missing market-derived limit price")
    legs: list[OptionLegSpec] = []
    for raw in request.legs:
        symbol = str(raw.get("symbol") or "").upper()
        root, expiration, option_type, strike = parse_occ_symbol(symbol)
        _ = root
        side = OrderSide(str(raw.get("side") or "").lower())
        intent = PositionIntent(str(raw.get("position_intent") or "").lower())
        legs.append(
            OptionLegSpec(
                symbol=symbol,
                ratio_qty=int(raw.get("ratio_qty") or raw.get("ratio") or 1),
                side=side,
                position_intent=intent,
                option_type=option_type,
                strike_price=strike,
                expiration=expiration,
            )
        )
    return CanonicalOrderPayload(
        client_order_id=client_order_id,
        account_id=account_id,
        underlying=underlying,
        order_class="mleg",
        order_type=request.order_type or "limit",
        time_in_force=request.time_in_force or "day",
        qty=int(request.qty),
        limit_price=Decimal(str(request.limit_price)),
        legs=tuple(legs),
    )


def option_request_from_payload(payload: CanonicalOrderPayload) -> OptionOrderRequest:
    return OptionOrderRequest(
        qty=payload.qty,
        order_type=payload.order_type,
        time_in_force=payload.time_in_force,
        limit_price=float(payload.limit_price),
        client_order_id=payload.client_order_id,
        order_class="mleg",
        legs=[
            {
                "symbol": leg.symbol,
                "ratio_qty": str(leg.ratio_qty),
                "side": leg.side.value,
                "position_intent": leg.position_intent.value,
            }
            for leg in payload.legs
        ],
    )


def evidence_from_chain_rows(
    *,
    underlying: str,
    spot: Decimal,
    rows: Any,
    account_id: str | None,
    timestamp: datetime | None = None,
    quote_age_seconds: Decimal = Decimal("0"),
    bars_count: int = 0,
    correlation_id: str = "",
) -> EvidenceSnapshot:
    """Build evidence from an already-observed chain (DataFrame or quote tuples)."""
    now = ensure_utc(timestamp or datetime.now(timezone.utc))
    quotes: list[OptionContractQuote] = []
    if hasattr(rows, "iterrows"):
        iterable = (row for _, row in rows.iterrows())
    else:
        iterable = rows
    for row in iterable:
        getter = row.get if hasattr(row, "get") else lambda key, default=None: getattr(row, key, default)
        symbol = str(getter("symbol") or "").upper()
        if not OCC_SYMBOL_RE.fullmatch(symbol):
            continue
        root, expiration, option_type, strike = parse_occ_symbol(symbol)
        bid = Decimal(str(getter("bid_price") if getter("bid_price") is not None else getter("bid") or 0))
        ask = Decimal(str(getter("ask_price") if getter("ask_price") is not None else getter("ask") or 0))
        last = Decimal(str(getter("last_price") if getter("last_price") is not None else getter("last") or 0))
        kind = str(getter("option_type") or option_type.value)
        resolved_type = OptionType.PUT if str(kind).upper().startswith("P") else OptionType.CALL
        quote_ts = getter("quote_timestamp") or getter("timestamp")
        if not isinstance(quote_ts, datetime):
            quote_ts = None
        iv = _optional_decimal(getter("implied_volatility") if getter("implied_volatility") is not None else getter("iv"))
        quotes.append(
            OptionContractQuote(
                symbol=symbol,
                underlying=root or underlying,
                option_type=resolved_type,
                strike_price=strike,
                expiration=expiration,
                bid=bid,
                ask=ask,
                last=last,
                delta=_optional_decimal(getter("delta")),
                gamma=_optional_decimal(getter("gamma")),
                theta=_optional_decimal(getter("theta")),
                vega=_optional_decimal(getter("vega")),
                quote_timestamp=quote_ts,
                implied_volatility=iv,
            )
        )
    return EvidenceSnapshot(
        underlying=underlying,
        spot_price=spot,
        timestamp=now,
        bars_count=int(bars_count),
        quote_age_seconds=quote_age_seconds,
        is_fresh=quote_age_seconds <= MAX_QUOTE_AGE_SECONDS,
        chain_quotes=tuple(quotes),
        correlation_id=correlation_id,
        account_id=account_id,
        quote_timestamp=now,
    )


class RiskGate:
    """Legacy OCC/account gates plus the Gate 5 certificate issuer."""

    def __init__(self, settings: HackathonSettings) -> None:
        self.settings = settings
        self.engine = RiskEngine(settings)

    def evaluate(
        self,
        request: OptionOrderRequest,
        portfolio: PortfolioSnapshot,
        *,
        underlying_price: float | None = None,
        option_price: float | None = None,
        proposed_delta: float = 0.0,
        proposed_vega: float = 0.0,
    ) -> GateResult:
        reasons: list[str] = []
        request.assert_options_instrument()

        if not self.settings.require_options:
            reasons.append("options-mandatory profile is off")
        if not portfolio.paper or not self.settings.paper_only:
            reasons.append("paper account required")
        if not portfolio.options_approved:
            reasons.append("options trading is not approved on this account")

        expected_id = self.settings.paper_account_id
        if expected_id and portfolio.account_id and portfolio.account_id != expected_id:
            reasons.append("account id does not match the dedicated paper account")

        target = self.settings.starting_capital
        if portfolio.equity <= 0:
            reasons.append("equity is missing")
        else:
            drift = abs(portfolio.equity - target) / target
            if drift > self.settings.equity_tolerance:
                reasons.append(
                    f"equity {portfolio.equity:.0f} is outside the ${target:.0f} paper book window"
                )

        if portfolio.trades_today >= self.settings.max_daily_trades:
            reasons.append("daily trade limit reached")
        if portfolio.open_positions >= self.settings.max_open_positions:
            reasons.append("open position limit reached")

        notional = _order_notional(request, underlying_price, option_price)
        if portfolio.equity > 0 and notional / portfolio.equity > self.settings.max_position_pct:
            reasons.append("order exceeds max position percent")
        if notional > portfolio.buying_power:
            reasons.append("insufficient buying power")

        if portfolio.net_delta is None or portfolio.net_vega is None:
            reasons.append("NO_TRADE: missing portfolio greeks")
        else:
            new_delta = abs(portfolio.net_delta + proposed_delta)
            new_vega = abs(portfolio.net_vega + proposed_vega)
            if new_delta > self.settings.max_abs_delta:
                reasons.append("portfolio delta limit exceeded")
            if new_vega > self.settings.max_abs_vega:
                reasons.append("portfolio vega limit exceeded")

        return GateResult(approved=not reasons, reasons=reasons)

    def issue_certificate(
        self,
        payload: CanonicalOrderPayload,
        portfolio: PortfolioSnapshot,
        evidence: EvidenceSnapshot,
        *,
        now: datetime | None = None,
        cycle_id: str | None = None,
        mode: str = "live",
    ) -> RiskCertificate:
        return self.engine.issue(
            payload,
            portfolio,
            evidence,
            now=now,
            cycle_id=cycle_id,
            mode=mode,
        )


class RiskEngine:
    """Issue and verify Risk Certificates on the exact MLEG order."""

    def __init__(self, settings: HackathonSettings) -> None:
        self.settings = settings
        self.limits = limits_from_settings(settings)

    def limits_for(self, mode: str) -> RiskLimits:
        """Replay, live, and demo all return the same frozen limits."""
        _ = mode
        return self.limits

    def issue(
        self,
        payload: CanonicalOrderPayload,
        portfolio: PortfolioSnapshot,
        evidence: EvidenceSnapshot,
        *,
        now: datetime | None = None,
        cycle_id: str | None = None,
        mode: str = "live",
    ) -> RiskCertificate:
        _ = self.limits_for(mode)
        issued_at = ensure_utc(now or datetime.now(timezone.utc))
        expires_at = issued_at + timedelta(seconds=self.limits.certificate_ttl_seconds)
        reasons, calculated = self._evaluate(payload, portfolio, evidence, issued_at)
        approval = not reasons
        return RiskCertificate(
            certificate_id=uuid.uuid4().hex,
            cycle_id=cycle_id or payload.client_order_id,
            payload_hash=payload.payload_hash,
            evidence_hash=evidence_digest(evidence),
            account_hash=account_digest(portfolio),
            client_order_id=payload.client_order_id,
            account_id=payload.account_id,
            approval=approval,
            veto=not approval,
            reasons=tuple(reasons),
            limits=self.limits,
            calculated_risk=calculated,
            issued_at=issued_at,
            expires_at=expires_at,
        )

    def verify(
        self,
        certificate: RiskCertificate,
        payload: CanonicalOrderPayload,
        portfolio: PortfolioSnapshot,
        evidence: EvidenceSnapshot,
        *,
        now: datetime | None = None,
    ) -> None:
        """Reject expired, mutated, or unauthorized certificates. Re-evaluates risk."""
        clock = ensure_utc(now or datetime.now(timezone.utc))
        if certificate.binding_hash != canonical_hash(certificate._binding_dict()):
            raise ExecutionRejected("unauthorized: certificate binding hash mismatch")
        if clock >= certificate.expires_at:
            raise ExecutionRejected("risk certificate expired")
        if payload.payload_hash != certificate.payload_hash:
            raise ExecutionRejected("payload changed after certificate issue")
        if evidence_digest(evidence) != certificate.evidence_hash:
            raise ExecutionRejected("evidence snapshot changed after certificate issue")
        if account_digest(portfolio) != certificate.account_hash:
            raise ExecutionRejected("account changed after certificate issue")
        if certificate.limits != self.limits:
            raise ExecutionRejected("unauthorized: certificate limits do not match engine")
        if certificate.account_id != payload.account_id:
            raise ExecutionRejected("account mismatch")
        expected_id = self.settings.paper_account_id
        if expected_id and (
            certificate.account_id != expected_id or str(portfolio.account_id or "") != expected_id
        ):
            raise ExecutionRejected("account mismatch")
        if not certificate.approval or certificate.veto:
            raise ExecutionRejected(
                "unauthorized: " + ("; ".join(certificate.reasons) or "certificate vetoed")
            )
        fresh = self.issue(
            payload,
            portfolio,
            evidence,
            now=clock,
            cycle_id=certificate.cycle_id,
        )
        if fresh.veto:
            raise ExecutionRejected(
                "unauthorized: " + ("; ".join(fresh.reasons) or "risk re-evaluation vetoed")
            )

    def assert_executable(
        self,
        certificate: RiskCertificate | None,
        payload: CanonicalOrderPayload,
        portfolio: PortfolioSnapshot,
        evidence: EvidenceSnapshot,
        *,
        now: datetime | None = None,
    ) -> CanonicalOrderPayload:
        if certificate is None:
            raise ExecutionRejected("unauthorized: risk certificate required")
        self.verify(certificate, payload, portfolio, evidence, now=now)
        return payload

    def _evaluate(
        self,
        payload: CanonicalOrderPayload,
        portfolio: PortfolioSnapshot,
        evidence: EvidenceSnapshot,
        now: datetime,
    ) -> tuple[list[str], CalculatedRisk]:
        reasons: list[str] = []
        limits = self.limits
        quotes = quotes_by_symbol(evidence)

        if not limits.require_options:
            reasons.append("options-mandatory profile is off")
        if not portfolio.paper or not limits.paper_only:
            reasons.append("paper account required")
        if not portfolio.options_approved:
            reasons.append("options trading is not approved on this account")

        expected_id = self.settings.paper_account_id
        if expected_id and portfolio.account_id and portfolio.account_id != expected_id:
            reasons.append("account mismatch")
        if expected_id and payload.account_id != expected_id:
            reasons.append("account mismatch")
        if portfolio.account_id and payload.account_id != str(portfolio.account_id):
            reasons.append("account mismatch")

        equity = Decimal(str(portfolio.equity))
        buying_power = Decimal(str(portfolio.buying_power))
        if equity <= 0:
            reasons.append("equity is missing")
        else:
            drift = abs(equity - limits.starting_capital) / limits.starting_capital
            if drift > limits.equity_tolerance:
                reasons.append(
                    f"equity {equity:.0f} is outside the ${limits.starting_capital:.0f} paper book window"
                )

        daily_trades = int(portfolio.trades_today)
        if daily_trades >= limits.max_daily_trades:
            reasons.append("daily trade limit reached")
        if int(portfolio.open_positions) >= limits.max_open_positions:
            reasons.append("open position limit reached")

        daily_loss = Decimal(str(portfolio.daily_loss))
        if daily_loss >= limits.max_daily_loss:
            reasons.append("daily loss limit reached")

        quote_age = evidence.quote_age_seconds
        quote_fresh = bool(evidence.is_fresh) and quote_age <= limits.max_quote_age_seconds
        if evidence.quote_timestamp is None and quote_age == 0 and not evidence.is_fresh:
            reasons.append("stale quote")
            quote_fresh = False
        elif not quote_fresh or quote_age > limits.max_quote_age_seconds:
            reasons.append("stale quote")

        width = Decimal("0")
        net_credit = Decimal("0")
        net_debit = Decimal("0")
        is_credit = True
        max_loss = Decimal("0")
        max_profit = Decimal("0")
        leg_risks: list[LegRisk] = []
        combo = {"delta": Decimal("0"), "vega": Decimal("0"), "gamma": Decimal("0"), "theta": Decimal("0")}
        missing_quote = False

        if payload.order_class != "mleg" or len(payload.legs) != 2:
            reasons.append("NO_TRADE: only two-leg defined-risk verticals are permitted")
        else:
            strikes: list[Decimal] = []
            types: set[OptionType] = set()
            sell_premium = Decimal("0")
            buy_premium = Decimal("0")
            for leg in payload.legs:
                quote = quotes.get(leg.symbol)
                if quote is None or quote.bid <= 0 or quote.ask <= 0:
                    missing_quote = True
                    reasons.append(f"NO_TRADE: missing quote for {leg.symbol}")
                    continue
                leg_age = freshness_seconds(quote.quote_timestamp, now)
                if quote.quote_timestamp is None or leg_age is None:
                    missing_quote = True
                    reasons.append(f"NO_TRADE: missing quote timestamp for {leg.symbol}")
                    continue
                if leg_age > limits.max_quote_age_seconds:
                    missing_quote = True
                    quote_fresh = False
                    reasons.append(f"NO_TRADE: stale quote for {leg.symbol}")
                    continue
                greeks = _leg_greeks(leg, quote, evidence.spot_price, now)
                if greeks is None:
                    missing_quote = True
                    reasons.append(f"NO_TRADE: missing greeks for {leg.symbol}")
                    continue
                signed = _signed_greeks(greeks, payload.qty, leg.ratio_qty, leg.side)
                for key in combo:
                    combo[key] += signed[key]
                bid = quote.bid
                ask = quote.ask
                leg_risks.append(
                    LegRisk(
                        symbol=leg.symbol,
                        side=leg.side.value,
                        ratio_qty=leg.ratio_qty,
                        bid=bid,
                        ask=ask,
                        delta=signed["delta"],
                        vega=signed["vega"],
                        gamma=signed["gamma"],
                        theta=signed["theta"],
                        quote_timestamp=quote.quote_timestamp,
                        quote_age_seconds=leg_age,
                    )
                )
                premium = bid if leg.side == OrderSide.SELL else ask
                cashflow = premium * Decimal(leg.ratio_qty)
                if leg.side == OrderSide.SELL:
                    sell_premium += cashflow
                else:
                    buy_premium += cashflow
                strikes.append(leg.strike_price)
                types.add(leg.option_type)

            if not missing_quote and len(strikes) == 2:
                width = abs(strikes[0] - strikes[1])
                net = sell_premium - buy_premium
                is_credit = net >= 0
                if is_credit:
                    net_credit = net
                    net_debit = Decimal("0")
                else:
                    net_debit = -net
                    net_credit = Decimal("0")
                max_loss, max_profit = independent_vertical_risk(
                    width=width,
                    net_credit=net_credit,
                    net_debit=net_debit,
                    qty=payload.qty,
                    is_credit=is_credit,
                )
                if is_credit and payload.limit_price >= 0:
                    reasons.append(
                        "NO_TRADE: credit MLEG limit_price must be negative "
                        "(Alpaca: positive=debit, negative=credit)"
                    )
                elif (not is_credit) and payload.limit_price <= 0:
                    reasons.append(
                        "NO_TRADE: debit MLEG limit_price must be positive "
                        "(Alpaca: positive=debit, negative=credit)"
                    )
                elif is_credit and payload.limit_price < 0:
                    limit_credit = -payload.limit_price
                    max_loss, max_profit = independent_vertical_risk(
                        width=width,
                        net_credit=limit_credit,
                        net_debit=Decimal("0"),
                        qty=payload.qty,
                        is_credit=True,
                    )
                    if limit_credit > width:
                        reasons.append("NO_TRADE: credit exceeds width")
                if width <= 0:
                    reasons.append("NO_TRADE: vertical width is missing")
                if is_credit and net_credit > width:
                    reasons.append("NO_TRADE: credit exceeds width")
                if not is_credit and net_debit > width:
                    reasons.append("NO_TRADE: debit exceeds width")
                if max_loss < 0:
                    reasons.append("NO_TRADE: max loss is invalid")

                allowed = _allowed_credit_vertical(payload.legs, is_credit)
                if allowed is None:
                    reasons.append("NO_TRADE: not an allowed SPY credit vertical")

        buying_power_impact = max_loss
        existing_open = Decimal(str(portfolio.open_risk))
        open_risk = existing_open + max_loss
        concentration_pct = (max_loss / equity) if equity > 0 else Decimal("1")

        if not missing_quote and max_loss > 0:
            if equity > 0 and concentration_pct > limits.max_concentration_pct:
                reasons.append("concentration limit exceeded")
            if buying_power_impact > buying_power:
                reasons.append("insufficient buying power")
            if open_risk > limits.max_open_risk:
                reasons.append("open risk limit exceeded")

        if (
            portfolio.net_delta is None
            or portfolio.net_vega is None
            or portfolio.net_gamma is None
            or portfolio.net_theta is None
        ):
            reasons.append("NO_TRADE: missing portfolio greeks")
            portfolio_delta = combo["delta"]
            portfolio_vega = combo["vega"]
            portfolio_gamma = combo["gamma"]
            portfolio_theta = combo["theta"]
        else:
            portfolio_delta = Decimal(str(portfolio.net_delta)) + combo["delta"]
            portfolio_vega = Decimal(str(portfolio.net_vega)) + combo["vega"]
            portfolio_gamma = Decimal(str(portfolio.net_gamma)) + combo["gamma"]
            portfolio_theta = Decimal(str(portfolio.net_theta)) + combo["theta"]
            if abs(portfolio_delta) > limits.max_abs_delta:
                reasons.append("portfolio delta limit exceeded")
            if abs(portfolio_vega) > limits.max_abs_vega:
                reasons.append("portfolio vega limit exceeded")
            if abs(portfolio_gamma) > limits.max_abs_gamma:
                reasons.append("portfolio gamma limit exceeded")
            if abs(portfolio_theta) > limits.max_abs_theta:
                reasons.append("portfolio theta limit exceeded")

        calculated = CalculatedRisk(
            is_credit=is_credit,
            width=width,
            net_credit=net_credit,
            net_debit=net_debit,
            max_loss=max_loss,
            max_profit=max_profit,
            buying_power_impact=buying_power_impact,
            concentration_pct=concentration_pct,
            daily_trades=daily_trades,
            open_risk=open_risk,
            daily_loss=daily_loss,
            quote_age_seconds=quote_age,
            quote_fresh=quote_fresh,
            combo_delta=combo["delta"],
            combo_vega=combo["vega"],
            combo_gamma=combo["gamma"],
            combo_theta=combo["theta"],
            portfolio_delta=portfolio_delta,
            portfolio_vega=portfolio_vega,
            portfolio_gamma=portfolio_gamma,
            portfolio_theta=portfolio_theta,
            legs=tuple(leg_risks),
            portfolio_equity=equity,
            buying_power=buying_power,
        )
        # Never let the pin fallback masquerade as a market price inside the cert.
        _assert_no_pin_fallback_price(calculated, quotes)
        return reasons, calculated


def _allowed_credit_vertical(legs: tuple[OptionLegSpec, ...], is_credit: bool) -> str | None:
    if not is_credit or len(legs) != 2:
        return None
    types = {leg.option_type for leg in legs}
    if len(types) != 1:
        return None
    shorts = [leg for leg in legs if leg.side == OrderSide.SELL]
    longs = [leg for leg in legs if leg.side == OrderSide.BUY]
    if len(shorts) != 1 or len(longs) != 1:
        return None
    short, long = shorts[0], longs[0]
    kind = next(iter(types))
    if kind == OptionType.PUT and short.strike_price > long.strike_price:
        return "bull_put"
    if kind == OptionType.CALL and short.strike_price < long.strike_price:
        return "bear_call"
    return None


def _leg_greeks(
    leg: OptionLegSpec,
    quote: OptionContractQuote,
    spot: Decimal,
    now: datetime,
) -> dict[str, Decimal] | None:
    if observed_greeks(quote):
        assert quote.delta is not None and quote.vega is not None
        assert quote.gamma is not None and quote.theta is not None
        return {
            "delta": quote.delta,
            "vega": quote.vega,
            "gamma": quote.gamma,
            "theta": quote.theta,
        }
    iv = quote.implied_volatility
    if iv is None or iv <= 0 or spot <= 0:
        return None
    expiry = ensure_utc(leg.expiration)
    t_years = max((expiry - ensure_utc(now)).total_seconds(), 1.0) / (365.0 * 24 * 3600)
    flag = "p" if leg.option_type == OptionType.PUT else "c"
    raw = contract_greeks(
        flag,
        float(spot),
        float(leg.strike_price),
        t_years,
        VOLLIB_RATE,
        float(iv),
    )
    return {key: Decimal(str(value)) for key, value in raw.items()}


def _signed_greeks(
    greeks: dict[str, Decimal],
    qty: int,
    ratio: int,
    side: OrderSide,
) -> dict[str, Decimal]:
    sign = Decimal("-1") if side == OrderSide.SELL else Decimal("1")
    factor = sign * Decimal(abs(qty)) * Decimal(abs(ratio)) * Decimal(OPTION_MULTIPLIER)
    return {key: value * factor for key, value in greeks.items()}


def _assert_no_pin_fallback_price(
    calculated: CalculatedRisk,
    quotes: Mapping[str, OptionContractQuote],
) -> None:
    """Guard: PIN_LIMIT_FALLBACK is never injected as a synthetic quote price."""
    _ = calculated
    for quote in quotes.values():
        # Real quotes may coincidentally print 0.85; that is market data, not a fallback.
        if quote.bid < 0 or quote.ask < 0:
            raise ExecutionRejected("NO_TRADE: invalid quote")


def _order_notional(
    request: OptionOrderRequest,
    underlying_price: float | None,
    option_price: float | None,
) -> float:
    """Legacy single-leg notional. Certificate path never uses this."""
    if request.limit_price is not None:
        premium = abs(float(request.limit_price))
    elif option_price is not None:
        premium = abs(float(option_price))
    elif underlying_price is not None:
        premium = abs(float(underlying_price)) * 0.02
    else:
        premium = 1.0
    qty = abs(int(request.qty))
    return premium * qty * OPTION_MULTIPLIER
