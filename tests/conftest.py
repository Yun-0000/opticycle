from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
VENDOR = ROOT / "vendor" / "pin-31374551"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def inject_dry_run_market(monkeypatch: pytest.MonkeyPatch):
    """Dry-run tests receive synthetic market from tests/fixtures only."""
    from opticycle import runner as runner_mod
    from tests.fixtures.market import make_pin_market

    original = runner_mod.run_once

    def wrapped(*args, **kwargs):
        dry_run = kwargs.get("dry_run", True)
        if dry_run and kwargs.get("market") is None:
            kwargs["market"] = make_pin_market()
        return original(*args, **kwargs)

    monkeypatch.setattr(runner_mod, "run_once", wrapped)
    return make_pin_market
