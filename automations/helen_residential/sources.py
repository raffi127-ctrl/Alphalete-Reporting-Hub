"""The three weekly email sources behind Helen Assefaw's tab.

She is a RESIDENTIAL Verizon Wireless ICD (Edge Concepts, Inc. — ownerville
13382, Falls Church VA), so she appears in NONE of the ATT-program Tableau
views and in no AppStream office. Everything on her tab comes from mail that
lands in alphaletereporting@gmail.com:

  1. RANKED Residential Telecom Tracker   anowrouzi@aptel.com     -> sales
  2. Residential Rep Count … values.xlsx  rarchey@thesmartcircle  -> headcount
  3. Headcount and Recruiting Totals      mdanesi3@gmail.com      -> funnel

ALL THREE CLOSE ON SATURDAY. The Sheet's columns close Sunday, so a source
week maps to the NEXT day's column — the same convention opt_frontier uses for
the Frontier PDFs.

Every parser here is defensive about a specific way these files have already
bitten us; the comments say which.
"""
from __future__ import annotations

import datetime as dt
import email
import re
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Dict, List, Optional

OWNER = "Helen Assefaw"
_OWNER_L = OWNER.lower()

TRACKER_SENDER = "anowrouzi@aptel.com"
TRACKER_GLOBS = ["RANKED Residential Telecom Tracker*.pdf"]
REPCOUNT_SENDER = "rarchey@thesmartcircle.com"
REPCOUNT_GLOBS = ["Residential Rep Count*.xlsx"]
RECRUITING_SENDER = "mdanesi3@gmail.com"


def to_sheet_sunday(d: dt.date) -> Optional[dt.date]:
    """Source week (Sat, sometimes Fri) -> the Sheet's WE-Sunday column.

    Returns None for any other weekday. One recruiting subject says Monday
    (11-17-2025) and a Monday is genuinely ambiguous — the week that just
    closed or the one now open, a whole column apart — so it is skipped rather
    than guessed."""
    if d.weekday() not in (4, 5, 6):        # Fri, Sat, Sun
        return None
    return d + dt.timedelta(days=(6 - d.weekday()) % 7)


# --------------------------------------------------------------- 1. sales

# Helen's row inside the MIDDLE table. The tracker page carries THREE ranked
# tables side by side — "Residential Telecom" (left), "Residential Wireless"
# (middle), "B2B" (right) — and their rows are concatenated on one text line.
# Anchoring on her name + company is what keeps a neighbouring table's numbers
# from being read as hers.
_TRACKER_ROW = re.compile(
    r"Helen Assefaw\s+Edge Concepts\s+[A-Z]{2}\s+[A-Za-z .'-]+?\s+"
    r"([\d,]+)\s+([\d,]+)\b")
_TRACKER_WEEK = re.compile(r"W\.E\. (\d{1,2})\.(\d{1,2})")


def parse_tracker(paths: List[Path], year_hint: int) -> Dict[dt.date, dict]:
    """{sheet WE-Sunday: {'units': n, 'source': str}} from the Wireless table.

    Each PDF also prints the PREVIOUS week's number, which is used to fill a
    week whose own edition never arrived (there was no W.E. 6.20 or 8.8 send).
    A '- REVISED' edition supersedes the first send of the same week."""
    import pdfplumber

    best: Dict[dt.date, tuple] = {}     # sunday -> (rank, units, source)
    for f in sorted(paths):
        if "Campaign Totals" in f.name:
            continue                    # org-level daily totals, no ICD rows
        m = _TRACKER_WEEK.search(f.name)
        if not m:
            continue
        try:
            sat = dt.date(year_hint, int(m.group(1)), int(m.group(2)))
        except ValueError:
            continue
        # The filename carries the email date as a prefix; use it to pick the
        # right year when a January edition is fetched in a December window.
        pref = re.match(r"(\d{4})-\d{2}-\d{2}_", f.name)
        if pref:
            sent_year = int(pref.group(1))
            for cand in (sent_year, sent_year - 1):
                try:
                    c = dt.date(cand, int(m.group(1)), int(m.group(2)))
                except ValueError:
                    continue
                if 0 <= (dt.date(sent_year, 12, 31) - c).days < 400:
                    sat = c
                    break
        try:
            with pdfplumber.open(f) as pdf:
                txt = "\n".join(p.extract_text() or "" for p in pdf.pages)
        except Exception:
            continue
        hit = _TRACKER_ROW.search(txt)
        if not hit:
            continue
        cur, prior = (int(x.replace(",", "")) for x in hit.groups())
        rank = 2 if "REVISED" in f.name else 1
        own = to_sheet_sunday(sat)
        if own and best.get(own, (0,))[0] <= rank:
            best[own] = (rank, cur, f"{f.name} (week ending {sat})")
        prev = to_sheet_sunday(sat - dt.timedelta(days=7))
        if prev and prev not in best:
            best[prev] = (0, prior, f"{f.name} ('previous week' column)")
    return {k: {"units": v[1], "source": v[2]} for k, v in best.items()}


