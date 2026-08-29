# GaussOptions Agent

Autonomous paper-trading agent for equity options.

- Places option orders through Alpaca MCP (primary) or Alpaca CLI (fallback)
- Options-only hackathon profile on a dedicated $100k paper book
- Run a single dry-run cycle: `python -m src.gaussoptions --once --backend mcp --dry-run`

API keys stay in local environment variables. Never commit secrets.
