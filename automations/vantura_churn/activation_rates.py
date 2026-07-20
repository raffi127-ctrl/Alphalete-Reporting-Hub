"""Vantura activation rates — ATTTRACKER-B2B / ACTIVATIONRATES.

Carlos's ask (Loom 2026-07-19): put an activation rate on the churn tab for
the 0-30 day and 31-60 day buckets, plus a per-rep list of both rates.

  * 31-60 day comes straight off this view's own 31-60 bucket, filtered to
    Carlos.
  * 0-30 day does NOT exist as a bucket in the view — it has to be
    reconstructed by combining the sub-30 columns ("combine all of the
    numbers from here"). Exactly which columns those are is decided from a
    real export, not from guesswork; see probe() below.

Nothing in here is wired into the daily run until probe() has been run ON
LUCY 2 and its output reviewed — the view is a saved custom view under
CARLOS's Tableau identity, so it must be pulled from his machine (the
ownerville SSO service identity does not see his rows; same reason
cdp_pull drives his real Chrome profile for the Order Log).
"""
from __future__ import annotations

import csv
import io

VIEW_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER-B2B/ACTIVATIONRATES/"
    "b804b6f8-55ed-4273-84a9-89553dd29521/CarlosLocalOfficeEXPANDEDCHURN?:iid=1")

# Direct authenticated export. Proven on ORDERLOG (2026-07-18): the plain
# dashboard .csv returns the underlying data with session cookies, which
# skips the crosstab dialog entirely — and skips having to know the
# worksheet's caption.
CSV_URL = (
    "https://us-east-1.online.tableau.com/t/sci/views/"
    "ATTTRACKER-B2B/ACTIVATIONRATES.csv?:refresh=yes")
CUSTOM_VIEW = "Carlos Local Office EXPANDED CHURN"

OWNER_PREFIX = "CARLOS HIDALGO"


def csv_urls() -> list[tuple[str, str]]:
    """(label, url) export candidates, cheapest first."""
    cv = CUSTOM_VIEW.replace(" ", "%20")
    return [
        ("custom-view", f"{CSV_URL}&:customView={cv}"),
        ("bare", CSV_URL),
    ]


def probe(page, log=print) -> dict:
    """Dump what ACTIVATION RATES actually exports, so the parser can be
    written against real columns instead of a guess.

    Reports, for each export candidate: HTTP status, row/column counts, the
    full header, every distinct value in the row-header columns (the bucket
    captions we need to identify), and the rows belonging to Carlos.
    """
    found = {}
    for label, url in csv_urls():
        try:
            r = page.context.request.get(url, timeout=300_000)
            body = r.body() or b""
            log(f"[AR {label}] status={r.status} bytes={len(body):,}")
            if r.status != 200 or len(body) < 200:
                log(f"[AR {label}] head={body[:300]!r}")
                continue
            rows = list(csv.reader(
                io.StringIO(body.decode("utf-8-sig", "replace"))))
            if not rows:
                log(f"[AR {label}] parsed 0 rows")
                continue
            hdr = [h.strip() for h in rows[0]]
            log(f"[AR {label}] {len(rows) - 1} data rows, {len(hdr)} columns")
            for i, h in enumerate(hdr):
                log(f"[AR {label}]   col{i:02d} {h!r}")

            # Distinct values per column, capped — this is what reveals the
            # bucket captions ("0-30 Day", "31-60 Day", …) and the measure
            # names, wherever Tableau decided to put them.
            for i, h in enumerate(hdr):
                vals = []
                for row in rows[1:]:
                    if i < len(row):
                        v = row[i].strip()
                        if v and v not in vals:
                            vals.append(v)
                    if len(vals) > 12:
                        break
                log(f"[AR {label}]   vals col{i:02d} {h!r}: "
                    f"{vals[:12]}{' …' if len(vals) > 12 else ''}")

            carlos = [row for row in rows[1:]
                      if any(str(c).split("\n")[0].strip().upper()
                             .startswith(OWNER_PREFIX) for c in row[:6])]
            log(f"[AR {label}] CARLOS rows: {len(carlos)}")
            for row in carlos[:40]:
                log(f"[AR {label}]   {row}")
            found[label] = {"header": hdr, "rows": len(rows) - 1,
                            "carlos_rows": len(carlos)}
        except Exception as ex:  # noqa: BLE001
            log(f"[AR {label}] ERR {str(ex)[:200]}")
    return found
