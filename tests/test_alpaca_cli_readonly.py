from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from opticycle.alpaca_cli_readonly import AlpacaCliReadError, AlpacaCliReadOnly


def test_cli_readonly_uses_official_singular_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr("opticycle.alpaca_cli_readonly.shutil.which", lambda _binary: "/usr/bin/alpaca")

    def run(command, **kwargs):
        calls.append(command)
        if command[1:3] == ["account", "get"]:
            payload = {"account_number": "PA3V84C40PJQ", "equity": "100000"}
        elif command[1:3] == ["position", "list"]:
            payload = []
        else:
            payload = [{"id": "oid", "client_order_id": "cid", "status": "filled"}]
        assert kwargs["env"]["ALPACA_LIVE_TRADE"] == "false"
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr("opticycle.alpaca_cli_readonly.subprocess.run", run)
    client = AlpacaCliReadOnly()
    snapshot = client.snapshot()
    assert [call[1:3] for call in calls] == [
        ["account", "get"],
        ["position", "list"],
        ["order", "list"],
    ]
    assert snapshot["paper_only"] is True
    assert len(snapshot["snapshot_hash"]) == 64


def test_cli_readonly_rejects_non_allowlisted_resource() -> None:
    with pytest.raises(AlpacaCliReadError, match="not allowed"):
        AlpacaCliReadOnly().read("close-all")
