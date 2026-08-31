# Open-session automation

Runs the remaining first-place live work during a regular US equity session. Paper only.

## What it does

1. Checks Alpaca clock. If the regular session is closed, it exits without trading.
2. Observes live SPY quotes and calls ThesisAgent (`gpt-5.6-luna` by default).
3. With `--submit`, places **at most one** certified paper MLEG if the thesis is accepted. Credit limits stay Alpaca-signed (negative).
4. Records `arguments_hash` and `raw_result_hash` from MCP when a submit happens.
5. **Does not close** the two existing verticals.

One submit per UTC calendar day (`data/open_session_lock.json`, gitignored). If a price-bound live `MATCHED` is already in the public pack, it will not submit again.

## Local / this Cloud Agent

```bash
# observe + ThesisAgent only
PYTHONPATH=vendor/pin-31374551:src python3 scripts/run-open-session.py

# observe + at most one paper MLEG
PYTHONPATH=vendor/pin-31374551:src python3 scripts/run-open-session.py --submit
```

Keys stay in gitignored `.env`. Never commit them.

## Cursor Automation (dashboard)

This repo cannot create a Cursor Automation via API. In Cursor: **Automations → New**, schedule weekdays **09:40 America/New_York** (after the cash open), and point it at this prompt:

```
On branch cursor/credit-limit-semantics-31e7 of yun-hackathons/hack-alpaca-trading-agents-2026.

Load gitignored .env (ALPACA paper keys + OPENAI_API_KEY). Paper only. ALPACA_LIVE_TRADE must stay false.

Run: PYTHONPATH=vendor/pin-31374551:src python3 scripts/run-open-session.py --submit

If the clock is closed, stop. If ThesisAgent returns NO_TRADE, export that episode honestly (model_called=true is success even with no order). If a paper MLEG is submitted, ingest broker order_id, keep FILLED vs MATCHED honest (only MATCHED if filled <= signed credit limit), rebuild public evidence, scan secrets, commit, push, update PR 3.

Do not close existing positions. Do not invent MATCHED. Do not place a second order the same UTC day. If a price-bound MATCHED live fill already exists, stop submitting.
```

## This conversation's timer

A Cloud Agent timer is also subscribed to fire weekdays at **13:40 UTC** (09:40 ET while EDT is in effect, through the 2026-09-04 deadline).
