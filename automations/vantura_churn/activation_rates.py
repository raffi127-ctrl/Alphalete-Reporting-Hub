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


# ------------------------------------------------------------------ parsing
# Confirmed shape (probe on Lucy 2, 2026-07-19): 7 columns, one row per
# Owner & Office × bucket, 325 rows.
COLS = {
    "bucket": "Activation Bucket",
    "owner": "Owner & Office",
    "color": "Activation Color",          # Tableau's own banding — NOT ours
    "activated": "Sales (All)  (activations)",   # numerator (note: 2 spaces)
    "rate": "Sales (All) Activation Rate",
    "sold": "Sales (All)",                # denominator
}
BUCKETS_0_30 = ["0-7 Days", "8-14 Days", "15-30 Days"]
BUCKET_31_60 = "31-60 Days"


def _num(v):
    s = str(v or "").replace(",", "").replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _owner_name(v: str) -> str:
    """'CARLOS HIDALGO\\r [alphalete …]' → 'CARLOS HIDALGO'. The member carries
    an embedded CR (not LF) before the office suffix in this view."""
    return str(v or "").replace("\r", "\n").split("\n")[0].strip().upper()


def parse_rates(rows: list, owner_prefix: str = OWNER_PREFIX) -> dict:
    """One owner's activation rates, as {'0-30': {...}, '31-60': {...}}.

    The view has NO 0-30 bucket, so it is rebuilt by summing the three
    sub-30 buckets — numerator and denominator summed SEPARATELY, then
    divided. Averaging the three published rates would silently weight a
    7-day bucket the same as a 291-sale one.
    """
    hdr = [str(h).strip() for h in rows[0]]
    missing = [c for c in COLS.values() if c not in hdr]
    if missing:
        raise RuntimeError(
            f"ACTIVATION RATES export missing columns: {missing}. "
            f"Got: {hdr}")
    ix = {k: hdr.index(c) for k, c in COLS.items()}

    mine = {}
    for r in rows[1:]:
        if len(r) <= max(ix.values()):
            continue
        if not _owner_name(r[ix["owner"]]).startswith(owner_prefix.upper()):
            continue
        mine[str(r[ix["bucket"]]).strip()] = r
    if not mine:
        raise RuntimeError(
            f"ACTIVATION RATES: no rows for owner {owner_prefix!r} — wrong "
            "export or the owner's name changed in Tableau.")

    def _bucket(names: list) -> dict:
        act = sold = 0.0
        seen = []
        for n in names:
            r = mine.get(n)
            if r is None:
                continue
            a, s = _num(r[ix["activated"]]), _num(r[ix["sold"]])
            if a is None or s is None:
                continue
            act += a
            sold += s
            seen.append(n)
        got = [n for n in names if n in mine]
        if sorted(got) != sorted(names):
            raise RuntimeError(
                f"ACTIVATION RATES: expected buckets {names} for "
                f"{owner_prefix}, found {sorted(mine)}. Refusing to report a "
                "rate built from a partial set of buckets.")
        return {"activated": int(act), "sold": int(sold),
                "rate": (act / sold) if sold else None, "buckets": seen}

    out = {"0-30": _bucket(BUCKETS_0_30), "31-60": _bucket([BUCKET_31_60])}
    # Cross-check the 31-60 figure against the rate Tableau publishes; a
    # mismatch means the columns moved under us.
    pub = _num(mine[BUCKET_31_60][ix["rate"]])
    if pub is not None and out["31-60"]["rate"] is not None:
        if abs(pub - out["31-60"]["rate"]) > 0.0005:
            raise RuntimeError(
                f"ACTIVATION RATES: 31-60 computed "
                f"{out['31-60']['rate']:.4f} but the view publishes "
                f"{pub:.4f} — numerator/denominator columns disagree.")
    return out


def list_sheets(page, view_url: str, log=print) -> list:
    """Worksheet captions available in this view's Crosstab dialog.

    Discovered rather than guessed: ask for a sheet name that cannot exist
    and read the caption list out of drive_crosstab_dialog's error, which
    reports everything it saw. Beats guessing a caption from the URL slug.
    """
    from automations.recruiting_report.opt_phase import drive_crosstab_dialog
    from pathlib import Path as _P
    import re as _re
    try:
        drive_crosstab_dialog(page, view_url, "__no_such_sheet__",
                              _P("/tmp/_ar_enum.csv"), verbose=False)
    except RuntimeError as ex:
        m = _re.search(r"thumb\(s\): (\[.*\])", str(ex), _re.S)
        if m:
            try:
                import ast
                sheets = ast.literal_eval(m.group(1))
                log(f"[AR sheets] {len(sheets)} worksheet(s): {sheets}")
                return list(sheets)
            except Exception:
                pass
        log(f"[AR sheets] could not enumerate: {str(ex)[:200]}")
    except Exception as ex:  # noqa: BLE001
        log(f"[AR sheets] enumerate ERR {str(ex)[:200]}")
    return []


def probe_view(page, view_url: str, log=print) -> dict:
    """Full shape probe for ONE activation-rates view URL: enumerate its
    worksheets, download each, and report columns + Carlos's rows. Used to
    tell competing custom views apart (does this one break out by Rep?)."""
    from automations.vantura_churn import compute
    from pathlib import Path as _P

    out = {}
    sheets = list_sheets(page, view_url, log=log)
    for sheet in sheets:
        dst = _P(f"/tmp/_ar_{_safe(sheet)}.csv")
        try:
            from automations.shared.tableau_patchright import (
                download_crosstab_patchright)
            download_crosstab_patchright(view_url, sheet, dst, page=page,
                                         verbose=False)
            grid = compute._load_grid(dst)
            hdr = [str(h or "").strip() for h in (grid[0] if grid else [])]
            log(f"[AR sheet {sheet!r}] {len(grid) - 1} rows, "
                f"{len(hdr)} cols: {hdr}")
            has_rep = [h for h in hdr if "rep" in h.lower()]
            log(f"[AR sheet {sheet!r}] REP-LIKE COLUMNS: {has_rep or 'NONE'}")
            mine = [r for r in grid[1:]
                    if any(_owner_name(c).startswith(OWNER_PREFIX)
                           for c in r[:6] if c)]
            log(f"[AR sheet {sheet!r}] CARLOS rows: {len(mine)}")
            for r in mine[:25]:
                log(f"[AR sheet {sheet!r}]   "
                    f"{[str(c)[:28] for c in r if c is not None]}")
            out[sheet] = {"header": hdr, "rows": len(grid) - 1,
                          "rep_columns": has_rep, "carlos_rows": len(mine)}
        except Exception as ex:  # noqa: BLE001
            log(f"[AR sheet {sheet!r}] ERR {str(ex)[:200]}")
    return out


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in str(s))[:40]


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
