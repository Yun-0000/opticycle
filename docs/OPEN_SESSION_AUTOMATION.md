# Open-session automation

Runs the remaining first-place live work during a regular US equity session. Paper only.

## What the script does

1. Checks Alpaca clock. If the regular session is closed, it exits without trading.
2. Observes live SPY quotes and calls ThesisAgent (`gpt-5.6-luna` by default).
3. With `--submit`, places **at most one** certified paper MLEG if the thesis is accepted. Credit limits stay Alpaca-signed (negative).
4. Records `arguments_hash` and `raw_result_hash` from MCP when a submit happens.
5. **Does not close** the two existing verticals.

One submit per UTC calendar day (`data/open_session_lock.json`, gitignored). If a price-bound live `MATCHED` is already in the public pack, it will not submit again.

```bash
# observe + ThesisAgent only
PYTHONPATH=vendor/pin-31374551:src python3 scripts/run-open-session.py

# observe + at most one paper MLEG
PYTHONPATH=vendor/pin-31374551:src python3 scripts/run-open-session.py --submit
```

Never commit keys.

## Set up a Cursor Automation

1. Connect GitHub: Dashboard → Integrations → **Connect** / **Manage Connections**. Give the Cursor GitHub app **read-write** on `yun-hackathons/hack-alpaca-trading-agents-2026`. Cloud Agents need a **paid** Cursor plan.
2. Confirm a Cloud Agent **environment** exists for this repo (Python + checkout). Automations reuse that environment.
3. Add secrets at [cursor.com/dashboard/cloud-agents](https://cursor.com/dashboard/cloud-agents) → **Secrets** (not on the Automations form). Use **Runtime Secret** for keys:
   - `ALPACA_API_KEY`
   - `ALPACA_SECRET_KEY`
   - `OPENAI_API_KEY`
   - `ALPACA_PAPER_TRADE` = `true`
   - `ALPACA_LIVE_TRADE` = `false`
   - `HACKATHON_LLM_MODEL` = `gpt-5.6-luna`  
   A gitignored `.env` is **not** cloned into a fresh Automation VM. After adding secrets, later runs pick them up.
4. Create the automation: [cursor.com/automations/new](https://cursor.com/automations/new) (or Desktop **Agents Window**, or `/automate`).
5. **Trigger:** Scheduled. Weekdays **09:40 America/New_York**, or cron `40 13 * * 1-5` while EDT is in effect (13:40 UTC).
6. **Repository:** Cron defaults to **no repository**. Switch to **Single repository** → `yun-hackathons/hack-alpaca-trading-agents-2026` → branch `cursor/credit-limit-semantics-31e7`.
7. **Model:** pick one (runs bill at API pricing). **Permissions:** **Private** so paper keys stay on your account.
8. If Cloud Agents are not on **Allow all network access**, allowlist Alpaca paper API, OpenAI, and GitHub.
9. Paste the prompt below, save, and activate.

The extra operational lines are load-bearing: Cloud Agents default to a **new** branch and a **new** PR; they also burn the open on review/tests; if `uvx` / MCP is missing they may fall back to alpaca-py. The script already refuses a closed clock, a second same-day submit, and unsigned MATCHED — the prompt still has to stop the *agent* from going around it.

```
First fetch and checkout the existing remote branch cursor/credit-limit-semantics-31e7.
Do not create a new branch or a new PR. Push only to this exact branch so existing PR 3 is updated.

Paper only. ALPACA_LIVE_TRADE must stay false.
Use Cloud Agent secrets (ALPACA_API_KEY, ALPACA_SECRET_KEY, OPENAI_API_KEY).
HACKATHON_LLM_MODEL=gpt-5.6-luna.

After checkout and a minimal safety preflight (paper flags, keys present, uvx available),
run immediately:

  PYTHONPATH=vendor/pin-31374551:src python3 scripts/run-open-session.py --submit

Do not spend the market session on broad repository review or a full test suite before the live attempt.
Verify uvx is available before any submit. If Alpaca MCP (uvx alpaca-mcp-server==2.3.0) cannot start, stop.
Do not use another broker path or submission method (no alpaca-py submit_order, no REST place-order).

If the clock is closed, stop. If ThesisAgent returns NO_TRADE, export that episode honestly
(model_called=true is success even with no order).
If a paper MLEG is submitted, ingest broker order_id, keep FILLED vs MATCHED honest
(only MATCHED if filled <= signed credit limit).

After the run, export the sanitized episode before the VM ends, rebuild public evidence,
run targeted tests and scripts/scan-public-evidence.py, then commit and push.
Never commit secrets, private account identifiers, or unsanitized broker data.

Do not close existing positions. Do not invent MATCHED.
Do not place a second order the same UTC day.
If a price-bound MATCHED live fill already exists, stop submitting.
```
