"""Gate 4: constrained ThesisAgent episodes and fail-closed live LLM requirement."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from opticycle.journal import TradeJournal
from opticycle.observe import observe_live
from opticycle.protocol import (
    OCC_SYMBOL_RE,
    EvidenceSnapshot,
    OptionContractQuote,
    OptionType,
    ThesisReasonCode,
    ThesisStance,
)
from opticycle.runner import run_once
from opticycle.settings import HackathonSettings
from opticycle.thesis import (
    STANCE_CREDIT_TYPE,
    ThesisAgent,
    features_to_prompt,
    persist_thesis_episode,
    summarize_features,
    validate_thesis_output,
)
from tests.test_live_observation import _PartialClient, _account


class ScriptedLlm:
    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = list(payloads)
        self.calls: list[str] = []

    def complete(self, prompt: str) -> dict:
        self.calls.append(prompt)
        if not self.payloads:
            return {"stance": "invalid"}
        return self.payloads.pop(0)


def _quote(symbol: str, strike: str) -> OptionContractQuote:
    return OptionContractQuote(
        symbol=symbol,
        underlying="SPY",
        option_type=OptionType.PUT,
        strike_price=Decimal(strike),
        expiration=datetime(2026, 9, 18, 20, 0, tzinfo=timezone.utc),
        bid=Decimal("1.20"),
        ask=Decimal("1.40"),
        last=Decimal("1.30"),
        delta=Decimal("-0.20"),
        quote_timestamp=datetime.now(timezone.utc),
    )


def _closes(start: str, end: str, count: int = 40) -> tuple[Decimal, ...]:
    first = Decimal(start)
    last = Decimal(end)
    if count <= 1:
        return (first,) * max(count, 0)
    step = (last - first) / Decimal(count - 1)
    return tuple(first + step * i for i in range(count))


def _evidence(
    *,
    bars: int = 40,
    quotes: int = 4,
    fresh: bool = True,
    direction: str = "bullish",
    quote_timestamp: datetime | None | object = ...,
    bid: Decimal | None = Decimal("560.20"),
    ask: Decimal | None = Decimal("560.30"),
    last: Decimal | None = Decimal("560.25"),
    quote_age: Decimal = Decimal("1.5"),
) -> EvidenceSnapshot:
    now = datetime.now(timezone.utc)
    chain = (
        _quote("SPY260918P00550000", "550"),
        _quote("SPY260918P00540000", "540"),
        _quote("SPY260918P00530000", "530"),
        _quote("SPY260918P00520000", "520"),
    )[:quotes]
    if direction == "bearish":
        closes = _closes("560.00", "548.00", bars)
    elif direction == "flat":
        closes = _closes("560.00", "560.05", bars)
    else:
        closes = _closes("548.00", "560.00", bars)
    ts: datetime | None
    if quote_timestamp is ...:
        ts = now
    else:
        ts = quote_timestamp  # type: ignore[assignment]
    return EvidenceSnapshot(
        underlying="SPY",
        spot_price=Decimal("560.25"),
        timestamp=now,
        bars_count=bars,
        quote_age_seconds=quote_age,
        is_fresh=fresh,
        chain_quotes=chain,
        indicators=(("clock_open", Decimal("1")),),
        correlation_id="cycle-thesis-001",
        bid=bid,
        ask=ask,
        last=last,
        quote_timestamp=ts,
        bar_closes=closes[:bars],
    )


def _valid_payload(features, stance: str = "BULLISH") -> dict:
    citations = [
        item
        for item in features.evidence_refs
        if item.startswith(("bar_return=", "bar_trend=", "underlying_", "quote_timestamp="))
    ]
    if not citations:
        citations = list(features.evidence_refs[:3])
    return {
        "stance": stance,
        "confidence": "0.82",
        "evidence": citations,
        "assumptions": ["session trend remains intact"],
        "invalidation_conditions": ["quote_timestamp missing or stale", "bar_trend flattens"],
        "observation_timestamp": features.observation_timestamp.isoformat(),
        "reason_code": "TREND_ALIGNED",
    }


def test_feature_summary_has_no_occ_qty_or_price_selection() -> None:
    evidence = _evidence()
    features = summarize_features(evidence)
    prompt = features_to_prompt(features)
    assert OCC_SYMBOL_RE.search(prompt) is None
    assert "qty" not in prompt
    assert "limit_price" not in prompt
    assert "SPY260918" not in prompt
    assert features.chain_count == 4
    assert features.evidence_refs
    assert features.implied_stance == ThesisStance.BULLISH
    assert any(item.startswith("underlying_last=") for item in features.evidence_refs)
    assert any(item.startswith("bar_return=") for item in features.evidence_refs)
    assert features.bound_credit_type == "bull_put"


def test_bullish_thesis_episode_maps_evidence_and_invalidation(tmp_path: Path) -> None:
    evidence = _evidence()
    features = summarize_features(evidence)
    agent = ThesisAgent(ScriptedLlm([_valid_payload(features, "BULLISH")]))
    thesis = agent.evaluate(evidence)
    assert thesis.stance == ThesisStance.BULLISH
    assert thesis.accepted is True
    assert thesis.model_called is True
    assert set(thesis.evidence) <= set(features.evidence_refs)
    assert thesis.invalidation_conditions
    assert thesis.observation_timestamp == evidence.timestamp
    episode = persist_thesis_episode(TradeJournal(tmp_path / "journal.jsonl"), evidence, thesis)
    assert episode.thesis is not None
    assert episode.decision.action.value == "BULLISH"
    lines = (tmp_path / "journal.jsonl").read_text(encoding="utf-8").strip().splitlines()
    payload = json.loads(lines[-1])
    assert payload["event"] == "thesis"
    assert payload["stance"] == "BULLISH"
    assert payload["invalidation_conditions"]
    assert payload["evidence"]
    assert payload["bound_credit_type"] == "bull_put"
    assert thesis.bound_credit_type == STANCE_CREDIT_TYPE[ThesisStance.BULLISH]
    assert any("=" in item for item in thesis.evidence)


def test_no_trade_insufficient_evidence_episode(tmp_path: Path) -> None:
    evidence = _evidence(bars=2, quotes=1)
    thesis = ThesisAgent(ScriptedLlm([{"stance": "BULLISH"}])).evaluate(evidence)
    assert thesis.stance == ThesisStance.NO_TRADE
    assert thesis.reason_code == ThesisReasonCode.INSUFFICIENT_EVIDENCE.value
    assert thesis.model_called is False
    assert thesis.invalidation_conditions
    assert set(thesis.evidence) <= set(summarize_features(evidence).evidence_refs)
    episode = persist_thesis_episode(TradeJournal(tmp_path / "journal.jsonl"), evidence, thesis)
    assert episode.decision.action.value == "NO_TRADE"
    payload = json.loads((tmp_path / "journal.jsonl").read_text(encoding="utf-8").strip().splitlines()[-1])
    assert payload["reason_code"] == "INSUFFICIENT_EVIDENCE"


def test_invalid_llm_output_rejected_by_validator(tmp_path: Path) -> None:
    evidence = _evidence()
    invalid = {
        "stance": "BUY",
        "symbol": "SPY260918P00550000",
        "qty": 1,
        "limit_price": 1.25,
    }
    llm = ScriptedLlm([invalid, invalid, invalid])
    thesis = ThesisAgent(llm).evaluate(evidence)
    assert thesis.accepted is False
    assert thesis.stance == ThesisStance.NO_TRADE
    assert thesis.reason_code in {
        ThesisReasonCode.INVALID_OUTPUT.value,
        ThesisReasonCode.SCHEMA_ERROR.value,
    }
    assert thesis.model_called is True
    assert thesis.regenerations == 2
    assert len(llm.calls) == 3
    features = summarize_features(evidence)
    record, reason = validate_thesis_output(invalid, features)
    assert record is None
    assert reason == ThesisReasonCode.INVALID_OUTPUT.value
    episode = persist_thesis_episode(TradeJournal(tmp_path / "journal.jsonl"), evidence, thesis)
    assert episode.terminal_state.value == "halted"
    payload = json.loads((tmp_path / "journal.jsonl").read_text(encoding="utf-8").strip().splitlines()[-1])
    assert payload["accepted"] is False
    assert payload["invalidation_conditions"]


def test_llm_disabled_blocks_live_trading(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("HACKATHON_LLM_API_KEY", raising=False)
    now = datetime.now(timezone.utc)
    bars = [
        type("Bar", (), {"open": 499, "high": 501, "low": 498, "close": 500, "volume": 1_000_000, "timestamp": now})()
        for _ in range(20)
    ]
    chain_snap = type(
        "Snap",
        (),
        {
            "latest_quote": type("Q", (), {"bid_price": 1.2, "ask_price": 1.4})(),
            "latest_trade": type("T", (), {"price": 1.3})(),
            "greeks": type("G", (), {"delta": -0.2, "gamma": 0.01, "theta": -0.05, "vega": 0.1})(),
        },
    )()
    observer = _PartialClient(
        account=_account(),
        quote={"SPY": type("Quote", (), {"bid_price": 500.0, "ask_price": 500.2, "timestamp": now})()},
        bars={"SPY": bars},
        chain={"SPY260918P00500000": chain_snap, "SPY260918P00490000": chain_snap},
    )
    journal = TradeJournal(tmp_path / "journal.jsonl")
    result = run_once(HackathonSettings(), dry_run=False, observer=observer, journal=journal)
    assert result["ok"] is False
    assert result["order"] is None
    assert result["outcome"] == "HALT"
    assert "model" in result["reason"].lower() or "LLM" in result["reason"]
    text = (tmp_path / "journal.jsonl").read_text(encoding="utf-8")
    assert "BULLISH" not in text
    assert "place_option_order" not in text


def test_live_observe_quote_without_timestamp_is_no_trade() -> None:
    result = observe_live(
        HackathonSettings(),
        client=_PartialClient(
            account=_account(),
            quote={"SPY": type("Quote", (), {"bid_price": 500.0, "ask_price": 500.2})()},
        ),
    )
    assert result.outcome.value == "NO_TRADE"
    assert result.evidence is None
    assert "timestamp" in result.reason


def test_empty_or_missing_features_is_no_trade() -> None:
    empty = _evidence(bars=0, quotes=0, bid=None, ask=None, last=None, quote_timestamp=None, quote_age=Decimal("0"))
    thesis = ThesisAgent().evaluate(empty)
    assert thesis.stance == ThesisStance.NO_TRADE
    assert thesis.accepted is False
    assert thesis.reason_code == ThesisReasonCode.STALE_DATA.value
    assert "freshness 0" in thesis.detail or "timestamp" in thesis.detail
    thin = _evidence(bars=2, quotes=1)
    thin_thesis = ThesisAgent().evaluate(thin)
    assert thin_thesis.stance == ThesisStance.NO_TRADE
    assert thin_thesis.reason_code == ThesisReasonCode.INSUFFICIENT_EVIDENCE.value
    flat = _evidence(direction="flat")
    flat_features = summarize_features(flat)
    assert flat_features.implied_stance == ThesisStance.NO_TRADE
    flat_thesis = ThesisAgent().evaluate(flat)
    assert flat_thesis.stance == ThesisStance.NO_TRADE
    assert flat_thesis.accepted is False
    assert flat_thesis.reason_code == ThesisReasonCode.LLM_DISABLED.value


def test_bullish_fixture_matches_stance_and_citations() -> None:
    evidence = _evidence(direction="bullish")
    features = summarize_features(evidence)
    thesis = ThesisAgent(ScriptedLlm([_valid_payload(features, "BULLISH")])).evaluate(evidence)
    assert thesis.stance == ThesisStance.BULLISH
    assert thesis.accepted is True
    assert thesis.model_called is True
    assert thesis.bound_credit_type == "bull_put"
    names = {item.split("=", 1)[0] for item in thesis.evidence}
    assert {"underlying_last", "underlying_bid", "underlying_ask", "quote_timestamp", "bar_return", "bar_trend"} <= names
    assert any(item.startswith("bar_trend=up") for item in thesis.evidence)
    assert any("=" in item for item in thesis.evidence)


def test_bearish_fixture_matches_stance_and_citations() -> None:
    evidence = _evidence(direction="bearish")
    features = summarize_features(evidence)
    thesis = ThesisAgent(ScriptedLlm([_valid_payload(features, "BEARISH")])).evaluate(evidence)
    assert thesis.stance == ThesisStance.BEARISH
    assert thesis.accepted is True
    assert thesis.model_called is True
    assert thesis.bound_credit_type == "bear_call"
    assert any(item.startswith("bar_trend=down") for item in thesis.evidence)
    assert any(item.startswith("bar_return=") for item in thesis.evidence)
    assert any(item.startswith("underlying_bid=") for item in thesis.evidence)


def test_cannot_emit_bullish_or_bearish_without_citations() -> None:
    features = summarize_features(_evidence(direction="bullish"))
    empty = _valid_payload(features, "BULLISH")
    empty["evidence"] = []
    record, reason = validate_thesis_output(empty, features)
    assert record is None
    assert reason == ThesisReasonCode.EMPTY_DIRECTION.value
    with pytest.raises(ValueError, match="cite real snapshot features"):
        from opticycle.protocol import ThesisRecord

        ThesisRecord(
            stance=ThesisStance.BULLISH,
            confidence=Decimal("0.9"),
            evidence=(),
            assumptions=(),
            invalidation_conditions=("x",),
            observation_timestamp=features.observation_timestamp,
            reason_code="TREND_ALIGNED",
            feature_correlation_id="x",
            model_called=False,
        )
    llm = ScriptedLlm([empty, empty, empty])
    thesis = ThesisAgent(llm).evaluate(_evidence(direction="bullish"))
    assert thesis.stance == ThesisStance.NO_TRADE
    assert thesis.accepted is False


def test_missing_quote_timestamp_is_fail_closed_not_freshness_zero() -> None:
    evidence = _evidence(
        direction="bullish",
        quote_timestamp=None,
        quote_age=Decimal("0"),
        fresh=True,
    )
    thesis = ThesisAgent().evaluate(evidence)
    assert thesis.stance == ThesisStance.NO_TRADE
    assert thesis.reason_code == ThesisReasonCode.STALE_DATA.value
    features = summarize_features(evidence)
    assert features.quote_timestamp_present is False
    assert features.is_fresh is False
    assert features.implied_stance == ThesisStance.NO_TRADE


def test_model_output_is_stance_even_if_it_disagrees_with_implied_stance() -> None:
    evidence = _evidence(direction="bullish")
    features = summarize_features(evidence)
    assert features.implied_stance == ThesisStance.BULLISH
    prompt = features_to_prompt(features)
    assert "implied_stance" in prompt
    assert "evidence_only_not_the_answer" in prompt
    payload = _valid_payload(features, "BEARISH")
    record, reason = validate_thesis_output(payload, features)
    assert record is not None
    assert record.stance == ThesisStance.BEARISH
    assert reason != ThesisReasonCode.EVIDENCE_CONFLICT.value
    thesis = ThesisAgent(ScriptedLlm([payload])).evaluate(evidence)
    assert thesis.stance == ThesisStance.BEARISH
    assert thesis.accepted is True
    assert thesis.model_called is True
    assert thesis.bound_credit_type == "bear_call"


def test_no_llm_key_is_fail_closed_not_silent_deterministic_ai() -> None:
    evidence = _evidence(direction="bullish")
    features = summarize_features(evidence)
    assert features.implied_stance == ThesisStance.BULLISH
    thesis = ThesisAgent().evaluate(evidence)
    assert thesis.stance == ThesisStance.NO_TRADE
    assert thesis.accepted is False
    assert thesis.model_called is False
    assert thesis.reason_code == ThesisReasonCode.LLM_DISABLED.value
    assert thesis.bound_credit_type == ""
