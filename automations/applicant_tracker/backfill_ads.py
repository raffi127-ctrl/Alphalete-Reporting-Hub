"""ONE-SHOT REPAIR: fill the blank Ad (Call List col I) on the rows imported
while N_CALL_COLS was 7.

WHY THIS EXISTS: the "Sent to Call List" detail table has 8 data cols (First,
Last, Email, Phone, Rating, Job Board, Date and Time, Ad) and the scrape asked
for 7, so the Ad was sliced off and never reached col I. Fixed in 7885ab5, but
every row already imported that way (2026-07-28 .. 07-30, ~3,200 rows) still has
a blank Ad. Going forward the morning phase fills it; this fills the past.

HOW IT'S SAFE — the rules Megan set for touching existing data:
  * MATCHES BY CONTENT, NOT ROW POSITION. A sheet row is paired with a scraped
    row by applicant identity (first, last, email, phone, date-and-time) within
    the same owner. Row numbers are only ever the DESTINATION of a match.
  * WRITES COLUMN I AND NOTHING ELSE, and only where I is already blank. A row
    that already has an Ad is never in the candidate set, so it can't be
    rewritten. Cells that don't match are left blank rather than guessed at.
  * Rating is deliberately NOT part of the identity key: recruiters change
    ratings after the fact, so today's scrape can disagree with what was
    imported — that's a stale field, not a different person.
  * --dry-run does the whole thing (browser included) and writes nothing.

USAGE (on Lucy 1, which holds the warm rcaptain ApplicantStream session):
    lucy rerun applicant_ad_backfill --dry-run
    lucy rerun applicant_ad_backfill
Defaults to 2026-07-28..2026-07-30; pass --date YYYY-MM-DD (repeatable) for
another day. All three default dates sit in the CURRENT Sun-Sat retention week,
so one report load per office serves them all.
"""
from __future__ import annotations  # Lucy 1 / mini run Python 3.9

import argparse
import datetime as dt
import time

from . import config
from . import sheets
from .applicantstream import OfficeNotAvailable, session

CARD_ID = "applicant-tracker-sync"

# The days imported by the truncated scrape (first broken import = the 7/29
# morning run, which reads 7/28; last = the 7/31 run, which reads 7/30).
DEFAULT_DATES = ["2026-07-28", "2026-07-29", "2026-07-30"]

L_CALL_LIST = "Sent to Call List"
N_CALL_COLS = 8          # keep in step with run.N_CALL_COLS
AD_IDX = 7               # last data col = the Ad
COL_DATE = 8             # sheet col H
COL_AD = 9               # sheet col I


def date_header_for(target: dt.date) -> str:
    """'Jul 28, 2026' — the retention grid's column header. Built without
    '%-d' (not portable to Windows; house rule)."""
    return "{} {}, {}".format(target.strftime("%b"), target.day, target.year)


def _norm(s) -> str:
    return " ".join((s or "").split()).strip().lower()


def _ident(first, last, email, phone, when) -> tuple:
    """Identity of one applicant row. Rating and Job Board are left out on
    purpose — Rating is mutable, and Job Board adds nothing an email+phone+
    timestamp doesn't already pin down."""
    return (_norm(first), _norm(last), _norm(email),
            "".join(ch for ch in (phone or "") if ch.isdigit()), _norm(when))


