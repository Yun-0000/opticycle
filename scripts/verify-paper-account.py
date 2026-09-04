#!/usr/bin/env python3
"""Verify paper credentials with GET /v2/account without printing secrets."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

PAPER_ACCOUNT = "PA3V84C40PJQ"
URL = "https://paper-api.alpaca.markets/v2/account"


def verify() -> dict[str, object]:
    key = (os.environ.get("ALPACA_API_KEY") or "").strip()
    secret = (os.environ.get("ALPACA_SECRET_KEY") or "").strip()
    if not key or not secret:
        return {"ok": False, "http_status": None, "reason": "paper credentials missing"}
    request = urllib.request.Request(
        URL,
        method="GET",
        headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
            status = int(response.status)
    except urllib.error.HTTPError as exc:
        return {"ok": False, "http_status": int(exc.code), "reason": "paper account rejected"}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return {"ok": False, "http_status": None, "reason": "paper account unreachable"}
    account_id = str(body.get("account_number") or body.get("id") or "")
    matched = account_id == PAPER_ACCOUNT
    return {
        "ok": status == 200 and matched,
        "http_status": status,
        "account_id": account_id if matched else "mismatch",
        "paper": True,
        "reason": "verified" if status == 200 and matched else "designated account mismatch",
    }


def main() -> int:
    result = verify()
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
