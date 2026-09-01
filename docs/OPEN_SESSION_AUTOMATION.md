# Regular-session runner

Paper only. During a US equity regular session this script observes, may call ThesisAgent, manages exits, and can place at most one new certified MLEG.

```bash
# observe + ThesisAgent only
PYTHONPATH=vendor/pin-31374551:src python3 scripts/run-open-session.py

# exits first, then at most one new paper MLEG
PYTHONPATH=vendor/pin-31374551:src python3 scripts/run-open-session.py --submit
```

It exits without trading when the Alpaca clock is closed. Credit limits stay Alpaca-signed (negative). The lock file `data/open_session_lock.json` is gitignored; live broker orders and positions are the source of truth for daily and open-vertical caps.

Never commit keys.
