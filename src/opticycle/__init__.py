"""Opticycle — autonomous options paper trader."""

from __future__ import annotations

from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[1]
_VENDOR = _ROOT.parent / "vendor" / "pin-31374551"
if _VENDOR.is_dir() and str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

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