# ----------------------------------------------------------- 2. headcount

_REPCOUNT_WEEK = re.compile(r"WE (\d{4}-\d{2}-\d{2})")


def parse_rep_counts(paths: List[Path]) -> Dict[dt.date, dict]:
    """{sheet WE-Sunday: {'Headcount': n, 'Existing': n, 'source': str}}."""
    import openpyxl

    out: Dict[dt.date, dict] = {}
    for f in sorted(paths):
        m = _REPCOUNT_WEEK.search(f.name)
        if not m:
            continue
        sat = dt.date.fromisoformat(m.group(1))
        sun = to_sheet_sunday(sat)
        if sun is None:
            continue
        try:
            wb = openpyxl.load_workbook(f, data_only=True, read_only=True)
        except Exception:
            continue
        for ws in wb.worksheets:
            # NOT the 'ICD Owner Snapshot (ATT RES)' variant — that slice is
            # all zeros for her, she has no ATT RES heads at all.
            if ws.title.strip().lower() != "icd owner snapshot":
                continue
            hdr, name_col = None, None
            for row in ws.iter_rows(values_only=True):
                cells = ["" if c is None else str(c).strip() for c in row]
                if hdr is None:
                    for j, c in enumerate(cells):
                        if c.lower() == "icd owner name":
                            hdr, name_col = cells, j
                            break
                    continue
                # Match the ICD OWNER NAME COLUMN only. She also shows up in
                # the `PO` column of ANOTHER ICD's row (she is program owner
                # for Leigh Allen / Takeoff Initiatives), and an any-cell match
                # returned THAT row — 9 existing / 4 headcount instead of her
                # own 48 / 56.
                if name_col is None or name_col >= len(cells):
                    continue
                if cells[name_col].lower() != _OWNER_L:
                    continue
                pairs = {h: v for h, v in zip(hdr, cells) if h}
                rec = {"source": f.name}
                for k in ("Headcount", "Existing"):
                    v = pairs.get(k, "")
                    if v not in ("", None):
                        try:
                            rec[k] = int(float(v))
                        except ValueError:
                            pass
                out[sun] = rec
                break
    return out


# ---------------------------------------------------------- 3. recruiting

# Matched against the email table's OWN header, never by position: the table
# has grown 12 -> 13 -> 18 columns since January, and column 12 is
# 'Retention CL' in one layout and an unrelated count in another. Bare
# 'Retention' appears THREE times, so each pattern is anchored on something
# unique. 'Rounds' is spelled three ways across the year ("1st Rounds Booked",
# "1st Rds Booked", "1st Rnds Booked") — a pattern that missed "Rds" silently
# dropped every week from June on.
_RDS = r"^{} r(?:ou)?n?ds? {}$"
RECRUITING_COLS = [
    (_RDS.format("1st", "booked"),   "1ST BOOKED",                          "int"),
    (_RDS.format("1st", "showed"),   "1ST SHOWED",                          "int"),
    (r"^conversion( 1st)?$",         "Retention 1st showed Booked for 2nd", "pct"),
    (_RDS.format("2nd", "booked"),   "2ND BOOKED",                          "int"),
    (_RDS.format("2nd", "showed"),   "2ND SHOWED",                          "int"),
    (r"^new starts? sched(uled)?$",  "New Starts Scheduled",                "int"),
    (r"^new starts showed$",         "New Starts Showed",                   "int"),
    (r"^retention cl$",              "Retention to Call list",              "pct"),
]

