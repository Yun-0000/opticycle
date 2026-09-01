"""Read-only Alpaca CLI adapter for independent broker evidence."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from opticycle.protocol import canonical_hash

READ_COMMANDS: dict[str, tuple[str, ...]] = {
    "account": ("account", "get", "--quiet"),
    "positions": ("position", "list", "--quiet"),
    "orders": ("order", "list", "--status", "all", "--limit", "100", "--quiet"),
}


class AlpacaCliReadError(RuntimeError):
    """The official read-only CLI could not return trustworthy JSON."""


def _paper_env() -> dict[str, str]:
    env = dict(os.environ)
    env["ALPACA_LIVE_TRADE"] = "false"
    env["ALPACA_PAPER_TRADE"] = "true"
    env["ALPACA_OUTPUT"] = "json"
    env["ALPACA_QUIET"] = "true"
    return env


def _get(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


@dataclass(slots=True)
class AlpacaCliReadOnly:
    binary: str = "alpaca"
    timeout_seconds: int = 30

    def available(self) -> bool:
        return shutil.which(self.binary) is not None

    def read(self, resource: str) -> Any:
        if resource not in READ_COMMANDS:
            raise AlpacaCliReadError(f"read-only resource not allowed: {resource}")
        if not self.available():
            raise AlpacaCliReadError("official Alpaca CLI is not installed")
        command = [self.binary, *READ_COMMANDS[resource]]
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
            env=_paper_env(),
        )
        if completed.returncode != 0:
            raise AlpacaCliReadError(f"alpaca {resource} read failed with exit {completed.returncode}")
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise AlpacaCliReadError(f"alpaca {resource} did not return JSON") from exc

    def snapshot(self) -> dict[str, Any]:
        account = self.read("account")
        positions = self.read("positions")
        orders = self.read("orders")
        evidence = {
            "schema": "opticycle.alpaca-cli-readonly.v1",
            "commands": {
                key: [self.binary, *value] for key, value in READ_COMMANDS.items()
            },
            "paper_only": True,
            "account": _public_account(account),
            "positions": [_public_position(item) for item in list(positions or [])],
            "orders": [_public_order(item) for item in list(orders or [])],
        }
        evidence["snapshot_hash"] = canonical_hash(evidence)
        return evidence

    def reconcile_order(
        self,
        *,
        client_order_id: str,
        broker_order_id: str | None,
    ) -> dict[str, Any]:
        orders = list(self.read("orders") or [])
        matches = [
            item
            for item in orders
            if str(_get(item, "client_order_id") or "") == str(client_order_id)
        ]
        if len(matches) != 1:
            return {
                "available": True,
                "matched": False,
                "reason": "missing or duplicate client_order_id",
                "client_order_id": client_order_id,
            }
        item = matches[0]
        cli_order_id = str(_get(item, "id") or "")
        matched = not broker_order_id or cli_order_id == str(broker_order_id)
        return {
            "available": True,
            "matched": matched,
            "client_order_id": client_order_id,
            "broker_order_id": cli_order_id,
            "status": str(getattr(_get(item, "status"), "value", _get(item, "status", "")) or ""),
            "source": "official_alpaca_cli_read_only",
        }


def _public_account(account: Any) -> dict[str, Any]:
    return {
        "id": str(_get(account, "id") or _get(account, "account_number") or ""),
        "status": str(getattr(_get(account, "status"), "value", _get(account, "status", "")) or ""),
        "equity": str(_get(account, "equity") or ""),
        "cash": str(_get(account, "cash") or ""),
        "buying_power": str(_get(account, "buying_power") or ""),
    }


def _public_position(position: Any) -> dict[str, Any]:
    return {
        "symbol": str(_get(position, "symbol") or ""),
        "qty": str(_get(position, "qty") or ""),
        "side": str(getattr(_get(position, "side"), "value", _get(position, "side", "")) or ""),
        "avg_entry_price": str(_get(position, "avg_entry_price") or ""),
        "current_price": str(_get(position, "current_price") or ""),
        "unrealized_pl": str(_get(position, "unrealized_pl") or ""),
    }


def _public_order(order: Any) -> dict[str, Any]:
    return {
        "id": str(_get(order, "id") or ""),
        "client_order_id": str(_get(order, "client_order_id") or ""),
        "status": str(getattr(_get(order, "status"), "value", _get(order, "status", "")) or ""),
        "qty": str(_get(order, "qty") or ""),
        "filled_qty": str(_get(order, "filled_qty") or ""),
        "filled_avg_price": str(_get(order, "filled_avg_price") or ""),
        "limit_price": str(_get(order, "limit_price") or ""),
        "order_class": str(getattr(_get(order, "order_class"), "value", _get(order, "order_class", "")) or ""),
    }


def write_snapshot(path: Path, *, client: AlpacaCliReadOnly | None = None) -> dict[str, Any]:
    payload = (client or AlpacaCliReadOnly()).snapshot()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload
