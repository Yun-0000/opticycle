"""Hackathon pydantic-settings: $100k paper, options required, MCP default."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ALLOWED_STRATEGIES = ("vertical_spread",)
STOCK_STRATEGIES = (
    "momentum",
    "value",
    "trend_following",
    "scalping",
    "statistical_arbitrage",
    "mean_reversion",
    "macro_factor",
    "multi_agent",
)


class HackathonSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HACKATHON_",
        env_file=None,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    starting_capital: float = Field(default=100_000, gt=0)
    require_options: bool = True
    execution_backend: Literal["mcp"] = "mcp"
    mcp_server_spec: str = "alpaca-mcp-server==2.3.0"
    watchlist: str = "SPY"
    interval_minutes: int = Field(default=15, ge=1, le=240)
    agent_mode: Literal["fast", "llm"] = "fast"
    strategy: Literal["vertical_spread"] = "vertical_spread"
    paper_only: bool = True
    max_position_pct: float = Field(default=0.08, gt=0, le=0.25)
    max_daily_trades: int = Field(default=8, ge=1, le=50)
    max_open_positions: int = Field(default=6, ge=1, le=20)
    max_abs_delta: float = Field(default=80.0, gt=0)
    max_abs_vega: float = Field(default=250.0, gt=0)
    equity_tolerance: float = Field(default=0.15, gt=0, le=0.5)
    paper_account_id: str | None = "PA3V84C40PJQ"
    llm_provider: str = "openai"

    @field_validator("execution_backend")
    @classmethod
    def backend_must_be_mcp(cls, value: str) -> str:
        name = value.strip().lower()
        if name != "mcp":
            raise ValueError("official MCP is the only live execution channel")
        return name

    @field_validator("strategy")
    @classmethod
    def strategy_must_be_options(cls, value: str) -> str:
        name = value.strip().lower()
        if name in STOCK_STRATEGIES:
            raise ValueError("stock-only strategies are disabled for this event")
        if name not in ALLOWED_STRATEGIES:
            raise ValueError("only SPY defined-risk vertical is enabled")
        return name

    @field_validator("require_options")
    @classmethod
    def options_must_stay_on(cls, value: bool) -> bool:
        if not value:
            raise ValueError("require_options cannot be turned off")
        return True

    @field_validator("paper_only")
    @classmethod
    def paper_must_stay_on(cls, value: bool) -> bool:
        if not value:
            raise ValueError("live trading is out of scope")
        return True

    @property
    def symbols(self) -> list[str]:
        return [part.strip().upper() for part in self.watchlist.split(",") if part.strip()]