# The subject drifts: "Wk Ending 01-31-2026", "Week Ending May 23, 2026",
# "Wk Ending 06/20" (no year), "Week Ending 07-25-26", with and without colon.
_SUBJ = [
    (re.compile(r"W(?:ee)?k Ending:?\s+(\d{1,2})[-/](\d{1,2})[-/](\d{4})", re.I), "mdy4"),
    (re.compile(r"W(?:ee)?k Ending:?\s+(\d{1,2})[-/](\d{1,2})[-/](\d{2})\b", re.I), "mdy2"),
    (re.compile(r"W(?:ee)?k Ending:?\s+(\d{1,2})[-/](\d{1,2})\b", re.I), "md"),
    (re.compile(r"W(?:ee)?k Ending:?\s+([A-Za-z]+)\s+(\d{1,2}),?\s*(\d{4})?", re.I), "name"),
]
_MONTHS = {m.lower(): n for n, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], start=1)}


def subject_date(subj: str, sent: dt.date) -> Optional[dt.date]:
    for rx, kind in _SUBJ:
        m = rx.search(subj)
        if not m:
            continue
        try:
            if kind == "mdy4":
                return dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
            if kind == "mdy2":
                return dt.date(2000 + int(m.group(3)), int(m.group(1)), int(m.group(2)))
            if kind == "md":
                return dt.date(sent.year, int(m.group(1)), int(m.group(2)))
            mo = _MONTHS.get(m.group(1).lower())
            if mo:
                return dt.date(int(m.group(3)) if m.group(3) else sent.year,
                               mo, int(m.group(2)))
        except ValueError:
            continue
    return None


def _body_rows(msg) -> List[List[str]]:
    for p in msg.walk():
        if p.get_content_type() == "text/html":
            h = p.get_payload(decode=True).decode("utf-8", "replace")
            h = re.sub(r"</(td|th)>", "\t", h)
            h = re.sub(r"</tr>", "\n", h)
            body = re.sub(r"<[^>]+>", "", h)
            break
    else:
        return []
    rows = []
    for ln in body.splitlines():
        cells = [re.sub(r"\s+", " ", c).strip() for c in ln.split("\t")]
        rows.append([c for c in cells if c])
    return rows


def parse_recruiting(ids, fetch, log=print) -> Dict[dt.date, dict]:
    """{sheet WE-Sunday: {label: raw_value}} from Madilyn's weekly email.

    `fetch(i)` must return the raw RFC822 bytes for message id `i`."""
    out: Dict[dt.date, dict] = {}
    for i in ids:
        raw = fetch(i)
        if not raw:
            continue
        msg = email.message_from_bytes(raw)
        subj = str(msg.get("Subject", ""))
        try:
            sent = parsedate_to_datetime(msg["Date"]).date()
        except Exception:
            sent = dt.date.today()
        src = subject_date(subj, sent)
        if not src:
            log(f"  ? unparseable subject: {subj[:70]}")
            continue
        sun = to_sheet_sunday(src)
        if sun is None:
            log(f"  ! {src} ({src:%a}) is not Fri/Sat/Sun — ambiguous, skipped")
            continue

        hits, header = [], None
        for ne in _body_rows(msg):
            if not ne:
                continue
            if any(re.match(_RDS.format("1st", "booked"), c.lower()) for c in ne):
                header = ne
                continue
            if ne[0] == OWNER and header:
                idx = {}
                for j, name in enumerate(header[1:]):
                    n = re.sub(r"\s+", " ", name).strip().lower()
                    for rx, label, _k in RECRUITING_COLS:
                        if label not in idx and re.match(rx, n):
                            idx[label] = j
                hits.append({lab: (ne[1 + j] if 1 + j < len(ne) else "")
                             for lab, j in idx.items()})

        # She can be listed in more than one table of the same email. Those are
        # the SAME office totals repeated under a second heading, NOT two
        # campaigns to add: on WE 7/18 both read 259/138/26/10 and summing gave
        # 518/276/52/20, double every neighbouring week. Dedupe, keep one.
        uniq = []
        for v in hits:
            filled = {k: x for k, x in v.items() if str(x).strip()}
            if filled and filled not in uniq:
                uniq.append(filled)
        if not uniq:
            continue
        if len(uniq) > 1:
            log(f"  ! {src}: {len(uniq)} DIFFERENT rows for her — skipped")
            continue
        out[sun] = uniq[0]
    return out


def to_number(raw: str, kind: str):
    raw = (raw or "").strip()
    if raw in ("", "-", "–", "—"):
        return None
    if kind == "pct":
        m = re.match(r"^([\d.]+)\s*%$", raw)
        return f"{float(m.group(1)) / 100:.4f}" if m else None
    try:
        return int(float(raw.replace(",", "")))
    except ValueError:
        return None
