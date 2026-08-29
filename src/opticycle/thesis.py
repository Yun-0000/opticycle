"""Constrained ThesisAgent: BULLISH / BEARISH / NO_TRADE from summarized evidence.

The model never receives or emits OCC symbols, quantity, or order prices.
Live execution requires a real model call. There is no pretend-AI path.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime
from decimal import Decimal, InvalidOperation
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
)

MIN_CONFIDENCE = Decimal("0.60")
MIN_BARS = 20
MIN_CHAIN = 2
MAX_REGENERATIONS = 2
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


class ThesisDisabled(RuntimeError):
    """Raised when live trading is attempted without a real model client."""


class LlmClient(Protocol):
    def complete(self, prompt: str) -> dict[str, Any]:
        """Return a parsed JSON object from a real model call."""


class OpenAiThesisClient:
    """Official OpenAI Chat Completions client. Never fabricates a thesis."""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        if not api_key.strip():
            raise ThesisDisabled("OPENAI_API_KEY is required for a real model call")
        self.api_key = api_key
        self.model = model

    @classmethod
    def from_env(cls) -> "OpenAiThesisClient":
        key = (os.environ.get("OPENAI_API_KEY") or os.environ.get("HACKATHON_LLM_API_KEY") or "").strip()
        if not key:
            raise ThesisDisabled("LLM disabled: missing OPENAI_API_KEY")
        model = (os.environ.get("HACKATHON_LLM_MODEL") or "gpt-4o-mini").strip()
        return cls(api_key=key, model=model)

    def complete(self, prompt: str) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are Opticycle ThesisAgent. Reply with JSON only. "
                        "stance must be BULLISH, BEARISH, or NO_TRADE. "
                        "Do not choose OCC symbols, quantity, or prices."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        }
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
            with urllib.request.urlopen(request, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise ThesisDisabled(f"real model call failed: {type(exc).__name__}") from exc
        content = body["choices"][0]["message"]["content"]
        loaded = json.loads(content)
        if not isinstance(loaded, dict):
            raise ValueError("model output is not a JSON object")
        return loaded


def summarize_features(evidence: EvidenceSnapshot) -> FeatureSummary:
    clock_open: bool | None = None
    trend_bucket = "unknown"
    for name, value in evidence.indicators:
        if name == "clock_open":
            clock_open = value > 0
        if name == "trend_bucket":
            trend_bucket = str(value)
    if evidence.bars_count >= MIN_BARS:
        if trend_bucket == "unknown":
            trend_bucket = "history_present"
    else:
        trend_bucket = "history_thin"
    bucket_floor = (int(evidence.spot_price) // 5) * 5
    refs = ["quote_fresh", "bars_count", "chain_count", "spot_bucket", "trend_bucket"]
    if clock_open is not None:
        refs.append("clock_open")
    return FeatureSummary(
        underlying=evidence.underlying,
        observation_timestamp=evidence.timestamp,
        correlation_id=evidence.correlation_id,
        quote_age_seconds=evidence.quote_age_seconds,
        is_fresh=evidence.is_fresh,
        bars_count=evidence.bars_count,
        chain_count=len(evidence.chain_quotes),
        spot_bucket=f"spot_bucket_{bucket_floor}",
        trend_bucket=trend_bucket,
        clock_open=clock_open,
        evidence_refs=tuple(refs),
    )


def features_to_prompt(features: FeatureSummary) -> str:
    payload = {
        "underlying": features.underlying,
        "observation_timestamp": features.observation_timestamp.isoformat(),
        "correlation_id": features.correlation_id,
        "quote_age_seconds": str(features.quote_age_seconds),
        "is_fresh": features.is_fresh,
        "bars_count": features.bars_count,
        "chain_count": features.chain_count,
        "spot_bucket": features.spot_bucket,
        "trend_bucket": features.trend_bucket,
        "clock_open": features.clock_open,
        "evidence_refs": list(features.evidence_refs),
        "required_output_fields": [
            "stance",
            "confidence",
            "evidence",
            "assumptions",
            "invalidation_conditions",
            "observation_timestamp",
            "reason_code",
        ],
        "allowed_stances": ["BULLISH", "BEARISH", "NO_TRADE"],
    }
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
    if any(field not in raw for field in required):
        return None, ThesisReasonCode.SCHEMA_ERROR.value
    try:
        stance = ThesisStance(str(raw["stance"]).strip().upper())
    except ValueError:
        return None, ThesisReasonCode.SCHEMA_ERROR.value
    try:
        confidence = Decimal(str(raw["confidence"]))
    except (InvalidOperation, ValueError):
        return None, ThesisReasonCode.SCHEMA_ERROR.value
    if confidence < Decimal("0") or confidence > Decimal("1"):
        return None, ThesisReasonCode.SCHEMA_ERROR.value
    if confidence < MIN_CONFIDENCE and stance != ThesisStance.NO_TRADE:
        return None, ThesisReasonCode.LOW_CONFIDENCE.value
    evidence_refs = _as_tuple(raw["evidence"])
    if not evidence_refs:
        return None, ThesisReasonCode.SCHEMA_ERROR.value
    if any(item not in features.evidence_refs for item in evidence_refs):
        return None, ThesisReasonCode.EVIDENCE_CONFLICT.value
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
    if not features.is_fresh and stance != ThesisStance.NO_TRADE:
        return None, ThesisReasonCode.STALE_DATA.value
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
    )


class ThesisAgent:
    def __init__(self, client: LlmClient | None = None) -> None:
        self.client = client

    def evaluate(self, evidence: EvidenceSnapshot) -> ThesisRecord:
        features = summarize_features(evidence)
        if not evidence.is_fresh or evidence.quote_age_seconds < 0:
            return _closed_thesis(features, reason_code=ThesisReasonCode.STALE_DATA, model_called=False)
        if evidence.bars_count < MIN_BARS or len(evidence.chain_quotes) < MIN_CHAIN:
            return _closed_thesis(
                features,
                reason_code=ThesisReasonCode.INSUFFICIENT_EVIDENCE,
                model_called=False,
                detail="bars or chain too thin for a directional thesis",
            )
        if self.client is None:
            return _closed_thesis(
                features,
                reason_code=ThesisReasonCode.LLM_DISABLED,
                model_called=False,
                detail="live path requires a real model call",
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
        },
    )
    return episode


def require_live_llm(client: LlmClient | None) -> LlmClient:
    if client is not None:
        return client
    return OpenAiThesisClient.from_env()
