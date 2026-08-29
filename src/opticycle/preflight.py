"""Paper-account preflight. Live calls are skipped in dry-run/CI."""

from __future__ import annotations

from opticycle.risk import PortfolioSnapshot
from opticycle.settings import HackathonSettings
from trade.orders import ExecutionRejected


def dry_run_portfolio(settings: HackathonSettings) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        equity=settings.starting_capital,
        buying_power=settings.starting_capital,
        cash=settings.starting_capital,
        account_id=settings.paper_account_id,
        paper=True,
        options_approved=True,
        trades_today=0,
        open_positions=0,
        net_delta=0.0,
        net_vega=0.0,
    )


def assert_paper_env(settings: HackathonSettings) -> None:
    if not settings.paper_only:
        raise ExecutionRejected("live trading is disabled")
    if settings.execution_backend not in {"mcp", "cli"}:
        raise ExecutionRejected("orders must go through MCP or CLI")
    if not settings.require_options:
        raise ExecutionRejected("stock-only path is disabled")
