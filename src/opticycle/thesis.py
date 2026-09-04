"""Constrained ThesisAgent: BULLISH / BEARISH / NO_TRADE from summarized evidence.

Determined signals (implied_stance, bar_trend) may enter the prompt as evidence.
They are not the answer. The model chooses the stance. Disagreement is valid.
No LLM key is fail-closed NO_TRADE — never a silent deterministic direction labeled AI.
The model never receives or emits OCC symbols, quantity, or order prices.
"""

from __future__ import annotations

import json
import math
import os
import statistics
import re
import urllib.error
import urllib.request
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol

from opticycle.journal import TradeJournal
from opticycle.protocol import (
    OCC_SYMBOL_RE,
    DecisionEpisode,
    DecisionRecord,
    EvidenceSnapshot,
    ExecutionStatus,
    FeatureSummary,
    StrategyKind,
    ThesisAction,
    ThesisReasonCode,
    ThesisRecord,
    ThesisStance,
    ensure_utc,
    format_decimal,
)
from opticycle.risk import MAX_QUOTE_AGE_SECONDS

MIN_CONFIDENCE = Decimal("0.60")
MIN_BARS = 20
MIN_CHAIN = 2
MIN_ABS_BAR_RETURN = Decimal("0.002")
MAX_REGENERATIONS = 2
STANCE_CREDIT_TYPE = {
    ThesisStance.BULLISH: "bull_put",
    ThesisStance.BEARISH: "bear_call",
}
FORBIDDEN_DEBIT_TYPES = frozenset({"bull_call", "bear_put"})
FORBIDDEN_OUTPUT_KEYS = frozenset(
    {
        "symbol",
        "symbols",
        "occ",
        "qty",
        "quantity",
        "limit",
        "limit_price",
        "price",
        "legs",
        "order_class",
        "client_order_id",
        "strike",
        "strikes",
    }
)
ALLOWED_REASON_CODES = {item.value for item in ThesisReasonCode}
DIRECTIONAL_CITATION_NAMES = ("bar_return", "bar_trend")


class ThesisDisabled(RuntimeError):
    """Raised when live trading is attempted without a real model client."""


class LlmClient(Protocol):
    def complete(self, prompt: str) -> dict[str, Any]:
        """Return a parsed JSON object from a real model call."""


DEFAULT_LLM_MODEL = "gpt-5.6-luna"
LLM_LAST_PATH = Path("data/llm_last.json")


def _dump_llm_last(payload: dict[str, Any]) -> None:
    """Gitignored debug dump of the last model reply. Never includes the API key."""
    try:
        path = LLM_LAST_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    except OSError:
        return


def llm_omits_temperature(model: str) -> bool:
    """GPT-5.6 (and later GPT-5) chat models only accept the default temperature."""
    name = (model or "").strip().lower()
    return name.startswith("gpt-5") or name.startswith("o1") or name.startswith("o3") or name.startswith("o4")


def chat_completion_payload(model: str, prompt: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are Opticycle ThesisAgent. Reply with JSON only. "
                    "Choose stance from pre-validated evidence: BULLISH, BEARISH, or NO_TRADE. "
                    "implied_stance is evidence, not the required answer; disagreement is allowed. "
                    "Do not choose OCC symbols, quantity, or prices."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    }
    if not llm_omits_temperature(model):
        payload["temperature"] = 0
    return payload


