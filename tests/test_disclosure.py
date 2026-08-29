from __future__ import annotations

from pathlib import Path

FORBIDDEN = (
    "GaussWorldTrader",
    "Gauss World Trader",
    "Magica-Chen",
    "Magica Chen",
    "github.com/Magica",
    "inspired by",
    "based on",
    "forked from",
)


def test_public_docs_do_not_name_upstream_project() -> None:
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "README.md",
        root / "docs" / "SUBMISSION_WRITEUP.md",
        root / "docs" / "ALPACA_ACCOUNT.md",
        root / "THIRD_PARTY_NOTICES.md",
        root / ".env.example",
        root / "PLAN.md",
        root / ".hackathon" / "candidate-report.md",
    ]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        lower = text.lower()
        for token in FORBIDDEN:
            assert token.lower() not in lower, f"{path} contains {token!r}"
