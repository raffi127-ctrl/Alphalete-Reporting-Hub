"""Verizon Sales Board off Credico's Sales Verification (Carlos 2026-11-07).

Megan's tracker for Nico's office (automations/verizon_office) reads Credico's
daily 'Sales Verification - Verizon Wireless - High Value Acquisitions, Inc. -
YYYYMMDD.xlsx' (vzreports@credicousa.com, ~10:45am CT, sales through
YESTERDAY) off the Hub inbox: per rep per day VALID LINES (the apps -- one
red drop on the room's tally is one line), valid sales, and 'Appr. %' (lines
with an approval date / lines). Carlos: "however she got the numbers i want
lucy to fill out our verizon salesboard with those numbers. i liked the
approved column so to the right of last weeks number add in this approved
number that lucy/megan are grabbing".

What this writes on the Vantura 'Verizon Sales Board' tab:
  * each MATCHED rep's day cells (Monday..Sunday, found by header) for every
    day the file covers inside the week the board shows -- AUTHORITATIVE like
    the BOX order-log pass: set to Credico's count, lowering included; a
    hand-typed marker (T/X/F) stays unless Credico shows lines; a blank stays
    blank when Credico shows 0. A board rep Credico does not list is left
    alone (and said so) -- a name mismatch never zeroes anyone.
  * column Q 'Approved' (header on the REP header row): the rep's 'Appr. %'
    for the Credico week whose Saturday falls in the board's week, and the
    crew's '% Appr.' on the Verizon totals row. Q is the first free column
    right of Leadership Status; the day columns, the Monday week-roll script
    and every other fill key on E:P, so nothing is inserted between Last Wk
    and Monday (that is a coordinated layout change, offered separately).
Names: Credico uses the rep's SSO legal name; a board row matches when the
first names agree (after the order-log aliases william->will, nicolas->nico
...) and the tokens are a subset either way or the last names match, or the
last names are near-identical (Jair Otero / 'Jair Ortero'), or Credico's
first name is a middle name on the board row with the same last name
(Samantha Ruiz / 'Brandy Samantha Ahumada Ruiz'). Unmatched reps are
reported, never guessed. The Slack roster fill (vantura_slack_sales) keeps
the live evening ticker; this pass corrects through yesterday late morning.

  python -m automations.vantura_verizon_credico.run --plan          # plan only
  python -m automations.vantura_verizon_credico.run --fill --yes    # write
  ... --repost       # after a write, re-post the Verizon day + week boards
                     # ('(corrected)' captions, sales_boards --corrected) into
                     # the day's Verizon Metrics thread -- Carlos 11/7: "then
                     # the screen shot sent out ... one for yesterday sales
                     # sorted highest to lowest and one for the week"
  ... --sv FILE.xlsx                                                 # local file
Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import email
import fnmatch
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from automations.vantura_boards import BOARD_TABS, _cell, board_ws, columns, stat_row

SHEET_ID = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"
TAB = BOARD_TABS["Verizon"]
OFFICE_KEY = "nicolas"                    # verizon_office.offices: High Value Acquisitions, Inc.
APPROVED_COL = 17                         # Q
APPROVED_HEADER = "Approved"
CREDICO_DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]   # parse.DAYS order
STALE_DAYS = 3                            # newest file older than this -> don't write
SINCE_DAYS = 10
# Fallback inbox: until Nico's Credico Outlook redirects to the Hub inbox, a
# copy forwarded to Carlos (any sender) is accepted -- Carlos's app password
# already lives on Lucy 2 for the double-tier reader.
CARLOS_INBOX = ("carloshidalgo349@gmail.com",
                Path.home() / ".config" / "recruiting-report" / "gmail-app-password-carloshidalgo349")

FIRST_NAME_ALIASES = {                    # = vantura_orderlog_sales.run.FIRST_NAME_ALIASES
    "william": "will",
    "nicholas": "nick",
    "nicolas": "nico",
    "jeffrey": "jeff",
}


def _log(msg: str = "") -> None:
    print(msg, flush=True)


# ------------------------------------------------------------------ names ----
def _toks(name: str) -> List[str]:
    s = str(name or "")
    if "," in s:                           # "Last, First" -> "First Last"
        last, first = s.split(",", 1)
        s = first + " " + last
    parts = re.sub(r"[^a-z0-9 ]", " ", s.lower().replace("'", "")).split()
    if parts and parts[0] in FIRST_NAME_ALIASES:
        parts[0] = FIRST_NAME_ALIASES[parts[0]]
    return parts


def match_rep(credico_name: str, board_names) -> Tuple[Optional[str], str]:
    """(board name, how) -- exact / subset / fuzzy last name / middle name;
    (None, '') when no single row fits."""
    ct = _toks(credico_name)
    if not ct:
        return None, ""
    exact = [b for b in board_names if _toks(b) == ct]
    if len(exact) == 1:
        return exact[0], "exact"
    subset, fuzzy, middle = [], [], []
    for b in board_names:
        bt = _toks(b)
        if not bt:
            continue
        if bt[0] == ct[0]:
            if set(bt) <= set(ct) or set(ct) <= set(bt) or bt[-1] == ct[-1]:
                subset.append(b)
            elif difflib.SequenceMatcher(None, bt[-1], ct[-1]).ratio() >= 0.8:
                fuzzy.append(b)
        elif ct[0] in bt[1:] and bt[-1] == ct[-1]:
            middle.append(b)
    if len(subset) == 1:
        return subset[0], "subset"
    if not subset and len(fuzzy) == 1:
        return fuzzy[0], "fuzzy last name"
    if not subset and not fuzzy and len(middle) == 1:
        return middle[0], "middle name"
    return None, ""


# ------------------------------------------------------------------ board ----
def shown_week(grid, today: dt.date) -> Tuple[Optional[dt.date], Optional[dt.date], str]:
    """(monday, sunday, text) of the week the board shows -- the WE cell B2
    ('11.8' = Sunday 11/8; a dropdown number can lose a trailing zero: '8.3'
    may be 8/30)."""
    text = _cell(grid, 2, 2)
    m = re.match(r"^\s*(\d{1,2})\.(\d{1,2})\s*$", text)
    if not m:
        return None, None, text
    month, day = int(m.group(1)), int(m.group(2))
    cands = []
    for year in (today.year - 1, today.year, today.year + 1):
        for d in (day, day * 10):
            try:
                c = dt.date(year, month, d)
            except ValueError:
                continue
            if c.weekday() == 6 and abs((c - today).days) <= 60:
                cands.append(c)
    if not cands:
        return None, None, text
    sunday = min(cands, key=lambda c: abs((c - today).days))
    return sunday - dt.timedelta(days=6), sunday, text


def rep_rows(grid) -> Dict[str, int]:
    """{board name: row} for the Verizon rep block (header+1 .. totals-1)."""
    cols = columns(grid)
    end = stat_row(grid)
    out = {}
    for r in range(cols["header_row"] + 1, end):
        name = _cell(grid, r, cols["name"])
        if name:
            out[name] = r
    return out


def _pct(v) -> str:
    try:
        return "%d%%" % round(float(v or 0) * 100)
    except (TypeError, ValueError):
        return ""


def plan(grid, sv, today: dt.date, log=_log) -> Tuple[List[tuple], List[str]]:
    """-> ([(label, A1, old, new, note)], problems). Pure: no IO."""
    from gspread.utils import rowcol_to_a1
    cols = columns(grid)
    rows = rep_rows(grid)
    monday, sunday, we_text = shown_week(grid, today)
    if monday is None:
        return [], ["the board's week cell reads %r -- can't place the days" % we_text]
    through = sv.through
    log("[vz] board shows WE %s (%s..%s); Credico file through %s"
        % (we_text, monday, sunday, through))

    # Credico reps -> board rows (newest week first names the match)
    matched: Dict[str, str] = {}
    unmatched: List[str] = []
    for wk in sv.weeks[:2]:
        for rep in wk.reps:
            if rep.name in matched or rep.name in unmatched:
                continue
            b, how = match_rep(rep.name, rows)
            if b:
                matched[rep.name] = b
                if how != "exact":
                    log("[vz]   %s -> %s (%s)" % (rep.name, b, how))
            else:
                unmatched.append(rep.name)

    out: List[tuple] = []
    changed_days = 0
    for wk in sv.weeks:
        start = wk.end - dt.timedelta(days=6)           # Credico's Sunday
        for i, dname in enumerate(CREDICO_DAYS):
            day = start + dt.timedelta(days=i)
            if day < monday or day > sunday:
                continue
            if through is not None and day > through:
                continue
            col = cols["days"][day.weekday()]
            for rep in wk.reps:
                b = matched.get(rep.name)
                if not b:
                    continue
                row = rows[b]
                new = int(rep.days.get(dname, 0) or 0)
                cur = _cell(grid, row, col)
                note = ""
                if cur.isdigit():
                    if new == int(cur):
                        continue
                    if new < int(cur):
                        note = "  (LOWERED to Credico -- Slack overcount)"
                elif cur:
                    if not new:
                        continue              # keep the marker (T/X/F)
                    note = "  (replaces marker %r)" % cur
                elif not new:
                    continue                  # blank stays blank
                out.append((b, rowcol_to_a1(row, col), cur or "(blank)", str(new), note))
                changed_days += 1

    # Approved column
    problems: List[str] = []
    hr = cols["header_row"]
    head = _cell(grid, hr, APPROVED_COL)
    if head and head.lower() != APPROVED_HEADER.lower():
        problems.append("column %s is not free (header %r) -- Approved not written"
                        % (rowcol_to_a1(hr, APPROVED_COL), head))
    else:
        if not head:
            out.append(("(header)", rowcol_to_a1(hr, APPROVED_COL), "(blank)", APPROVED_HEADER, ""))
        wk = next((w for w in sv.weeks if monday <= w.end <= sunday), None)
        want: Dict[int, str] = {}
        if wk is not None:
            for rep in wk.reps:
                b = matched.get(rep.name)
                if b:
                    want[rows[b]] = _pct(rep.vals.get("Appr. %"))
            ov = next((o for o in sv.overview if o.get("Week End Date") == wk.end), None)
            srow = stat_row(grid)
            if ov is not None and srow <= len(grid):
                want[srow] = _pct(ov.get("% Appr."))
        else:
            log("[vz]   no Credico week ends inside the board's week yet -- Approved cleared")
        targets = list(rows.values()) + ([stat_row(grid)] if stat_row(grid) <= len(grid) else [])
        label = {r: n for n, r in rows.items()}
        for row in targets:
            new = want.get(row, "")
            cur = _cell(grid, row, APPROVED_COL)
            if cur != new:
                out.append((label.get(row, "(crew)"), rowcol_to_a1(row, APPROVED_COL),
                            cur or "(blank)", new or "(clear)", ""))

    for name in unmatched:
        problems.append("Credico rep %r matches no Verizon board row -- not written" % name)
    not_listed = [b for b in rows if b not in matched.values()]
    if not_listed:
        log("[vz]   on the board, not in Credico's file (days left alone): " + ", ".join(not_listed))
    log("[vz] %d day cell(s) to change" % changed_days)
    return out, problems


def apply(ws, items: List[tuple]) -> int:
    from automations.recruiting_report.fill import _retry
    data = [{"range": a1, "values": [["" if new == "(clear)" else new]]}
            for _lbl, a1, _old, new, _n in items]
    if not data:
        return 0
    _retry(lambda: ws.batch_update(data, value_input_option="USER_ENTERED"))
    return len(data)


# ------------------------------------------------------------------ fetch ----
def _newest_attachment(M, glob: str, since_days: int, dest: Path,
                       subject: str = "Sales Verification") -> Optional[Path]:
    """Newest attachment matching `glob` on a message whose subject carries
    `subject`, any sender (a forward keeps the file name). `M` is an open
    imaplib connection (or anything with search/fetch)."""
    from automations.shared.email_ingest import _filename, _safe_name
    since = (dt.date.today() - dt.timedelta(days=since_days)).strftime("%d-%b-%Y")
    _typ, data = M.search(None, '(SUBJECT "%s" SINCE "%s")' % (subject, since))
    for i in reversed((data[0] or b"").split()):
        _typ, raw = M.fetch(i, "(RFC822)")
        if not raw or not raw[0]:
            continue
        msg = email.message_from_bytes(raw[0][1])
        for part in msg.walk():
            fn = _filename(part)
            if fn and fnmatch.fnmatch(fn.lower(), glob.lower()):
                dest.mkdir(parents=True, exist_ok=True)
                out = dest / _safe_name(fn)
                out.write_bytes(part.get_payload(decode=True))
                return out
    return None


def fetch_from_carlos_inbox(office, log=_log) -> Optional[Path]:
    account, pw_path = CARLOS_INBOX
    if not pw_path.exists():
        log("[vz]   (no app password for %s on this box -- fallback inbox skipped)" % account)
        return None
    import imaplib
    from automations.shared.email_ingest import IMAP_HOST
    glob = "Sales Verification - Verizon Wireless - %s*.xlsx" % office.office
    M = imaplib.IMAP4_SSL(IMAP_HOST)
    M.login(account, pw_path.read_text(encoding="utf-8-sig").strip().replace(" ", ""))
    try:
        M.select('"[Gmail]/All Mail"', readonly=True)
        return _newest_attachment(M, glob, SINCE_DAYS,
                                  Path(tempfile.gettempdir()) / ("vantura_verizon_credico_" + office.key))
    finally:
        M.logout()


def fetch(office, log=_log) -> Tuple[Optional[Path], str]:
    """(path, source): the Hub inbox first (Credico as sender -- the Outlook
    redirect), then Carlos's inbox (a forward from Nico or Credico CC)."""
    from automations.verizon_office import run as VRUN
    path = VRUN.fetch(office, "sales", since_days=SINCE_DAYS)
    if path:
        return Path(path), "Hub inbox (alphaletereporting, from Credico)"
    path = fetch_from_carlos_inbox(office, log=log)
    if path:
        return path, "Carlos's inbox (%s)" % CARLOS_INBOX[0]
    return None, ""


