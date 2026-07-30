"""Sunday standings email for the August Owner Showdown.

Cadence (Raf, 2026-07-29): one update email each Sunday (Sunday is when the
most up-to-date headcount is pulled), to RAF ONLY. First email Sun Aug 2,
last Sun Aug 30. The sheet itself updates daily (personal) / Sundays (rep).

This module BUILDS the email (subject + HTML + text). It does NOT send —
sending is gated on Raf's OK and wired to the report runner at go-live.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Tuple

TO_EMAIL = "raffi127@gmail.com"                 # Raf (confirmed 7/29)
CC_EMAILS = ["meganhidalgo1191@gmail.com"]      # Megan — CC to confirm delivery
SHEET_URL = ("https://docs.google.com/spreadsheets/d/"
             "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E/edit?gid=893154737")


def _rows_html(rows: List[Tuple[int, str, object]], value_label: str) -> str:
    body = []
    for rank, name, val in rows:
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"{rank}.")
        body.append(
            f"<tr><td style='padding:4px 10px 4px 0'>{medal}</td>"
            f"<td style='padding:4px 12px 4px 0;font-family:Georgia,serif'>"
            f"{name}</td>"
            f"<td style='padding:4px 0;text-align:right;font-weight:700'>"
            f"{val}</td></tr>")
    return (f"<table style='border-collapse:collapse'>"
            f"<tr><td></td><td style='color:#888;font-size:12px'>OWNER</td>"
            f"<td style='color:#888;font-size:12px;text-align:right'>"
            f"{value_label}</td></tr>{''.join(body)}</table>")


def build(sales_rows: List[Tuple[int, str, object]],
          rep_rows: List[Tuple[int, str, object]],
          run_date: dt.date) -> Dict[str, str]:
    """sales_rows / rep_rows: [(rank, name, value)] already sorted high→low.
    Returns {subject, html, text}."""
    ds = f"{run_date:%b} {run_date.day}"   # e.g. "Aug 2" — no %-d (Windows-safe)
    subject = f"🏆 August Owner Showdown — standings ({ds})"

    html = (
        f"<div style='font-family:Arial,sans-serif;max-width:560px'>"
        f"<h2 style='margin:0 0 2px'>🏆 August Owner Showdown</h2>"
        f"<div style='color:#666;margin-bottom:16px'>Standings as of {ds} · "
        f"$5,000 to each winner</div>"
        f"<h3 style='margin:18px 0 6px'>💻 Personal Sales "
        f"<span style='color:#888;font-weight:400'>(new-internet, month-to-date)"
        f"</span></h3>{_rows_html(sales_rows, 'NEW INT')}"
        f"<h3 style='margin:22px 0 6px'>📈 Rep Count Growth "
        f"<span style='color:#888;font-weight:400'>(vs. Aug 2 baseline)</span>"
        f"</h3>{_rows_html(rep_rows, 'GROWTH')}"
        f"<div style='margin-top:22px'><a href='{SHEET_URL}'>Open the live "
        f"tracker →</a></div></div>")

    def _txt(rows):
        return "\n".join(f"  {r}. {n} — {v}" for r, n, v in rows)
    text = (f"August Owner Showdown — standings as of {ds}\n\n"
            f"PERSONAL SALES (new-internet, MTD):\n{_txt(sales_rows)}\n\n"
            f"REP COUNT GROWTH (vs Aug 2):\n{_txt(rep_rows)}\n\n"
            f"Live tracker: {SHEET_URL}")
    return {"subject": subject, "html": html, "text": text}
