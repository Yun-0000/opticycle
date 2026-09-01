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

```
Fetch and checkout cursor/credit-limit-semantics-31e7. Do not create a branch or PR; push only here (updates PR 3).

Paper only. After a short preflight (keys, ALPACA_LIVE_TRADE=false, uvx), run immediately — no repo review or full tests first:

  PYTHONPATH=vendor/pin-31374551:src python3 scripts/run-open-session.py --submit

If uvx / alpaca-mcp-server==2.3.0 cannot start, stop. No other submit path.

Then export the sanitized episode, rebuild public evidence, scan secrets, targeted tests, commit and push. No secrets, account ids, or raw broker dumps. Do not close existing positions.
```
