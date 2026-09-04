#!/usr/bin/env python3
"""Render the submission slide deck as a 16:9 PDF (lablab requires PDF)."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import Color, HexColor
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "opticycle-slides.pdf"
POSTER = ROOT / "artifacts" / "demo-poster.png"

W, H = 1920, 1080
BG = HexColor("#0b0e12")
PANEL = HexColor("#1f2124")
LINE = HexColor("#303235")
INK = HexColor("#dedede")
MUTED = HexColor("#818284")
ACCENT = HexColor("#a8ff00")
RED = HexColor("#ff6285")


def _page(c: Canvas) -> None:
    c.setFillColor(BG)
    c.rect(0, 0, W, H, fill=1, stroke=0)
    c.setStrokeColor(LINE)
    c.setLineWidth(1)
    for x in range(0, W, 32):
        c.line(x, 0, x, H)
    for y in range(0, H, 32):
        c.line(0, y, W, y)
    c.setFillColor(BG)
    c.setStrokeColor(LINE)
    c.setLineWidth(1)
    c.roundRect(48, 48, W - 96, H - 96, 2, fill=1, stroke=1)
    c.setFillColor(ACCENT)
    c.rect(48, 48, 8, H - 96, fill=1, stroke=0)


def _header(c: Canvas, number: str) -> None:
    c.setFillColor(ACCENT)
    c.setFont("Courier-Bold", 16)
    c.drawString(96, 980, "OPTICYCLE")
    c.setFillColor(MUTED)
    c.setFont("Courier", 16)
    c.drawRightString(W - 96, 980, number)


def _title(c: Canvas, text: str, y: float = 900) -> None:
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 48)
    c.drawString(96, y, text)


def _lede(c: Canvas, text: str, y: float = 840) -> None:
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 22)
    c.drawString(96, y, text)


def _card(c: Canvas, x: float, y: float, w: float, h: float, fill: Color = PANEL) -> None:
    c.setFillColor(fill)
    c.setStrokeColor(LINE)
    c.setLineWidth(1)
    c.rect(x, y, w, h, fill=1, stroke=1)


def slide_title(c: Canvas) -> None:
    c.drawImage(ImageReader(str(POSTER)), 0, 0, width=W, height=H, preserveAspectRatio=True, anchor="c")


def slide_path(c: Canvas) -> None:
    _page(c)
    _header(c, "02")
    _title(c, "One verified path")
    _lede(c, "The broker receipt, not the transport response, decides what is true.")
    steps = [
        "SNAPSHOT",
        "LLM STANCE",
        "PAYLOAD",
        "CERT",
        "MCP",
        "BROKER GET",
        "MATCHED",
    ]
    x = 96
    for i, name in enumerate(steps):
        _card(c, x, 520, 210, 180)
        c.setFillColor(ACCENT if name == "MATCHED" else MUTED)
        c.setFont("Courier-Bold", 13)
        c.drawString(x + 16, 660, name)
        if i < len(steps) - 1:
            c.setFillColor(MUTED)
            c.setFont("Helvetica", 22)
            c.drawString(x + 214, 590, "›")
        x += 248
    facts = [
        ("STRUCTURE", "SELL 740P   BUY 724P"),
        ("LIMIT / FILL", "-2.26  /  -2.26"),
        ("BROKER ORDER", "24b16fe6…"),
        ("CLIENT ID", "oc-63db2a…"),
        ("RESULT", "price-bound MATCHED"),
    ]
    x = 96
    for label, value in facts:
        _card(c, x, 140, 332, 280)
        c.setFillColor(MUTED)
        c.setFont("Courier", 12)
        c.drawString(x + 20, 380, label)
        c.setFillColor(INK)
        c.setFont("Helvetica", 18)
        c.drawString(x + 20, 330, value)
        x += 352


def slide_invariants(c: Canvas) -> None:
    _page(c)
    _header(c, "03")
    _title(c, "Authorization follows the payload")
    _lede(c, "The model has no route to contracts, quantity, limit price, or execution.")
    _card(c, 96, 140, 840, 620)
    c.setFillColor(ACCENT)
    c.setFont("Helvetica-Bold", 28)
    c.drawString(128, 690, "BYTE-BOUND")
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 20)
    c.drawString(128, 640, "Any change invalidates the certificate")
    for i, item in enumerate(["symbol", "side or intent", "leg ratio", "quantity", "limit price"]):
        y = 540 - i * 70
        c.setFillColor(ACCENT)
        c.rect(128, y, 10, 10, fill=1, stroke=0)
        c.setFillColor(INK)
        c.setFont("Helvetica", 22)
        c.drawString(156, y - 4, item)
    _card(c, 984, 140, 840, 620)
    c.setFillColor(ACCENT)
    c.setFont("Helvetica-Bold", 28)
    c.drawString(1016, 690, "ZERO-RESUBMIT")
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 72)
    c.drawString(1016, 540, "1")
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 22)
    c.drawString(1080, 556, "MCP submit")
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 72)
    c.drawString(1016, 400, "0")
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 22)
    c.drawString(1080, 416, "resubmits")
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 18)
    c.drawString(1016, 220, "Unknown response: GET the same client ID or HALT")


def slide_results(c: Canvas) -> None:
    _page(c)
    _header(c, "04")
    _title(c, "Broker paper results")
    _lede(c, "Actual fills stay separate from modeled research and from the open position mark.")
    headers = ["STRUCTURE", "ENTRY", "BROKER STATE", "RESULT"]
    rows = [
        ("793C / 809C", "filled -2.11", "closed through MCP", "+$58 approx."),
        ("768C / 769C", "filled -0.51", "closed through MCP", "−$2 approx."),
        ("740P / 724P", "limit -2.26", "price-bound MATCHED", "open at Sep 1 snapshot"),
    ]
    x0, y0, row_h = 96, 620, 88
    widths = [360, 360, 460, 500]
    x = x0
    for header, width in zip(headers, widths, strict=True):
        c.setFillColor(ACCENT)
        c.setFont("Courier", 13)
        c.drawString(x, y0 + 40, header)
        x += width
    for i, row in enumerate(rows):
        y = y0 - (i + 1) * row_h
        _card(c, 96, y - 20, W - 192, row_h - 8)
        x = x0
        for j, (cell, width) in enumerate(zip(row, widths, strict=True)):
            if j == 3 and cell.startswith("+"):
                c.setFillColor(ACCENT)
            elif j == 3 and cell.startswith("−"):
                c.setFillColor(RED)
            else:
                c.setFillColor(INK)
            c.setFont("Helvetica", 20)
            c.drawString(x, y + 16, cell)
            x += width
    _card(c, 96, 140, 840, 200)
    c.setFillColor(MUTED)
    c.setFont("Courier", 12)
    c.drawString(128, 292, "CLOSED-SPREAD REALIZED P&L")
    c.setFillColor(ACCENT)
    c.setFont("Helvetica-Bold", 48)
    c.drawString(128, 210, "+$55.67")
    _card(c, 984, 140, 840, 200)
    c.setFillColor(MUTED)
    c.setFont("Courier", 12)
    c.drawString(1016, 292, "SEP 1 COMMITTED CLI SNAPSHOT")
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 28)
    c.drawString(1016, 230, "$100,036.62 equity")
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 20)
    c.drawString(1016, 186, "−$19.00 open unrealized P&L")


def slide_rights(c: Canvas) -> None:
    _page(c)
    _header(c, "05")
    _title(c, "Decision rights")
    _lede(c, "One stance from AI. Every capital decision remains deterministic and broker-verifiable.")
    lanes = [
        ("AI", "BULLISH, BEARISH, or NO_TRADE"),
        ("CODE", "contracts, size, price, risk, exits"),
        ("BROKER", "receipt, fill, position, account equity"),
    ]
    x = 96
    for title, body in lanes:
        _card(c, x, 560, 560, 200)
        c.setFillColor(ACCENT)
        c.setFont("Courier-Bold", 14)
        c.drawString(x + 24, 716, title)
        c.setFillColor(INK)
        c.setFont("Helvetica", 20)
        c.drawString(x + 24, 660, body)
        x += 584
    limits = ["3–10 DTE", "$5 width", "0.20–0.30 short delta", "2% risk per trade", "8% total open risk"]
    x = 96
    for item in limits:
        _card(c, x, 380, 332, 140)
        c.setFillColor(ACCENT)
        c.setFont("Helvetica", 18)
        c.drawString(x + 20, 436, item)
        x += 352
    _card(c, 96, 140, W - 192, 200)
    c.setFillColor(MUTED)
    c.setFont("Courier", 12)
    c.drawString(128, 292, "OPEN EVIDENCE")
    c.setFillColor(INK)
    c.setFont("Helvetica", 20)
    c.drawString(128, 240, "public ledger   broker receipts   43-second demo   keyless assertions")
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 16)
    c.drawString(128, 186, "First two entries remain FILLED. Only the signed-credit third entry is price-bound MATCHED.")


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    c = Canvas(str(OUT), pagesize=(W, H))
    for draw in (slide_title, slide_path, slide_invariants, slide_results, slide_rights):
        draw(c)
        c.showPage()
    c.save()
    print(OUT)


if __name__ == "__main__":
    main()
