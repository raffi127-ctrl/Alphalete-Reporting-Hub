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
    """{(owner, ident): [ad, ...]} for every target date, plus the offices that
    couldn't be read. ONE report load per office serves all the dates."""
    index = {}
    by_ident = {}
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
                    index.setdefault((_norm(owner), key), []).append(ad)
                    by_ident.setdefault(key, []).append((_norm(owner), ad))
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
    return index, by_ident, skipped


# ---- step 3: pair them up -------------------------------------------------
def match(rows, index, by_ident):
    """Pair each candidate sheet row with a scraped Ad. Returns
    (fills {rownum: ad}, misses [(rownum, reason, identity)]).

    Two applicants can share an identity (the same person applying to two ads in
    the same minute). Those rows are indistinguishable from each other, so the
    ads are handed out in order — the multiset lands correct even though no
    single pairing is provable."""
    fills, misses = {}, []
    used = {}
    for n in sorted(rows):
        row = rows[n]
        owner, key = _norm(row[0]), _ident(row[1], row[2], row[3], row[4], row[7])
        pool = index.get((owner, key))
        why = ""
        if pool is None:
            # The owner string is whatever select_office returned the day of the
            # import; if that drifted, fall back to identity alone rather than
            # leaving a row unfilled — but only when it's unambiguous.
            alt = by_ident.get(key)
            if alt:
                owners = set(o for o, _ in alt)
                if len(owners) == 1:
                    pool = [ad for _, ad in alt]
                    owner = list(owners)[0]
                    why = "owner mismatch (matched on identity alone)"
                else:
                    misses.append((n, "same applicant under {} owners — "
                                      "ambiguous".format(len(owners)), key))
                    continue
        if not pool:
            misses.append((n, "no matching applicant in today's scrape", key))
            continue
        i = used.get((owner, key), 0)
        if i >= len(pool):
            misses.append((n, "more sheet rows than scraped ads for this "
                              "applicant ({} rows, {} ads)".format(
                                  i + 1, len(pool)), key))
            continue
        used[(owner, key)] = i + 1
        fills[n] = pool[i]
        if why:
            misses.append((n, "FILLED — " + why, key))
    return fills, misses


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
    '[' or '=' lands as the literal text it is."""
    if not fills:
        return 0
    written = 0
    for start, end in _runs(list(fills)):
        values = [[fills[n]] for n in range(start, end + 1)]
        rng = "I{}:I{}".format(start, end)
        if sheets.DRY_RUN:
            log("    [dry-run] would write {} cell(s) into {}".format(
                len(values), rng))
        else:
            ws.update(rng, values, value_input_option="RAW")
        written += len(values)
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
        index, by_ident, skipped = scrape_ads(app, offices, targets)

    fills, misses = match(rows, index, by_ident)
    written = write_ads(ws, fills)

    print("\n--- RESULT ---")
    print("Rows needing an Ad : {}".format(len(rownums)))
    print("Ads written        : {}{}".format(
        written, " (dry-run, nothing sent)" if sheets.DRY_RUN else ""))
    unfilled = [m for m in misses if not m[1].startswith("FILLED")]
    noted = [m for m in misses if m[1].startswith("FILLED")]
    if noted:
        print("Filled with a note : {}".format(len(noted)))
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
