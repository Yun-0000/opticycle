"""Official Alpaca CLI fallback for paper option orders.

Pinned installer tag: v0.0.14 (see docs/Dockerfile). Paper is mandatory:
ALPACA_LIVE_TRADE must not be true. Tests inject a subprocess runner.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from ..orders import ExecutionRejected, OptionOrderRequest

ALPACA_CLI_TAG = "v0.0.14"
SubprocessRunner = Callable[..., subprocess.CompletedProcess[str]]


def paper_cli_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if value is not None}
    live = str(env.get("ALPACA_LIVE_TRADE") or "").strip().lower()
    if live == "true":
        raise ExecutionRejected("live trading is disabled; Alpaca CLI must stay on paper")
    env["ALPACA_LIVE_TRADE"] = "false"
    env["ALPACA_OUTPUT"] = env.get("ALPACA_OUTPUT") or "json"
    env["ALPACA_QUIET"] = env.get("ALPACA_QUIET") or "true"
    if extra:
        env.update(extra)
        if str(env.get("ALPACA_LIVE_TRADE") or "").strip().lower() == "true":
            raise ExecutionRejected("live trading is disabled; Alpaca CLI must stay on paper")
    return env


@dataclass
class AlpacaCliExecutor:
    binary: str = "alpaca"
    dry_run: bool = False
    runner: SubprocessRunner | None = None
    env: dict[str, str] | None = None

    def place_option_order(self, request: OptionOrderRequest) -> dict[str, Any]:
        request.assert_options_instrument()
        argv = request.to_cli_argv(self.binary)
        if self.dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "backend": "cli",
                "argv": argv,
            }
        env = paper_cli_env(self.env)
        runner = self.runner or subprocess.run
        completed = runner(
            argv,
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            raise RuntimeError(
                f"alpaca CLI exited {completed.returncode}: {stderr or completed.stdout}"
            )
        payload = _parse_json(completed.stdout)
        payload.setdefault("ok", True)
        payload.setdefault("backend", "cli")
        return payload


def _parse_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {"ok": True, "raw": ""}
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return {"ok": True, "raw": text}
    if isinstance(loaded, dict):
        return loaded
    return {"ok": True, "data": loaded}