class OpenAiThesisClient:
    """Official OpenAI Chat Completions client. Never fabricates a thesis."""

    def __init__(self, api_key: str, model: str = DEFAULT_LLM_MODEL) -> None:
        if not api_key.strip():
            raise ThesisDisabled("OPENAI_API_KEY is required for a real model call")
        self.api_key = api_key
        self.model = model

    @classmethod
    def from_env(cls) -> "OpenAiThesisClient":
        key = (os.environ.get("OPENAI_API_KEY") or os.environ.get("HACKATHON_LLM_API_KEY") or "").strip()
        if not key:
            raise ThesisDisabled("LLM disabled: missing OPENAI_API_KEY")
        model = (os.environ.get("HACKATHON_LLM_MODEL") or DEFAULT_LLM_MODEL).strip()
        return cls(api_key=key, model=model)

    def complete(self, prompt: str) -> dict[str, Any]:
        payload = chat_completion_payload(self.model, prompt)
        request = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            _dump_llm_last({"model": self.model, "error": type(exc).__name__})
            raise ThesisDisabled(f"real model call failed: {type(exc).__name__}") from exc
        content = body["choices"][0]["message"].get("content") or ""
        if not str(content).strip():
            _dump_llm_last({"model": self.model, "error": "empty_content"})
            raise ThesisDisabled("real model call returned empty content")
        try:
            loaded = json.loads(content)
        except json.JSONDecodeError as exc:
            _dump_llm_last({"model": self.model, "error": "json_decode", "content": str(content)[:4000]})
            raise ThesisDisabled(f"real model call returned non-JSON: {type(exc).__name__}") from exc
        if not isinstance(loaded, dict):
            _dump_llm_last({"model": self.model, "error": "not_object", "content": str(content)[:4000]})
            raise ValueError("model output is not a JSON object")
        _dump_llm_last({"model": self.model, "parsed": loaded})
        return loaded


def _cite(name: str, value: str) -> str:
    return f"{name}={value}"


def _citation_name(item: str) -> str:
    return item.split("=", 1)[0]


