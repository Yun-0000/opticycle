# Third-party notices

This repository is MIT-licensed. The following components are included or invoked at runtime. Their license texts apply to those components.

## Gauss World Trader (pinned foundation)

- Project: Gauss World Trader
- Repository: https://github.com/Magica-Chen/GaussWorldTrader
- Pinned commit: `31374551bae6fd34a0fe56fe11d208f4ff04fbb4`
- Snapshot path: `vendor/pin-31374551/`
- License: MIT. Full text: `vendor/pin-31374551/LICENSE` and the root `LICENSE`.
- Original author: Zexun Chen (`Copyright (c) 2026 Zexun Chen`)
- Reuse scope: pinned baseline algorithmic framework only (layout, Alpaca data-client wrapper, greeks utilities, vertical-spread construction helpers). Not used as the live Opticycle product.

## alpaca-py

Apache License 2.0. Market data and account verification clients.

## alpaca-mcp-server 2.3.0

MIT License. Spawned as the official order path (`uvx alpaca-mcp-server==2.3.0`, tool `place_option_order`).

## mcp 2.1.1

MIT License. Python MCP client used to speak stdio to the Alpaca MCP server.

## vollib 1.0.11

MIT License. Black-Scholes greeks used in pre-trade risk gates.
