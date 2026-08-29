"""Hackathon paper-trading profile. Keys stay in the environment, never in git."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HackathonProfile:
    starting_capital: float = 100_000.0
    require_options: bool = True
    execution_backend: str = "mcp"  # mcp | cli
    symbol: str = "SPY"
    max_position_pct: float = 0.15
    max_daily_trades: int = 8

    def validate_backend(self) -> str:
        backend = self.execution_backend.lower()
        if backend not in {"mcp", "cli"}:
            raise ValueError("execution_backend must be mcp or cli")
        return backend
