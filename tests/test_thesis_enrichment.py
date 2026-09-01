from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from opticycle.protocol import OptionType
from opticycle.thesis import features_to_prompt, summarize_features
from tests.test_thesis_agent import _evidence


def test_thesis_features_include_vol_skew_range_and_nfp() -> None:
    base = _evidence(direction="bullish")
    puts = tuple(
        replace(
            quote,
            implied_volatility=Decimal("0.28") + Decimal(index) / Decimal("100"),
            delta=Decimal("-0.25"),
        )
        for index, quote in enumerate(base.chain_quotes[:2])
    )
    calls = tuple(
        replace(
            quote,
            symbol=quote.symbol.replace("P", "C"),
            option_type=OptionType.CALL,
            implied_volatility=Decimal("0.22") + Decimal(index) / Decimal("100"),
            delta=Decimal("0.25"),
        )
        for index, quote in enumerate(base.chain_quotes[2:])
    )
    enriched = replace(base, chain_quotes=puts + calls)
    features = summarize_features(enriched)
    prompt = features_to_prompt(features)
    assert features.iv_rank is not None
    assert features.iv_rank_scope == "current_chain_cross_section"
    assert features.realized_volatility is not None
    assert features.put_call_skew is not None
    assert features.five_day_range_pct is not None
    assert features.next_event.startswith("US_EMPLOYMENT_SITUATION")
    assert "hours_to_event" in prompt
