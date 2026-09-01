"""W3: public claim SHAs must resolve on this PR; ghost fc974f1 is gone."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from opticycle.evidence_public import MANIFEST_PATH, NO_TRADE_JSONL, PAGE_PATH, PUBLIC_JSONL, load_public_records
from opticycle.ledger import COMMIT_SHA_RE, parse_claim

ROOT = Path(__file__).resolve().parents[1]
GHOST = "fc974f1ae3119fd9d8207cd23468ca79f864f6f2"
GHOST_PREFIX = "fc974f1"
CLAIMS_JSON = ROOT / "artifacts" / "evidence" / "claims.json"
FORBIDDEN_LIVE_CLIENT = "oc-204a8dfccffd40c9"


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(ROOT),
        check=False,
        capture_output=True,
        text=True,
    )


def _assert_sha_resolves_on_this_pr(sha: str) -> None:
    assert COMMIT_SHA_RE.fullmatch(sha), sha
    typed = _git("cat-file", "-t", sha)
    assert typed.returncode == 0, typed.stderr
    assert typed.stdout.strip() == "commit"
    ancestor = _git("merge-base", "--is-ancestor", sha, "HEAD")
    assert ancestor.returncode == 0, f"{sha} is not an ancestor of HEAD on this PR"


def test_every_public_claim_commit_sha_resolves_on_this_pr() -> None:
    records = load_public_records()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    shas: set[str] = set()
    for row in records:
        sha = str(row.get("commit_sha") or "")
        _assert_sha_resolves_on_this_pr(sha)
        shas.add(sha)
        parsed = parse_claim(str(row["claim"]))
        assert parsed["commit_sha"] == sha
    for claim, mapped in manifest["claims"].items():
        sha = str(mapped["commit_sha"])
        _assert_sha_resolves_on_this_pr(sha)
        shas.add(sha)
        assert parse_claim(claim)["commit_sha"] == sha
    claims = json.loads(CLAIMS_JSON.read_text(encoding="utf-8"))
    for claim, mapped in claims.items():
        sha = str(mapped["commit_sha"])
        _assert_sha_resolves_on_this_pr(sha)
        shas.add(sha)
    assert shas


def test_ghost_fc974f1_is_gone_from_public_artifacts() -> None:
    for path in (PUBLIC_JSONL, MANIFEST_PATH, PAGE_PATH, CLAIMS_JSON, NO_TRADE_JSONL):
        text = path.read_text(encoding="utf-8")
        assert GHOST not in text, path
        assert GHOST_PREFIX not in text, path


def test_public_completion_is_two_live_matched_fills() -> None:
    from opticycle.evidence_public import is_live_fill_row, is_live_matched_fill
    from opticycle.live_matched_fills import LIVE_MATCHED_CLIENT_IDS
    from opticycle.broker_lookup import SIGNED_CLIENT_ORDER_ID

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    html = PAGE_PATH.read_text(encoding="utf-8")
    public = PUBLIC_JSONL.read_text(encoding="utf-8")
    assert manifest["live_fill_claimed"] is True
    assert manifest["matched_claimed"] is True
    assert "replay/fixture" not in html
    assert "not public completion" not in html
    assert "Do not invent MATCHED" not in html
    assert not manifest.get("incomplete_live")
    for client_id in set(LIVE_MATCHED_CLIENT_IDS) | {SIGNED_CLIENT_ORDER_ID}:
        assert client_id in public
        assert client_id in html
    live = [row for row in load_public_records() if is_live_matched_fill(row)]
    assert {row["client_order_id"] for row in live} == set(LIVE_MATCHED_CLIENT_IDS)
    for row in load_public_records():
        extra = row.get("extra") or {}
        if row.get("channel") == "replay" and row.get("outcome") == "MATCHED":
            assert extra.get("live_fill_claimed") is not True
            mapped = manifest["claims"][row["claim"]]
            assert mapped["live_fill"] is False
            assert mapped["live_mleg_submit"] is False
            assert mapped["channel"] == "replay"
            caveat = str(mapped.get("caveat") or "")
            assert "fixture" not in caveat.lower()
            assert "not public completion" not in caveat
        elif is_live_fill_row(row):
            assert extra.get("live_fill_claimed") is True
            mapped = manifest["claims"][row["claim"]]
            assert mapped["live_fill"] is True
        else:
            assert extra.get("live_fill_claimed") is not True
