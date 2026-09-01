#!/usr/bin/env python3
"""Fetch Alpaca portfolio/history and render a dependency-free equity PNG."""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import urllib.error
import urllib.parse
import urllib.request
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT_URL = "https://paper-api.alpaca.markets/v2/account"
HISTORY_URL = "https://paper-api.alpaca.markets/v2/account/portfolio/history"
DESIGNATED_ACCOUNT = "PA3V84C40PJQ"


def _request(url: str) -> tuple[int, dict]:
    key = (os.environ.get("ALPACA_API_KEY") or "").strip()
    secret = (os.environ.get("ALPACA_SECRET_KEY") or "").strip()
    if not key or not secret:
        raise RuntimeError("paper credentials missing")
    request = urllib.request.Request(
        url,
        headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return int(response.status), json.loads(response.read().decode("utf-8"))


def _chunk(tag: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)


def _render_png(values: list[float], path: Path, *, width: int = 1200, height: int = 480) -> None:
    bg = (8, 10, 13)
    pixels = [list(bg) for _ in range(width * height)]

    def set_px(x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < width and 0 <= y < height:
            pixels[y * width + x] = list(color)

    def line(x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int], thickness: int = 1) -> None:
        dx, sx = abs(x1 - x0), 1 if x0 < x1 else -1
        dy, sy = -abs(y1 - y0), 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            for ox in range(-thickness, thickness + 1):
                for oy in range(-thickness, thickness + 1):
                    set_px(x0 + ox, y0 + oy, color)
            if x0 == x1 and y0 == y1:
                break
            twice = 2 * err
            if twice >= dy:
                err += dy
                x0 += sx
            if twice <= dx:
                err += dx
                y0 += sy

    left, right, top, bottom = 54, width - 42, 34, height - 48
    for fraction in (0, 0.25, 0.5, 0.75, 1):
        y = int(top + (bottom - top) * fraction)
        line(left, y, right, y, (37, 45, 55))
    low, high = min(values), max(values)
    if high == low:
        high += 1
        low -= 1
    pad = max((high - low) * 0.18, 1)
    low -= pad
    high += pad
    points: list[tuple[int, int]] = []
    for index, value in enumerate(values):
        x = left if len(values) == 1 else int(left + (right - left) * index / (len(values) - 1))
        y = int(bottom - (value - low) / (high - low) * (bottom - top))
        points.append((x, y))
    for start, end in zip(points, points[1:]):
        line(*start, *end, (166, 255, 0), thickness=2)
    for x, y in (points[0], points[-1]):
        for radius, color in ((7, (8, 10, 13)), (4, (246, 211, 101))):
            for ox in range(-radius, radius + 1):
                for oy in range(-radius, radius + 1):
                    if ox * ox + oy * oy <= radius * radius:
                        set_px(x + ox, y + oy, color)
    raw = b"".join(b"\x00" + bytes(sum(pixels[row * width : (row + 1) * width], [])) for row in range(height))
    png = b"\x89PNG\r\n\x1a\n"
    png += _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += _chunk(b"IDAT", zlib.compress(raw, 9))
    png += _chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--period", default="1M")
    parser.add_argument("--timeframe", default="1D")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "artifacts" / "evidence")
    args = parser.parse_args(argv)
    query = urllib.parse.urlencode(
        {"period": args.period, "timeframe": args.timeframe, "extended_hours": "false"}
    )
    try:
        account_status, account = _request(ACCOUNT_URL)
        history_status, history = _request(f"{HISTORY_URL}?{query}")
    except (RuntimeError, urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "reason": type(exc).__name__ if not isinstance(exc, RuntimeError) else str(exc)}))
        return 1
    account_id = str(account.get("account_number") or account.get("id") or "")
    equities = [float(value) for value in history.get("equity") or [] if value is not None]
    timestamps = list(history.get("timestamp") or [])
    if account_status != 200 or history_status != 200 or account_id != DESIGNATED_ACCOUNT or len(equities) < 2:
        print(json.dumps({"ok": False, "reason": "account/history verification failed"}))
        return 1
    points = [
        {"timestamp": int(timestamp), "equity": equity}
        for timestamp, equity in zip(timestamps, equities)
    ]
    payload = {
        "schema": "opticycle.portfolio-history.v1",
        "source": "GET /v2/account/portfolio/history",
        "http_status": history_status,
        "account_id": account_id,
        "period": args.period,
        "timeframe": args.timeframe,
        "points": points,
        "start_equity": equities[0],
        "end_equity": equities[-1],
        "net_change": round(equities[-1] - equities[0], 2),
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "portfolio_history.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _render_png(equities, args.out_dir / "equity-curve.png")
    print(json.dumps({"ok": True, "http_status": history_status, "points": len(points), "net_change": payload["net_change"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