REPOST_CMD = ["-m", "automations.sales_boards.run", "--program", "Verizon", "--post", "--corrected"]


def repost_boards(log=_log) -> int:
    """Re-post yesterday's Verizon day board + the week ranking with
    '(corrected)' captions (sales_boards dedupes by caption, so the 5:10
    replies stay and these land beside them). Returns the exit code."""
    log("[vz] re-posting the Verizon boards: python " + " ".join(REPOST_CMD))
    r = subprocess.run([sys.executable] + REPOST_CMD, capture_output=True, text=True)
    for line in (r.stdout or "").splitlines()[-25:]:
        log("    | " + line)
    if r.returncode:
        for line in (r.stderr or "").splitlines()[-10:]:
            log("    ! " + line)
        log("[vz] board re-post FAILED (exit %d)" % r.returncode)
    return r.returncode


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="vantura_verizon_credico")
    ap.add_argument("--sv", type=Path, default=None, help="local Sales Verification xlsx")
    ap.add_argument("--fill", action="store_true")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--plan", action="store_true",
                    help="plan only, even with --fill --yes (a rerun carries them)")
    ap.add_argument("--repost", action="store_true",
                    help="after a write, re-post the Verizon day + week boards (corrected)")
    ap.add_argument("--today", default=None)
    a = ap.parse_args(argv)
    today = dt.date.fromisoformat(a.today) if a.today else dt.date.today()

    from automations.verizon_office import offices as OF, parse as VP
    office = OF.get(OFFICE_KEY)
    if a.sv:
        path, source = Path(a.sv), "local file"
    else:
        path, source = fetch(office, log=_log)
    if not path:
        _log("[vz] SKIP -- no '%s' Sales Verification in the Hub inbox or Carlos's inbox "
             "(last %d days). Until Nico's Credico Outlook redirects to alphaletereporting@gmail.com "
             "(workflows/verizon-icd-onboarding.md) or a copy is forwarded to Carlos, the Slack "
             "numbers stand." % (office.office, SINCE_DAYS))
        print("=== done ===", flush=True)
        return 0
    sv = VP.read_sales_verification(Path(path))
    _log("[vz] %s from %s: %d week block(s), newest WE %s, through %s"
         % (Path(path).name, source, len(sv.weeks), sv.weeks[0].end if sv.weeks else "-", sv.through))
    if sv.through and (today - sv.through).days > STALE_DAYS:
        _log("[vz] SKIP -- newest file is stale (through %s) -- not writing" % sv.through)
        print("=== done ===", flush=True)
        return 0

    from automations.recruiting_report.fill import open_by_key, _retry
    sh = open_by_key(SHEET_ID)
    ws = board_ws(sh, "Verizon")
    grid = _retry(lambda: ws.get_all_values())
    items, problems = plan(grid, sv, today, log=_log)
    for lbl, a1, old, new, note in items:
        _log("  %-28s %-5s %-8s -> %s%s" % (lbl[:28], a1, old, new, note))
    for p in problems:
        _log("  ! " + p)
    if not items:
        _log("[vz] board already matches Credico")
    elif a.fill and a.yes and not a.plan:
        n = apply(ws, items)
        _log("[vz] wrote %d cell(s) on '%s'" % (n, ws.title))
        if a.repost and n and repost_boards(log=_log):
            print("=== done ===", flush=True)
            return 2
    else:
        _log("[vz] PLAN ONLY -- %d cell(s) would change (--fill --yes to write)" % len(items))
    print("=== done ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
