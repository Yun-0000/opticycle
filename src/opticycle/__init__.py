"""Opticycle — autonomous options paper trader."""

from __future__ import annotations

from .protocol import (
    BrokerReceipt,
    CanonicalOrderPayload,
    DecisionEpisode,
    DecisionRecord,
    EvidenceSnapshot,
    ExecutionAttempt,
    ExecutionChannel,
    ExecutionStatus,
    OptionCandidate,
    OptionContractQuote,
    OptionLegSpec,
    OptionType,
    OrderSide,
    PositionIntent,
    ReconciliationReport,
    ReconciliationStatus,
    FieldComparison,
    CalculatedRisk,
    RiskCertificate,
    RiskLimits,
    SpreadType,
    StrategyKind,
    ThesisAction,
)

__all__ = [
    "BrokerReceipt",
    "CanonicalOrderPayload",
    "DecisionEpisode",
    "DecisionRecord",
    "EvidenceSnapshot",
    "ExecutionAttempt",
    "ExecutionChannel",
    "ExecutionStatus",
    "OptionCandidate",
    "OptionContractQuote",
    "OptionLegSpec",
    "OptionType",
    "OrderSide",
    "PositionIntent",
    "ReconciliationReport",
    "ReconciliationStatus",
    "FieldComparison",
    "CalculatedRisk",
    "RiskCertificate",
    "RiskLimits",
    "SpreadType",
    "StrategyKind",
    "ThesisAction",
]

__version__ = "0.1.0"
