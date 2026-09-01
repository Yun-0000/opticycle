from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_DISCLOSURE = (
    "Gauss World Trader",
    "https://github.com/Magica-Chen/GaussWorldTrader",
    "31374551bae6fd34a0fe56fe11d208f4ff04fbb4",
    "vendor/pin-31374551/",
)


def test_foundation_and_notices_disclose_upstream() -> None:
    foundation = (ROOT / "FOUNDATION.md").read_text(encoding="utf-8")
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for token in REQUIRED_DISCLOSURE:
        assert token in foundation, f"FOUNDATION.md missing {token!r}"
        assert token in notices, f"THIRD_PARTY_NOTICES.md missing {token!r}"
    assert "FOUNDATION.md" in readme
    assert "Reuse scope" in foundation or "reuse scope" in foundation.lower()
    assert "Pinned baseline" in notices or "reuse scope" in notices.lower()
