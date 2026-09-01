# Open-session automation

Runs the remaining first-place live work during a regular US equity session. Paper only.

## What the script does

1. Checks Alpaca clock. If the regular session is closed, it exits without trading.
2. Observes live SPY quotes and calls ThesisAgent (`gpt-5.6-luna` by default).
3. With `--submit`, manages triggered exits first, then may place one certified paper MLEG if the thesis is accepted. Credit limits stay Alpaca-signed (negative).
4. Records `arguments_hash` and `raw_result_hash` from MCP when a submit happens.
5. Enforces two new contracts per day, four contracts open, and deterministic profit/loss/expiry/event exits.

The lock (`data/open_session_lock.json`, gitignored) is an audit counter, not a fallback gate. Live broker orders/positions remain the source of truth for daily and open-contract caps.

```bash
# observe + ThesisAgent only
PYTHONPATH=vendor/pin-31374551:src python3 scripts/run-open-session.py

# manage exits, then observe + at most one new paper MLEG
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
5. **Trigger:** Scheduled every 30 minutes on weekdays. While EDT is in effect use cron `*/30 13-20 * * 1-5`; the broker clock gate makes the 13:00 and 20:00 UTC edge runs observation-only, leaving 13:30–19:30 UTC as RTH cycles.
6. **Repository:** Cron defaults to **no repository**. Switch to **Single repository** → `yun-hackathons/hack-alpaca-trading-agents-2026` → branch `main`.
7. **Model:** pick one (runs bill at API pricing). **Permissions:** **Private** so paper keys stay on your account.
8. If Cloud Agents are not on **Allow all network access**, allowlist Alpaca paper API, OpenAI, and GitHub.
9. Paste the prompt below, save, and activate.

```
Fetch and checkout main. Do not create a branch or PR; do not change execution code from the automation.

Paper only. After a short preflight (keys, ALPACA_LIVE_TRADE=false, uvx), run immediately — no repo review or full tests first:

  PYTHONPATH=vendor/pin-31374551:src python3 scripts/run-open-session.py --submit

If uvx / alpaca-mcp-server==2.3.0 cannot start, stop. No other submit path.

Then capture the read-only Alpaca CLI snapshot when available, export the sanitized episode, rebuild public evidence, scan secrets, run targeted tests, commit, and push. Never commit keys or raw broker dumps.
```
