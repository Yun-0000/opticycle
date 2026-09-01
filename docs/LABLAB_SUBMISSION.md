# LabLab submission fields

**Title:** Opticycle

**Tagline:** The SPY options agent that proves every trade before—and after—it executes.

**Cover:** `artifacts/demo-poster.png`

**Description**

Opticycle is a proof-carrying paper trading agent for SPY defined-risk credit verticals. ThesisAgent sees fresh quote, volatility, skew, range, trend, and event evidence, then chooses only BULLISH, BEARISH, or NO_TRADE. Deterministic code selects the exact 3–10 DTE, $5-wide spread, sizes it from live equity, and binds a risk certificate to the final MLEG payload. All order mutations go through the official Alpaca MCP Server. Alpaca broker GET and the official read-only CLI independently reconcile the same client order ID; a mismatch or uncertain timeout halts instead of resubmitting or splitting legs. The agent also manages open spreads with 50% profit, 2× credit loss, expiry, and NFP risk exits. The public Judge packet includes three real paper receipts, a price-bound MATCHED trade, realized results, an Alpaca portfolio-history equity curve, and the full proof trace.

**Tech tags:** Alpaca, MCP, OpenAI, Cursor

**GitHub:** https://github.com/yun-hackathons/hack-alpaca-trading-agents-2026

**Video:** https://yun-hackathons.github.io/hack-alpaca-trading-agents-2026/demo.mp4

**Judge packet / live demo URL:** https://yun-hackathons.github.io/hack-alpaca-trading-agents-2026/evidence/