def _sheet_date(cell: str) -> str:
    """'07/28/2026 1:07 AM' -> '2026-07-28' (or '' if unparseable)."""
    head = (cell or "").strip().split(" ")[0]
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return dt.datetime.strptime(head, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


# ---- step 1: what needs filling -----------------------------------------
def find_candidates(ws, want_dates):
    """Rows whose Date-and-Time falls on a target date AND whose Ad is blank.
    Reads the WHOLE column, never a fixed window [[feedback_fixed_window_lookups]]."""
    dates = ws.col_values(COL_DATE)
    ads = ws.col_values(COL_AD)
    rows = []
    for i, cell in enumerate(dates, start=1):
        if i == 1:
            continue  # header
        if _sheet_date(cell) not in want_dates:
            continue
        ad = ads[i - 1] if i - 1 < len(ads) else ""
        if (ad or "").strip():
            continue  # already has an Ad — never touched
        rows.append(i)
    return rows


def load_rows(ws, rownums):
    """Fetch A..I for the candidate rows (one pull over their span)."""
    if not rownums:
        return {}
    lo, hi = min(rownums), max(rownums)
    block = ws.get("A{}:I{}".format(lo, hi))
    out = {}
    want = set(rownums)
    for off, row in enumerate(block):
        n = lo + off
        if n not in want:
            continue
        row = list(row) + [""] * (9 - len(row))
        out[n] = row
    return out


# ---- step 2: what the site says today ------------------------------------
def scrape_ads(app, office_ids, targets, log=print):
    """Everything the site lists for the target dates, as consumable entries:
        entries   [{owner, ident, email, ad, used}]
        index     (owner, ident) -> [entry]      exact identity, same owner
        by_ident  ident          -> [entry]      identity across owners
        by_email  email          -> [entry]      the drift-tolerant fallback
    plus the offices that couldn't be read. ONE report load per office serves
    all the dates — scrape_at navigates away, so every href is collected from
    that single load first."""
    entries = []
    index = {}
    by_ident = {}
    by_email = {}
    skipped = []
    for office_id in office_ids:
        try:
            owner = app.select_office(office_id)
            app.open_retention_details()
            # Collect every href from the ONE loaded report first — scrape_at
            # navigates away, so hrefs must be gathered before any visit.
            hrefs = []
            for target in targets:
                header = date_header_for(target)
                hrefs.append((header, app.detail_href(L_CALL_LIST, header)))
            found = 0
            for header, href in hrefs:
                if not href:
                    log("  [{}] {}: no Call List link for {}".format(
                        office_id, owner, header))
                    continue
                for r in app.scrape_at(href, N_CALL_COLS):
                    r = list(r) + [""] * (N_CALL_COLS - len(r))
                    ad = (r[AD_IDX] or "").strip()
                    if not ad:
                        continue
                    key = _ident(r[0], r[1], r[2], r[3], r[6])
                    e = {"owner": _norm(owner), "ident": key,
                         "email": _norm(r[2]), "ad": ad, "used": False}
                    entries.append(e)
                    index.setdefault((e["owner"], key), []).append(e)
                    by_ident.setdefault(key, []).append(e)
                    if e["email"]:
                        by_email.setdefault(e["email"], []).append(e)
                    found += 1
            log("  [{}] {}: {} ad(s) read".format(office_id, owner, found))
        except OfficeNotAvailable as e:
            skipped.append((str(office_id), "no access: {}".format(e)))
            log("  ⛔ [{}] NO ACCESS: {}".format(office_id, e))
        except Exception as e:  # noqa: BLE001 — one office must not sink the rest
            skipped.append((str(office_id), "{}: {}".format(
                type(e).__name__, str(e)[:100])))
            log("  ! [{}] error: {}: {}".format(
                office_id, type(e).__name__, str(e)[:120]))
    return {"entries": entries, "index": index,
            "by_ident": by_ident, "by_email": by_email}, skipped


# ---- step 3: pair them up -------------------------------------------------
def _take(pool):
    """First unconsumed entry in a pool (each scraped Ad is handed out once)."""
    for e in pool or []:
        if not e["used"]:
            return e
    return None


def match(scrape, rows):
    """Pair each candidate sheet row with a scraped Ad. Returns
    (fills {rownum: ad}, notes [(rownum, reason, identity)]).

    Three ways to pair, strongest first:
      1. (owner, identity) — the normal case.
      2. identity alone, when the owner string drifted since the import.
      3. EMAIL alone, when the record itself was edited after the import (a
         recruiter fixing a name, a corrected phone). Email is unique per
         applicant here, so this is a real match, not a guess — but it only
         fires when exactly one unconsumed ad carries that email, and it's
         reported so the count is auditable.
    Anything left is deliberately NOT guessed at: the row stays blank.

    Two applicants can share an identity (the same person applying to two ads in
    the same minute). Those rows are indistinguishable from each other, so the
    ads are handed out in order — the multiset lands correct even though no
    single pairing is provable."""
    index, by_ident = scrape["index"], scrape["by_ident"]
    by_email = scrape["by_email"]
    fills, notes = {}, []
    for n in sorted(rows):
        row = rows[n]
        owner = _norm(row[0])
        key = _ident(row[1], row[2], row[3], row[4], row[7])
        email = _norm(row[3])

        e = _take(index.get((owner, key)))
        if e is None:
            alt = by_ident.get(key) or []
            owners = set(x["owner"] for x in alt)
            if len(owners) == 1:
                e = _take(alt)
                if e is not None:
                    notes.append((n, "FILLED — owner string drifted; matched on "
                                     "identity", key))
            elif len(owners) > 1:
                notes.append((n, "ambiguous: same applicant under {} owners"
                                 .format(len(owners)), key))
                continue
        if e is None and email:
            same = [x for x in (by_email.get(email) or []) if not x["used"]]
            if len(same) == 1:
                e = same[0]
                notes.append((n, "FILLED — record edited since import; matched "
                                 "on email", key))
            elif len(same) > 1:
                notes.append((n, "ambiguous: {} unclaimed ads share this email"
                                 .format(len(same)), key))
                continue
        if e is None:
            # Nothing on that day's detail page carries this applicant — they
            # were taken off the call list after the import (dedup / removed
            # from process). The Ad is not recoverable from this source.
            seen = bool(by_email.get(email)) if email else False
            notes.append((n, "not on that day's detail page any more"
                             + (" (all their ads already claimed)" if seen
                                else " — applicant removed since import"), key))
            continue
        e["used"] = True
        fills[n] = e["ad"]
    return fills, notes


def _runs(rownums):
    """Consecutive rows -> (start, end) ranges, so the write touches only the
    cells being filled (never a block that spans rows we must not disturb)."""
    out = []
    for n in sorted(rownums):
        if out and n == out[-1][1] + 1:
            out[-1][1] = n
        else:
            out.append([n, n])
    return [(a, b) for a, b in out]


def write_ads(ws, fills, log=print):
    """Write column I only, in contiguous runs. RAW so an Ad that starts with
    '[' or '=' lands as the literal text it is.

    ONE batched request per chunk of runs, NOT one request per run: the rows
    that can't be filled break the span into ~190 runs, and 190 back-to-back
    ws.update() calls tripped Sheets' 'write requests per minute per user' cap
    mid-run (429, 2026-07-31) — leaving the repair half-done. batch_update
    sends them as a single write. Re-running is safe either way: only blank-Ad
    rows are ever candidates, so anything already filled is skipped."""
    if not fills:
        return 0
    payload = []
    for start, end in _runs(list(fills)):
        payload.append({"range": "I{}:I{}".format(start, end),
                        "values": [[fills[n]] for n in range(start, end + 1)]})
    written = sum(len(p["values"]) for p in payload)
    if sheets.DRY_RUN:
        log("    [dry-run] would write {} cell(s) across {} run(s) in {} "
            "batched request(s)".format(
                written, len(payload), (len(payload) + 199) // 200))
        return written
    for i in range(0, len(payload), 200):
        chunk = payload[i:i + 200]
        for attempt in range(5):
            try:
                ws.batch_update(chunk, value_input_option="RAW")
                break
            except Exception as e:  # noqa: BLE001 — 429/503 are worth waiting out
                if "429" not in str(e) and "Quota" not in str(e) and attempt == 0:
                    raise
                if attempt == 4:
                    raise
                wait = 20 * (attempt + 1)
                log("    (write throttled: retrying in {}s)".format(wait))
                time.sleep(wait)
        log("    wrote {} cell(s) [{} of {} run(s)]".format(
            sum(len(c["values"]) for c in chunk),
            min(i + 200, len(payload)), len(payload)))
    return written


def run(dates=None, office_ids=None) -> None:
    want = list(dates or DEFAULT_DATES)
    targets = [dt.date.fromisoformat(d) for d in want]
    offices = list(office_ids or config.OFFICE_IDS)
    print("=== Call List Ad backfill: {} ({} offices){} ===".format(
        ", ".join(want), len(offices), " [DRY-RUN]" if sheets.DRY_RUN else ""))

    ws = sheets.open_tab(config.TAB_CALL_LIST)
    rownums = find_candidates(ws, set(want))
    print("Blank-Ad rows on those dates: {}".format(len(rownums)))
    if not rownums:
        print("Nothing to fill.")
        return
    rows = load_rows(ws, rownums)

    print("Re-scraping ApplicantStream...")
    with session() as app:
        scrape, skipped = scrape_ads(app, offices, targets)
    print("Ads read from the site: {}".format(len(scrape["entries"])))

    fills, notes = match(scrape, rows)
    written = write_ads(ws, fills)

    print("\n--- RESULT ---")
    print("Rows needing an Ad : {}".format(len(rownums)))
    print("Ads written        : {}{}".format(
        written, " (dry-run, nothing sent)" if sheets.DRY_RUN else ""))
    unfilled = [m for m in notes if not m[1].startswith("FILLED")]
    noted = [m for m in notes if m[1].startswith("FILLED")]
    if noted:
        print("Filled with a note : {}".format(len(noted)))
        kinds = {}
        for _, why, _k in noted:
            kinds[why] = kinds.get(why, 0) + 1
        for why, cnt in sorted(kinds.items(), key=lambda kv: -kv[1]):
            print("  • {} row(s): {}".format(cnt, why))
    print("Still unfilled     : {}".format(len(unfilled)))
    reasons = {}
    for _, why, _k in unfilled:
        reasons[why.split(" (")[0]] = reasons.get(why.split(" (")[0], 0) + 1
    for why, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print("  • {} row(s): {}".format(n, why))
    for n, why, key in unfilled[:15]:
        print("    row {}: {} {} <{}> — {}".format(
            n, key[0], key[1], key[2], why))
    if len(unfilled) > 15:
        print("    … and {} more".format(len(unfilled) - 15))
    if skipped:
        print("Offices not read   : {}".format(len(skipped)))
        for oid, why in skipped:
            print("  • {}: {}".format(oid, why))

    # Re-read and confirm, rather than trusting the write. [[feedback_read_actual_content]]
    if not sheets.DRY_RUN:
        left = find_candidates(ws, set(want))
        print("\nVERIFY (re-read): {} blank-Ad row(s) remain on {}".format(
            len(left), ", ".join(want)))


if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="Fill the blank Ad on already-imported Call List rows")
    p.add_argument("--date", action="append", metavar="YYYY-MM-DD",
                   help="date to repair; repeatable (default: 7/28, 7/29, 7/30)")
    p.add_argument("--office", action="append", metavar="ID",
                   help="limit to office id(s); repeatable")
    p.add_argument("--dry-run", action="store_true",
                   help="scrape + match, write NOTHING to the Sheet")
    a = p.parse_args()
    if a.dry_run:
        sheets.DRY_RUN = True
    run(a.date, a.office)
