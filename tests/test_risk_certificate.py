"""Gate 5: Risk Certificate bound to the exact MLEG order.

Certificate prices come only from real quotes. Missing/stale quotes veto.
The pin 0.85 limit fallback never enters calculated risk.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from opticycle.protocol import (
    CanonicalOrderPayload,
    EvidenceSnapshot,
    OptionContractQuote,
    OptionLegSpec,
    OptionType,
    OrderSide,
    PositionIntent,
)
from opticycle.risk import (
    PIN_LIMIT_FALLBACK,
    PortfolioSnapshot,
    RiskEngine,
    independent_vertical_risk,
)
from opticycle.settings import HackathonSettings
from trade.mcp.alpaca_mcp_executor import AlpacaMcpExecutor, PLACE_OPTION_ORDER
from trade.orders import ExecutionRejected

ACCOUNT_ID = "PA3V84C40PJQ"
EXP = datetime(2026, 9, 18, 20, 0, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]


def _settings() -> HackathonSettings:
    return HackathonSettings()


def _portfolio(**kwargs) -> PortfolioSnapshot:
    base = dict(
        equity=100_000,
        buying_power=100_000,
        cash=100_000,
        account_id=ACCOUNT_ID,
        paper=True,
        options_approved=True,
        trades_today=0,
        open_positions=0,
        net_delta=0.0,
        net_vega=0.0,
        net_gamma=0.0,
        net_theta=0.0,
        daily_loss=0.0,
        open_risk=0.0,
    )
    base.update(kwargs)
    return PortfolioSnapshot(**base)


def _quote(
    symbol: str,
    *,
    option_type: OptionType,
    strike: str,
    bid: str,
    ask: str,
    delta: str = "0",
    vega: str = "0",
    gamma: str = "0",
    theta: str = "0",
) -> OptionContractQuote:
    return OptionContractQuote(
        symbol=symbol,
        underlying="SPY",
        option_type=option_type,
        strike_price=Decimal(strike),
        expiration=EXP,
        bid=Decimal(bid),
        ask=Decimal(ask),
        last=(Decimal(bid) + Decimal(ask)) / Decimal("2"),
        delta=Decimal(delta),
        vega=Decimal(vega),
        gamma=Decimal(gamma),
        theta=Decimal(theta),
    )


def _leg(
    symbol: str,
    *,
    side: OrderSide,
    intent: PositionIntent,
    option_type: OptionType,
    strike: str,
    ratio: int = 1,
) -> OptionLegSpec:
    return OptionLegSpec(
        symbol=symbol,
        ratio_qty=ratio,
        side=side,
        position_intent=intent,
        option_type=option_type,
        strike_price=Decimal(strike),
        expiration=EXP,
    )


def _bull_put_legs() -> tuple[OptionLegSpec, OptionLegSpec]:
    short = _leg(
        "SPY260918P00550000",
        side=OrderSide.SELL,
        intent=PositionIntent.SELL_TO_OPEN,
        option_type=OptionType.PUT,
        strike="550.00",
    )
    long = _leg(
        "SPY260918P00540000",
        side=OrderSide.BUY,
        intent=PositionIntent.BUY_TO_OPEN,
        option_type=OptionType.PUT,
        strike="540.00",
    )
    return short, long


def _bull_put_quotes() -> tuple[OptionContractQuote, OptionContractQuote]:
    # Sell 550 put at bid 2.10; buy 540 put at ask 0.90 → credit 1.20, width 10.
    short = _quote(
        "SPY260918P00550000",
        option_type=OptionType.PUT,
        strike="550.00",
        bid="2.10",
        ask="2.20",
        delta="-0.20",
        vega="0.08",
        gamma="0.01",
        theta="-0.04",
    )
    long = _quote(
        "SPY260918P00540000",
        option_type=OptionType.PUT,
        strike="540.00",
        bid="0.80",
        ask="0.90",
        delta="-0.10",
        vega="0.05",
        gamma="0.008",
        theta="-0.02",
    )
    return short, long


def _bear_call_legs() -> tuple[OptionLegSpec, OptionLegSpec]:
    short = _leg(
        "SPY260918C00560000",
        side=OrderSide.SELL,
        intent=PositionIntent.SELL_TO_OPEN,
        option_type=OptionType.CALL,
        strike="560.00",
    )
    long = _leg(
        "SPY260918C00570000",
        side=OrderSide.BUY,
        intent=PositionIntent.BUY_TO_OPEN,
        option_type=OptionType.CALL,
        strike="570.00",
    )
    return short, long


def _bear_call_quotes() -> tuple[OptionContractQuote, OptionContractQuote]:
    short = _quote(
        "SPY260918C00560000",
        option_type=OptionType.CALL,
        strike="560.00",
        bid="1.80",
        ask="1.90",
        delta="0.18",
        vega="0.07",
        gamma="0.009",
        theta="-0.03",
    )
    long = _quote(
        "SPY260918C00570000",
        option_type=OptionType.CALL,
        strike="570.00",
        bid="0.70",
        ask="0.80",
        delta="0.09",
        vega="0.04",
        gamma="0.006",
        theta="-0.015",
    )
    return short, long


def _debit_call_legs() -> tuple[OptionLegSpec, OptionLegSpec]:
    long = _leg(
        "SPY260918C00550000",
        side=OrderSide.BUY,
        intent=PositionIntent.BUY_TO_OPEN,
        option_type=OptionType.CALL,
        strike="550.00",
    )
    short = _leg(
        "SPY260918C00560000",
        side=OrderSide.SELL,
        intent=PositionIntent.SELL_TO_OPEN,
        option_type=OptionType.CALL,
        strike="560.00",
    )
    return long, short


def _debit_call_quotes() -> tuple[OptionContractQuote, OptionContractQuote]:
    long = _quote(
        "SPY260918C00550000",
        option_type=OptionType.CALL,
        strike="550.00",
        bid="2.90",
        ask="3.00",
        delta="0.40",
        vega="0.11",
        gamma="0.02",
        theta="-0.05",
    )
    short = _quote(
        "SPY260918C00560000",
        option_type=OptionType.CALL,
        strike="560.00",
        bid="1.50",
        ask="1.60",
        delta="0.22",
        vega="0.07",
        gamma="0.012",
        theta="-0.03",
    )
    return long, short


def _payload(
    legs: tuple[OptionLegSpec, ...],
    *,
    qty: int = 1,
    limit_price: Decimal = Decimal("1.20"),
    account_id: str = ACCOUNT_ID,
    client_order_id: str = "cycle-gate5-001",
) -> CanonicalOrderPayload:
    return CanonicalOrderPayload(
        client_order_id=client_order_id,
        account_id=account_id,
        underlying="SPY",
        order_class="mleg",
        order_type="limit",
        time_in_force="day",
        qty=qty,
        limit_price=limit_price,
        legs=legs,
    )


def _evidence(
    quotes: tuple[OptionContractQuote, ...],
    *,
    age: Decimal = Decimal("1"),
    fresh: bool = True,
    spot: Decimal = Decimal("555.00"),
    now: datetime | None = None,
    account_id: str = ACCOUNT_ID,
) -> EvidenceSnapshot:
    return EvidenceSnapshot(
        underlying="SPY",
        spot_price=spot,
        timestamp=now or datetime.now(timezone.utc),
        bars_count=60,
        quote_age_seconds=age,
        is_fresh=fresh,
        chain_quotes=quotes,
        correlation_id="corr-gate5",
        account_id=account_id,
    )


class FakeMcpClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, name: str, arguments: dict) -> dict:
        self.calls.append((name, arguments))
        return {"id": "mcp-cert-1", "status": "accepted", "ok": True}


def test_credit_spread_max_loss_matches_independent_formula() -> None:
    engine = RiskEngine(_settings())
    legs = _bull_put_legs()
    quotes = _bull_put_quotes()
    payload = _payload(legs)
    cert = engine.issue(payload, _portfolio(), _evidence(quotes))
    risk = cert.calculated_risk

    # Independent: sell bid 2.10 − buy ask 0.90 = 1.20 credit; width 10; qty 1.
    expected_credit = Decimal("1.20")
    expected_width = Decimal("10.00")
    expected_loss, expected_profit = independent_vertical_risk(
        width=expected_width,
        net_credit=expected_credit,
        net_debit=Decimal("0"),
        qty=1,
        is_credit=True,
    )
    assert expected_loss == Decimal("880.00")
    assert expected_profit == Decimal("120.00")
    assert risk.net_credit == expected_credit
    assert risk.net_debit == Decimal("0")
    assert risk.width == expected_width
    assert risk.max_loss == expected_loss
    assert risk.max_profit == expected_profit
    assert risk.is_credit is True
    assert cert.approval is True
    assert cert.veto is False


def test_debit_spread_max_loss_matches_independent_formula_and_is_vetoed() -> None:
    engine = RiskEngine(_settings())
    legs = _debit_call_legs()
    quotes = _debit_call_quotes()
    payload = _payload(legs, limit_price=Decimal("1.50"))
    cert = engine.issue(payload, _portfolio(), _evidence(quotes))
    risk = cert.calculated_risk

    # Independent: buy ask 3.00 − sell bid 1.50 = 1.50 debit; width 10.
    expected_debit = Decimal("1.50")
    expected_width = Decimal("10.00")
    expected_loss, expected_profit = independent_vertical_risk(
        width=expected_width,
        net_credit=Decimal("0"),
        net_debit=expected_debit,
        qty=1,
        is_credit=False,
    )
    assert expected_loss == Decimal("150.00")
    assert expected_profit == Decimal("850.00")
    assert risk.net_debit == expected_debit
    assert risk.net_credit == Decimal("0")
    assert risk.max_loss == expected_loss
    assert risk.max_profit == expected_profit
    assert risk.is_credit is False
    assert cert.veto is True
    assert any("credit vertical" in reason for reason in cert.reasons)


def test_expired_certificate_is_rejected() -> None:
    engine = RiskEngine(_settings())
    now = datetime.now(timezone.utc)
    payload = _payload(_bull_put_legs())
    evidence = _evidence(_bull_put_quotes(), now=now)
    cert = engine.issue(payload, _portfolio(), evidence, now=now)
    with pytest.raises(ExecutionRejected, match="expired"):
        engine.verify(cert, payload, _portfolio(), evidence, now=now + timedelta(seconds=61))


def test_snapshot_change_is_rejected() -> None:
    engine = RiskEngine(_settings())
    payload = _payload(_bull_put_legs())
    original_quotes = _bull_put_quotes()
    evidence = _evidence(original_quotes)
    cert = engine.issue(payload, _portfolio(), evidence)
    shifted = _quote(
        "SPY260918P00550000",
        option_type=OptionType.PUT,
        strike="550.00",
        bid="2.50",
        ask="2.60",
        delta="-0.20",
        vega="0.08",
        gamma="0.01",
        theta="-0.04",
    )
    changed = _evidence((shifted, original_quotes[1]))
    with pytest.raises(ExecutionRejected, match="snapshot changed"):
        engine.verify(cert, payload, _portfolio(), changed)


def test_payload_change_is_rejected() -> None:
    engine = RiskEngine(_settings())
    payload = _payload(_bull_put_legs(), qty=1)
    evidence = _evidence(_bull_put_quotes())
    portfolio = _portfolio()
    cert = engine.issue(payload, portfolio, evidence)
    changed = _payload(_bull_put_legs(), qty=2)
    with pytest.raises(ExecutionRejected, match="payload changed"):
        engine.verify(cert, changed, portfolio, evidence)


def test_account_change_is_rejected() -> None:
    engine = RiskEngine(_settings())
    payload = _payload(_bull_put_legs())
    evidence = _evidence(_bull_put_quotes())
    portfolio = _portfolio(equity=100_000)
    cert = engine.issue(payload, portfolio, evidence)
    changed = _portfolio(equity=90_000)
    with pytest.raises(ExecutionRejected, match="account changed"):
        engine.verify(cert, payload, changed, evidence)


def test_executor_rejects_leg_qty_or_limit_change_after_issue() -> None:
    engine = RiskEngine(_settings())
    legs = _bull_put_legs()
    payload = _payload(legs, qty=1, limit_price=Decimal("1.20"))
    evidence = _evidence(_bull_put_quotes())
    portfolio = _portfolio()
    cert = engine.issue(payload, portfolio, evidence)
    assert cert.approval is True
    client = FakeMcpClient()
    executor = AlpacaMcpExecutor(client=client, dry_run=False)

    qty_changed = _payload(legs, qty=2, limit_price=Decimal("1.20"))
    with pytest.raises(ExecutionRejected, match="payload changed"):
        executor.place_certified_order_sync(qty_changed, cert, portfolio, evidence, settings=_settings())

    limit_changed = _payload(legs, qty=1, limit_price=Decimal("1.55"))
    with pytest.raises(ExecutionRejected, match="payload changed"):
        executor.place_certified_order_sync(limit_changed, cert, portfolio, evidence, settings=_settings())

    mutated_legs = (
        legs[0],
        _leg(
            "SPY260918P00535000",
            side=OrderSide.BUY,
            intent=PositionIntent.BUY_TO_OPEN,
            option_type=OptionType.PUT,
            strike="535.00",
        ),
    )
    # The mutated long leg has no quote either; payload hash change is enough.
    with pytest.raises(ExecutionRejected, match="payload changed"):
        executor.place_certified_order_sync(
            _payload(mutated_legs, qty=1, limit_price=Decimal("1.20")),
            cert,
            portfolio,
            evidence,
            settings=_settings(),
        )
    assert client.calls == []

    executor.place_certified_order_sync(payload, cert, portfolio, evidence, settings=_settings())
    assert client.calls[0][0] == PLACE_OPTION_ORDER
    assert client.calls[0][1]["qty"] == "1"
    assert client.calls[0][1]["limit_price"] == "1.20"
    assert len(client.calls[0][1]["legs"]) == 2


def test_buying_power_veto() -> None:
    engine = RiskEngine(_settings())
    cert = engine.issue(
        _payload(_bull_put_legs()),
        _portfolio(buying_power=100),
        _evidence(_bull_put_quotes()),
    )
    assert cert.veto is True
    assert any("buying power" in reason for reason in cert.reasons)
    assert cert.calculated_risk.buying_power_impact == Decimal("880.00")


def test_concentration_veto() -> None:
    engine = RiskEngine(_settings())
    cert = engine.issue(
        _payload(_bull_put_legs()),
        _portfolio(equity=5_000, buying_power=5_000, cash=5_000),
        _evidence(_bull_put_quotes()),
    )
    assert cert.veto is True
    assert any("concentration" in reason for reason in cert.reasons)


def test_combo_and_portfolio_greeks() -> None:
    engine = RiskEngine(_settings())
    cert = engine.issue(
        _payload(_bull_put_legs()),
        _portfolio(net_delta=5.0, net_vega=1.0, net_gamma=0.5, net_theta=-1.0),
        _evidence(_bull_put_quotes()),
    )
    risk = cert.calculated_risk
    # Short put: sell * 100 * (-0.20) = +20 delta; long put: buy * 100 * (-0.10) = -10.
    assert risk.combo_delta == Decimal("10.00")
    assert risk.combo_vega == Decimal("-3.00")  # sell 0.08*-100 + buy 0.05*100 = -8+5
    assert risk.combo_gamma == Decimal("-0.20")  # sell 0.01*-100 + buy 0.008*100
    assert risk.combo_theta == Decimal("2.00")  # sell -0.04*-100 + buy -0.02*100 = 4-2
    assert risk.portfolio_delta == Decimal("15.00")
    assert risk.portfolio_vega == Decimal("-2.00")
    assert len(risk.legs) == 2
    assert {leg.symbol for leg in risk.legs} == {
        "SPY260918P00550000",
        "SPY260918P00540000",
    }


def test_daily_loss_veto() -> None:
    engine = RiskEngine(_settings())
    cert = engine.issue(
        _payload(_bull_put_legs()),
        _portfolio(daily_loss=2_000),
        _evidence(_bull_put_quotes()),
    )
    assert cert.veto is True
    assert any("daily loss" in reason for reason in cert.reasons)
    assert cert.calculated_risk.daily_loss == Decimal("2000.00")


def test_stale_quote_veto() -> None:
    engine = RiskEngine(_settings())
    cert = engine.issue(
        _payload(_bull_put_legs()),
        _portfolio(),
        _evidence(_bull_put_quotes(), age=Decimal("500"), fresh=False),
    )
    assert cert.veto is True
    assert any("stale quote" in reason for reason in cert.reasons)
    assert cert.calculated_risk.quote_fresh is False


def test_missing_quote_vetoes_without_using_pin_fallback() -> None:
    engine = RiskEngine(_settings())
    # Only the short leg is quoted; the long ask/bid are absent from evidence.
    short_only = (_bull_put_quotes()[0],)
    cert = engine.issue(
        _payload(_bull_put_legs(), limit_price=PIN_LIMIT_FALLBACK),
        _portfolio(),
        _evidence(short_only),
    )
    assert cert.veto is True
    assert any("missing quote" in reason for reason in cert.reasons)
    assert cert.calculated_risk.net_credit != PIN_LIMIT_FALLBACK
    assert cert.calculated_risk.net_debit != PIN_LIMIT_FALLBACK
    assert cert.calculated_risk.max_loss != PIN_LIMIT_FALLBACK * Decimal("100")
    prices = {
        cert.calculated_risk.net_credit,
        cert.calculated_risk.net_debit,
        cert.calculated_risk.max_loss,
        cert.calculated_risk.max_profit,
    }
    assert PIN_LIMIT_FALLBACK not in prices


def test_certificate_prices_come_from_quotes_not_limit_fallback() -> None:
    engine = RiskEngine(_settings())
    payload = _payload(_bull_put_legs(), limit_price=PIN_LIMIT_FALLBACK)
    cert = engine.issue(payload, _portfolio(), _evidence(_bull_put_quotes()))
    risk = cert.calculated_risk
    assert risk.net_credit == Decimal("1.20")
    assert risk.max_loss == Decimal("880.00")
    assert PIN_LIMIT_FALLBACK not in {risk.net_credit, risk.net_debit, risk.width}
    for leg in risk.legs:
        assert leg.bid != PIN_LIMIT_FALLBACK
        assert leg.ask != PIN_LIMIT_FALLBACK
    assert cert.approval is True


def test_account_mismatch_veto() -> None:
    engine = RiskEngine(_settings())
    cert = engine.issue(
        _payload(_bull_put_legs(), account_id=ACCOUNT_ID),
        _portfolio(account_id="PA9999999999"),
        _evidence(_bull_put_quotes()),
    )
    assert cert.veto is True
    assert any("account mismatch" in reason for reason in cert.reasons)


def test_unauthorized_missing_or_vetoed_certificate_cannot_execute() -> None:
    engine = RiskEngine(_settings())
    payload = _payload(_bull_put_legs())
    evidence = _evidence(_bull_put_quotes())
    portfolio = _portfolio()
    client = FakeMcpClient()
    executor = AlpacaMcpExecutor(client=client, dry_run=False)
    with pytest.raises(ExecutionRejected, match="unauthorized"):
        executor.place_certified_order_sync(payload, None, portfolio, evidence, settings=_settings())

    vetoed = engine.issue(
        payload,
        _portfolio(daily_loss=5_000),
        evidence,
    )
    assert vetoed.veto is True
    with pytest.raises(ExecutionRejected, match="unauthorized"):
        executor.place_certified_order_sync(payload, vetoed, _portfolio(daily_loss=5_000), evidence, settings=_settings())
    assert client.calls == []


def test_same_limits_for_replay_live_and_demo() -> None:
    engine = RiskEngine(_settings())
    replay = engine.limits_for("replay")
    live = engine.limits_for("live")
    demo = engine.limits_for("demo")
    aggressive = engine.limits_for("aggressive")
    assert replay == live == demo == aggressive
    assert replay.max_daily_loss == Decimal("2000.00")
    assert replay.max_open_risk == Decimal("8000.00")
    assert replay.max_quote_age_seconds == Decimal("120")


def test_no_aggressive_mode_or_second_pnl_config() -> None:
    settings_src = (ROOT / "src" / "opticycle" / "settings.py").read_text(encoding="utf-8")
    risk_src = (ROOT / "src" / "opticycle" / "risk.py").read_text(encoding="utf-8")
    runner_src = (ROOT / "src" / "opticycle" / "runner.py").read_text(encoding="utf-8")
    assert "aggressive" not in settings_src.lower()
    assert "aggressive" not in runner_src.lower()
    assert "apply_aggressive_settings" not in risk_src
    assert "pnl_mode" not in risk_src.lower()
    assert "bypass" not in risk_src.lower()
    assert "aggressive" not in risk_src.lower()
    assert risk_src.count("DAILY_LOSS_FRACTION") == 2


def test_llm_cannot_modify_certificate() -> None:
    engine = RiskEngine(_settings())
    cert = engine.issue(_payload(_bull_put_legs()), _portfolio(), _evidence(_bull_put_quotes()))
    with pytest.raises(FrozenInstanceError):
        cert.approval = False  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        cert.veto = True  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        cert.payload_hash = "0" * 64  # type: ignore[misc]
    with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
        cert.calculated_risk.max_loss = Decimal("1")  # type: ignore[misc]


def test_pin_option_hardcoded_limit_is_gone() -> None:
    text = (ROOT / "src" / "opticycle" / "pin_option.py").read_text(encoding="utf-8")
    assert "0.85" not in text
    assert "else 0.85" not in text
    assert "missing market-derived limit price" in text


def test_bear_call_credit_formula_and_approval() -> None:
    engine = RiskEngine(_settings())
    cert = engine.issue(
        _payload(_bear_call_legs(), limit_price=Decimal("1.00")),
        _portfolio(),
        _evidence(_bear_call_quotes()),
    )
    # Sell bid 1.80 − buy ask 0.80 = 1.00 credit; width 10.
    expected_loss, expected_profit = independent_vertical_risk(
        width=Decimal("10.00"),
        net_credit=Decimal("1.00"),
        net_debit=Decimal("0"),
        qty=1,
        is_credit=True,
    )
    assert cert.calculated_risk.net_credit == Decimal("1.00")
    assert cert.calculated_risk.max_loss == expected_loss == Decimal("900.00")
    assert cert.calculated_risk.max_profit == expected_profit == Decimal("100.00")
    assert cert.approval is True


def test_certificate_binds_required_hashes_and_times() -> None:
    engine = RiskEngine(_settings())
    now = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
    payload = _payload(_bull_put_legs())
    evidence = _evidence(_bull_put_quotes(), now=now)
    portfolio = _portfolio()
    cert = engine.issue(payload, portfolio, evidence, now=now, cycle_id="cycle-bind")
    assert cert.payload_hash == payload.payload_hash
    assert len(cert.evidence_hash) == 64
    assert len(cert.account_hash) == 64
    assert len(cert.binding_hash) == 64
    assert cert.limits == engine.limits
    assert cert.issued_at == now
    assert cert.expires_at == now + timedelta(seconds=60)
    assert cert.approval is True
    assert cert.veto is False
    engine.verify(cert, payload, portfolio, evidence, now=now + timedelta(seconds=1))