def summarize_features(evidence: EvidenceSnapshot) -> FeatureSummary:
    """Read real snapshot fields only. Never invent IV, Greeks, or a quote timestamp."""

    clock_open: bool | None = None
    for name, value in evidence.indicators:
        if name == "clock_open":
            clock_open = value > 0
    cited: list[str] = []
    missing: list[str] = []

    last = evidence.last if evidence.last is not None and evidence.last > 0 else None
    bid = evidence.bid if evidence.bid is not None and evidence.bid > 0 else None
    ask = evidence.ask if evidence.ask is not None and evidence.ask > 0 else None
    if last is None:
        missing.append("underlying_last")
    else:
        cited.append(_cite("underlying_last", format_decimal(last, 4)))
    if bid is None:
        missing.append("underlying_bid")
    else:
        cited.append(_cite("underlying_bid", format_decimal(bid, 4)))
    if ask is None:
        missing.append("underlying_ask")
    else:
        cited.append(_cite("underlying_ask", format_decimal(ask, 4)))

    quote_ts = evidence.quote_timestamp
    if quote_ts is None:
        missing.append("quote_timestamp")
    else:
        cited.append(_cite("quote_timestamp", ensure_utc(quote_ts).isoformat()))
        cited.append(_cite("quote_age_seconds", format_decimal(evidence.quote_age_seconds, 3)))

    closes = tuple(close for close in evidence.bar_closes if close > 0)
    bar_return: Decimal | None = None
    realized_volatility: Decimal | None = None
    five_day_range_pct: Decimal | None = None
    trend_bucket = "unknown"
    if len(closes) < MIN_BARS:
        missing.append("bar_closes")
    elif closes[0] <= 0:
        missing.append("bar_closes")
    else:
        bar_return = (closes[-1] - closes[0]) / closes[0]
        cited.append(_cite("bar_return", format_decimal(bar_return, 6)))
        cited.append(_cite("bars_count", str(len(closes))))
        if bar_return > MIN_ABS_BAR_RETURN:
            trend_bucket = "up"
        elif bar_return < -MIN_ABS_BAR_RETURN:
            trend_bucket = "down"
        else:
            trend_bucket = "flat"
        cited.append(_cite("bar_trend", trend_bucket))
        if len(closes) >= 5:
            last_five = closes[-5:]
            five_day_range_pct = (max(last_five) - min(last_five)) / closes[-1]
            cited.append(_cite("five_day_range_pct", format_decimal(five_day_range_pct, 6)))
        if len(closes) >= 21:
            returns = [
                float((closes[index] - closes[index - 1]) / closes[index - 1])
                for index in range(max(1, len(closes) - 20), len(closes))
                if closes[index - 1] > 0
            ]
            if len(returns) >= 2:
                realized_volatility = Decimal(
                    str(statistics.stdev(returns) * math.sqrt(252))
                )
                cited.append(
                    _cite("realized_volatility_20d", format_decimal(realized_volatility, 6))
                )

    chain_count = len(evidence.chain_quotes)
    cited.append(_cite("chain_count", str(chain_count)))
    if chain_count < MIN_CHAIN:
        missing.append("option_chain")

    timed_chain = [quote for quote in evidence.chain_quotes if quote.quote_timestamp is not None]
    timed_bids = [quote.bid for quote in timed_chain if quote.bid > 0]
    if timed_bids:
        cited.append(_cite("chain_credit_available", format_decimal(max(timed_bids), 4)))

    iv_quotes = [
        quote
        for quote in evidence.chain_quotes
        if quote.implied_volatility is not None and quote.implied_volatility > 0
    ]
    iv_rank: Decimal | None = None
    iv_rank_scope = ""
    put_call_skew: Decimal | None = None
    if iv_quotes:
        atm = min(iv_quotes, key=lambda quote: abs(quote.strike_price - evidence.spot_price))
        ivs = [quote.implied_volatility for quote in iv_quotes if quote.implied_volatility is not None]
        low, high = min(ivs), max(ivs)
        iv_rank = Decimal("0.5") if high == low else (atm.implied_volatility - low) / (high - low)
        iv_rank_scope = "current_chain_cross_section"
        cited.append(_cite("iv_rank", format_decimal(iv_rank, 6)))
        cited.append(_cite("iv_rank_scope", iv_rank_scope))
        puts = [
            quote.implied_volatility
            for quote in iv_quotes
            if quote.option_type.value == "put"
            and quote.delta is not None
            and Decimal("0.20") <= abs(quote.delta) <= Decimal("0.30")
        ]
        calls = [
            quote.implied_volatility
            for quote in iv_quotes
            if quote.option_type.value == "call"
            and quote.delta is not None
            and Decimal("0.20") <= abs(quote.delta) <= Decimal("0.30")
        ]
        if puts and calls:
            put_call_skew = Decimal(str(statistics.median(puts))) - Decimal(
                str(statistics.median(calls))
            )
            cited.append(_cite("put_call_skew_25d", format_decimal(put_call_skew, 6)))

    nfp = datetime.fromisoformat("2026-09-04T08:30:00-04:00")
    hours_to_event = Decimal(str((nfp - ensure_utc(evidence.timestamp).astimezone(nfp.tzinfo)).total_seconds() / 3600))
    next_event = "US_EMPLOYMENT_SITUATION_2026-09-04T08:30:00-04:00"
    cited.append(_cite("next_event", next_event))
    cited.append(_cite("hours_to_event", format_decimal(hours_to_event, 3)))

    if clock_open is not None:
        cited.append(_cite("clock_open", "true" if clock_open else "false"))

    stale = (not evidence.is_fresh) or evidence.quote_age_seconds < 0
    if quote_ts is not None and evidence.quote_age_seconds > MAX_QUOTE_AGE_SECONDS:
        stale = True
    if quote_ts is None:
        stale = True

    implied = ThesisStance.NO_TRADE
    bound = ""
    if not missing and not stale and trend_bucket == "up":
        implied = ThesisStance.BULLISH
        bound = STANCE_CREDIT_TYPE[implied]
    elif not missing and not stale and trend_bucket == "down":
        implied = ThesisStance.BEARISH
        bound = STANCE_CREDIT_TYPE[implied]

    cited.append(_cite("is_fresh", "true" if bool(evidence.is_fresh) and not stale else "false"))
    cited.append(_cite("implied_stance", implied.value))
    cited.append(_cite("bound_credit_type", bound or "none"))

    spot_for_bucket = last or evidence.spot_price
    bucket_floor = (int(spot_for_bucket) // 5) * 5
    return FeatureSummary(
        underlying=evidence.underlying,
        observation_timestamp=evidence.timestamp,
        correlation_id=evidence.correlation_id,
        quote_age_seconds=evidence.quote_age_seconds,
        is_fresh=bool(evidence.is_fresh) and quote_ts is not None and not stale,
        bars_count=len(closes) if closes else evidence.bars_count,
        chain_count=chain_count,
        spot_bucket=f"spot_bucket_{bucket_floor}",
        trend_bucket=trend_bucket,
        clock_open=clock_open,
        evidence_refs=tuple(cited),
        implied_stance=implied,
        missing_features=tuple(missing),
        quote_timestamp_present=quote_ts is not None,
        bar_return=bar_return,
        bound_credit_type=bound,
        iv_rank=iv_rank,
        iv_rank_scope=iv_rank_scope,
        realized_volatility=realized_volatility,
        put_call_skew=put_call_skew,
        five_day_range_pct=five_day_range_pct,
        next_event=next_event,
        hours_to_event=hours_to_event,
    )


def features_to_prompt(features: FeatureSummary, *, validation_feedback: str = "") -> str:
    directional = [
        item
        for item in features.evidence_refs
        if _citation_name(item) in DIRECTIONAL_CITATION_NAMES
    ]
    payload = {
        "underlying": features.underlying,
        "observation_timestamp": features.observation_timestamp.isoformat(),
        "correlation_id": features.correlation_id,
        "quote_age_seconds": str(features.quote_age_seconds),
        "is_fresh": features.is_fresh,
        "bars_count": features.bars_count,
        "chain_count": features.chain_count,
        "spot_bucket": features.spot_bucket,
        "bar_trend": features.trend_bucket,
        "bar_return": str(features.bar_return) if features.bar_return is not None else None,
        "clock_open": features.clock_open,
        "implied_stance": features.implied_stance.value,
        "implied_stance_role": "evidence_only_not_the_answer",
        "bound_credit_type": features.bound_credit_type,
        "iv_rank": str(features.iv_rank) if features.iv_rank is not None else None,
        "iv_rank_scope": features.iv_rank_scope or None,
        "realized_volatility_20d": (
            str(features.realized_volatility) if features.realized_volatility is not None else None
        ),
        "put_call_skew_25d": str(features.put_call_skew) if features.put_call_skew is not None else None,
        "five_day_range_pct": (
            str(features.five_day_range_pct) if features.five_day_range_pct is not None else None
        ),
        "next_event": features.next_event,
        "hours_to_event": str(features.hours_to_event) if features.hours_to_event is not None else None,
        "cited_features": list(features.evidence_refs),
        "required_directional_citations": directional,
        "missing_features": list(features.missing_features),
        "required_output_fields": [
            "stance",
            "confidence",
            "evidence",
            "assumptions",
            "invalidation_conditions",
            "observation_timestamp",
            "reason_code",
        ],
        "allowed_reason_codes": sorted(ALLOWED_REASON_CODES),
        "reason_code_rule": (
            "For BULLISH or BEARISH use TREND_ALIGNED. "
            "For NO_TRADE use INSUFFICIENT_EVIDENCE or STALE_DATA."
        ),
        "confidence_rule": "confidence is a decimal in [0, 1], never a percent",
        "timestamp_rule": "copy observation_timestamp from this payload exactly",
        "allowed_stances": ["BULLISH", "BEARISH", "NO_TRADE"],
        "choice_rule": (
            "You choose BULLISH, BEARISH, or NO_TRADE from cited_features. "
            "implied_stance is a determined signal in the evidence, not the required answer. "
            "Disagreement is a valid choice, not an automatic conflict."
        ),
        "credit_binding": (
            "Bind after you choose: BULLISH=bull_put credit; BEARISH=bear_call credit; debit disabled"
        ),
        "citation_rule": (
            "Set evidence to a JSON list of exact strings copied verbatim from cited_features. "
            "For BULLISH or BEARISH include every string in required_directional_citations. "
            "Do not paraphrase, add commentary, or invent a name=value pair."
        ),
        "citation_example": {"evidence": directional},
    }
    if validation_feedback:
        payload["validation_feedback"] = (
            f"Previous output failed deterministic validation: {validation_feedback}. "
            "Return a fresh full JSON object and follow citation_rule exactly."
        )
    text = json.dumps(payload, sort_keys=True)
    if OCC_SYMBOL_RE.search(text):
        raise ValueError("feature prompt must not include OCC symbols")
    return text


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    return (str(value),)


def _contains_occ(value: Any) -> bool:
    if isinstance(value, str):
        return bool(OCC_SYMBOL_RE.search(value))
    if isinstance(value, (list, tuple, dict)):
        return any(_contains_occ(item) for item in (value.values() if isinstance(value, dict) else value))
    return False


def _canonicalize_evidence_refs(
    raw_refs: tuple[str, ...], features: FeatureSummary
) -> tuple[str, ...] | None:
    """Bind name-only model citations to the exact observed name=value strings."""
    allowed = tuple(features.evidence_refs)
    exact = set(allowed)
    by_name = {_citation_name(item): item for item in allowed}
    canonical: list[str] = []
    for raw in raw_refs:
        item = str(raw).strip().strip("`")
        if item in exact:
            resolved = item
        elif "=" not in item and item in by_name:
            resolved = by_name[item]
        else:
            name, separator, value = item.partition("=")
            candidate = f"{name.strip()}={value.strip()}" if separator else ""
            if candidate not in exact:
                return None
            resolved = candidate
        if resolved not in canonical:
            canonical.append(resolved)
    return tuple(canonical)


def validate_thesis_output(
    raw: Any,
    features: FeatureSummary,
) -> tuple[ThesisRecord | None, str]:
    if not isinstance(raw, dict):
        return None, ThesisReasonCode.SCHEMA_ERROR.value
    lowered = {str(key).lower() for key in raw}
    if lowered & FORBIDDEN_OUTPUT_KEYS:
        return None, ThesisReasonCode.INVALID_OUTPUT.value
    if _contains_occ(raw):
        return None, ThesisReasonCode.INVALID_OUTPUT.value
    required = (
        "stance",
        "confidence",
        "evidence",
        "assumptions",
        "invalidation_conditions",
        "observation_timestamp",
        "reason_code",
    )
    if any(field not in raw for field in required if field != "stance"):
        return None, ThesisReasonCode.SCHEMA_ERROR.value
    if "stance" not in raw or not str(raw.get("stance") or "").strip():
        return None, ThesisReasonCode.EMPTY_DIRECTION.value
    try:
        raw_stance = str(raw.get("stance") or "").strip().upper()
        if not raw_stance:
            return None, ThesisReasonCode.EMPTY_DIRECTION.value
        stance = ThesisStance(raw_stance)
    except ValueError:
        return None, ThesisReasonCode.EMPTY_DIRECTION.value
    try:
        confidence = Decimal(str(raw["confidence"]))
    except (InvalidOperation, ValueError):
        return None, ThesisReasonCode.SCHEMA_ERROR.value
    if confidence < Decimal("0") or confidence > Decimal("1"):
        return None, ThesisReasonCode.SCHEMA_ERROR.value
    if confidence < MIN_CONFIDENCE and stance != ThesisStance.NO_TRADE:
        return None, ThesisReasonCode.LOW_CONFIDENCE.value
    raw_evidence_refs = _as_tuple(raw["evidence"])
    evidence_refs = _canonicalize_evidence_refs(raw_evidence_refs, features)
    if evidence_refs is None:
        return None, ThesisReasonCode.EVIDENCE_CONFLICT.value
    if stance in {ThesisStance.BULLISH, ThesisStance.BEARISH} and not evidence_refs:
        return None, ThesisReasonCode.EMPTY_DIRECTION.value
    allowed = set(features.evidence_refs)
    if stance in {ThesisStance.BULLISH, ThesisStance.BEARISH}:
        if any(item not in allowed for item in evidence_refs):
            return None, ThesisReasonCode.EVIDENCE_CONFLICT.value
        cited_names = {_citation_name(item) for item in evidence_refs}
        if "bar_return" not in cited_names or "bar_trend" not in cited_names:
            return None, ThesisReasonCode.EVIDENCE_CONFLICT.value
        if features.bound_credit_type in FORBIDDEN_DEBIT_TYPES:
            return None, ThesisReasonCode.INVALID_OUTPUT.value
    elif evidence_refs and any(item not in allowed for item in evidence_refs):
        return None, ThesisReasonCode.EVIDENCE_CONFLICT.value
    if not evidence_refs and stance == ThesisStance.NO_TRADE:
        evidence_refs = features.evidence_refs
    assumptions = _as_tuple(raw["assumptions"])
    invalidation = _as_tuple(raw["invalidation_conditions"])
    if stance != ThesisStance.NO_TRADE and not invalidation:
        return None, ThesisReasonCode.SCHEMA_ERROR.value
    reason_code = str(raw["reason_code"]).strip().upper()
    if reason_code not in ALLOWED_REASON_CODES:
        return None, ThesisReasonCode.SCHEMA_ERROR.value
    try:
        ts = datetime.fromisoformat(str(raw["observation_timestamp"]).replace("Z", "+00:00"))
    except ValueError:
        return None, ThesisReasonCode.SCHEMA_ERROR.value
    if ensure_utc(ts) != ensure_utc(features.observation_timestamp):
        return None, ThesisReasonCode.EVIDENCE_CONFLICT.value
    if (not features.is_fresh or not features.quote_timestamp_present) and stance != ThesisStance.NO_TRADE:
        return None, ThesisReasonCode.STALE_DATA.value
    bound = STANCE_CREDIT_TYPE.get(stance, "") if stance != ThesisStance.NO_TRADE else ""
    if bound in FORBIDDEN_DEBIT_TYPES:
        return None, ThesisReasonCode.INVALID_OUTPUT.value
    return (
        ThesisRecord(
            stance=stance,
            confidence=confidence,
            evidence=evidence_refs,
            assumptions=assumptions,
            invalidation_conditions=invalidation,
            observation_timestamp=features.observation_timestamp,
            reason_code=reason_code,
            feature_correlation_id=features.correlation_id,
            model_called=True,
            accepted=True,
            bound_credit_type=bound,
        ),
        reason_code,
    )


def _closed_thesis(
    features: FeatureSummary,
    *,
    reason_code: ThesisReasonCode,
    model_called: bool,
    regenerations: int = 0,
    detail: str = "",
) -> ThesisRecord:
    return ThesisRecord(
        stance=ThesisStance.NO_TRADE,
        confidence=Decimal("0"),
        evidence=features.evidence_refs,
        assumptions=("fail-closed ThesisAgent",),
        invalidation_conditions=(
            "insufficient or invalid evidence; do not open a SPY vertical",
        ),
        observation_timestamp=features.observation_timestamp,
        reason_code=reason_code.value,
        feature_correlation_id=features.correlation_id,
        model_called=model_called,
        regenerations=regenerations,
        accepted=False,
        detail=detail,
        bound_credit_type="",
    )


class ThesisAgent:
    def __init__(self, client: LlmClient | None = None) -> None:
        self.client = client

    def evaluate(self, evidence: EvidenceSnapshot) -> ThesisRecord:
        features = summarize_features(evidence)
        if not features.quote_timestamp_present:
            return _closed_thesis(
                features,
                reason_code=ThesisReasonCode.STALE_DATA,
                model_called=False,
                detail="quote timestamp missing; fail-closed (not freshness 0)",
            )
        if not features.is_fresh or evidence.quote_age_seconds < 0:
            return _closed_thesis(features, reason_code=ThesisReasonCode.STALE_DATA, model_called=False)
        if features.missing_features:
            return _closed_thesis(
                features,
                reason_code=ThesisReasonCode.INSUFFICIENT_EVIDENCE,
                model_called=False,
                detail="insufficient snapshot features",
            )
        if self.client is None:
            return _closed_thesis(
                features,
                reason_code=ThesisReasonCode.LLM_DISABLED,
                model_called=False,
                detail="no LLM key; fail-closed — not a silent deterministic BULLISH/BEARISH labeled as AI",
            )
        prompt = features_to_prompt(features)
        last_reason = ThesisReasonCode.SCHEMA_ERROR.value
        regenerations = 0
        for attempt in range(1 + MAX_REGENERATIONS):
            try:
                raw = self.client.complete(prompt)
            except Exception as exc:
                last_reason = ThesisReasonCode.SCHEMA_ERROR.value
                if attempt == MAX_REGENERATIONS:
                    return _closed_thesis(
                        features,
                        reason_code=ThesisReasonCode.SCHEMA_ERROR,
                        model_called=True,
                        regenerations=regenerations,
                        detail=type(exc).__name__,
                    )
                regenerations += 1
                continue
            record, reason = validate_thesis_output(raw, features)
            if record is not None:
                object.__setattr__(record, "regenerations", regenerations)
                return record
            last_reason = reason
            if attempt == MAX_REGENERATIONS:
                break
            regenerations += 1
            prompt = features_to_prompt(features, validation_feedback=reason)
        code = ThesisReasonCode(last_reason) if last_reason in ALLOWED_REASON_CODES else ThesisReasonCode.INVALID_OUTPUT
        return _closed_thesis(
            features,
            reason_code=code,
            model_called=True,
            regenerations=regenerations,
            detail="deterministic validator rejected model output",
        )


def persist_thesis_episode(
    journal: TradeJournal,
    evidence: EvidenceSnapshot,
    thesis: ThesisRecord,
) -> DecisionEpisode:
    action = {
        ThesisStance.BULLISH: ThesisAction.BULLISH,
        ThesisStance.BEARISH: ThesisAction.BEARISH,
        ThesisStance.NO_TRADE: ThesisAction.NO_TRADE,
    }[thesis.stance]
    decision = DecisionRecord(
        cycle_id=evidence.correlation_id or "thesis",
        underlying=evidence.underlying,
        action=action,
        strategy=StrategyKind.VERTICAL_SPREAD,
        timestamp=thesis.observation_timestamp,
        reason=f"{thesis.reason_code}: {thesis.detail or thesis.stance.value}",
        confidence=thesis.confidence,
    )
    episode = DecisionEpisode(
        cycle_id=decision.cycle_id,
        underlying=evidence.underlying,
        started_at=evidence.timestamp,
        finished_at=thesis.observation_timestamp,
        evidence=evidence,
        decision=decision,
        thesis=thesis,
        terminal_state=(
            ExecutionStatus.PENDING
            if thesis.accepted and thesis.stance != ThesisStance.NO_TRADE
            else ExecutionStatus.HALTED
        ),
    )
    journal.record(
        "thesis",
        {
            "stance": thesis.stance.value,
            "confidence": str(thesis.confidence),
            "evidence": list(thesis.evidence),
            "assumptions": list(thesis.assumptions),
            "invalidation_conditions": list(thesis.invalidation_conditions),
            "observation_timestamp": thesis.observation_timestamp.isoformat(),
            "reason_code": thesis.reason_code,
            "feature_correlation_id": thesis.feature_correlation_id,
            "model_called": thesis.model_called,
            "regenerations": thesis.regenerations,
            "accepted": thesis.accepted,
            "action": action.value,
            "bound_credit_type": thesis.bound_credit_type,
        },
    )
    return episode


def require_live_llm(client: LlmClient | None) -> LlmClient:
    if client is not None:
        return client
    return OpenAiThesisClient.from_env()
