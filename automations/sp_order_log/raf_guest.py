"""Carlos's guest reps' orders, read off RAF'S SaraPlus, merged into the
order log.

Carlos 2026-10-08: his reps sell ONLY under Raf's code right now ("they'll be
AT&T NDS here in like a week or so" — fiber under Raf until then). So the
Sales Order History pull on Carlos's own dealer (sp_order_log.pull_csv) reads
every one of those reps as zero, and the two Slack sections built from it —
the #8 AT&T Order Log workbook and the #9 Activation Report Overview in the
B2B Metrics thread — go out missing his whole crew. "We need that one remade
by looking at the sales made on their Rafael Saraplus logins."

HOW, in one line: pull the SAME Sales Order History export from RAF's dealer,
keep only the rows whose User Name matches the guest roster, and append them
to Carlos's export before shape_lines — same builders, same look, two dealers.

WHY THE PULL RUNS ON LUCY 1 (not Lucy 2, where sp_order_log lives). Raf's
dealer login (alphalete_sales_board: saraplus-creds.json +
automations/uploaded/.saraplus_profile) only exists on Lucy 1, where its
profile is already verified and — unlike Carlos's B2B login — has NO emailed
passcode step. A fresh profile on Lucy 2 could trigger SaraPlus's new-browser
device verification, and Raf's codes would land in an inbox this repo cannot
read (his codes do NOT go to alphaletereporting@gmail.com). So the pull stays
where the working session is, and the filtered CSV crosses machines the way
every other sp_order_log artifact already does: base64-chunked into a control
-sheet tab (status_probe._upload_bytes), which Lucy 2 decodes at merge time.

THE ROSTER IS THE ONE LIST — total_knocks.guests.GUEST_REPS, the same reps
the knock boards and Raf's sales board already split on, matched with the
same three-pass unique-hit-only matcher (guests.match_rows). An ambiguous
match is NO match; roster names with no SaraPlus rows are printed every pull
so a re-spelled rep shows up in the log, not as a silent zero.

TEMPORARY BY DESIGN: when the reps move onto Carlos's own NDS code (~a week,
Carlos 2026-10-08), their orders start landing in his own export and this
feed simply stops matching rows. Unload the Lucy 1 agent then; nothing else
needs an edit.

    python -m automations.sp_order_log.raf_guest --pull          # Lucy 1
    python -m automations.sp_order_log.raf_guest --show          # any box
    python -m automations.sp_order_log.raf_guest --from-file x.csv  # offline

Python 3.9-safe (Lucy runtime). Cross-platform.
"""
from __future__ import annotations

import argparse
import base64
import csv
import datetime as dt
import io
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

HOST = "Rafael Hidalgo"
GUEST = "Carlos Hidalgo"

# The handoff tab on the control sheet (the same workbook sp_order_log's
# 'SP XLSX' / 'SP AR Shot' relay tabs live in). Holds ONE base64-chunked JSON
# envelope: {"pulled", "start", "end", "rows", "csv"} — the envelope carries
# its own timestamp because the uploader clears the tab on every write and a
# bare CSV would have no way to say how old it is.
TAB = "Raf Guest Orders"

# A pull is usable for ~a day: the morning artifacts only need yesterday's
# orders, which a 4am pull already has in full (the 31-day window ends today,
# and today has no sales at 4am). Past this age the merge refuses the data
# and says so loudly rather than quietly serving week-old numbers.
MAX_AGE_H = 26

# SaraPlus spelling -> roster spelling, for a rep whose SaraPlus User Name
# shares no letters with the roster (the NAME_MAP situation — 'GLORIA SCOTT'
# selling as 'Annice Middleton'). The loose matcher handles middle names and
# status suffixes by itself; only a wholly different name belongs here.
RAF_NAME_MAP: Dict[str, str] = {}


# --- the roster filter --------------------------------------------------------

def _username_field(fieldnames: List[str]) -> Optional[str]:
    """The export's rep column, however it is spaced ('User Name' today)."""
    for f in fieldnames or []:
        if str(f or "").replace(" ", "").strip().lower() == "username":
            return f
    return None


def filter_csv(data: bytes, log=print) -> Tuple[bytes, Dict[str, int]]:
    """Keep only the guest roster's rows -> (filtered csv bytes, {rep: rows}).

    Matching happens once per DISTINCT User Name (not per row) through
    guests.match_rows, so a name matches or misses the same way the knock
    boards decide it — one answer about who a person is, everywhere.
    """
    from automations.total_knocks import guests
    from automations.total_knocks.pull import COL_REP

    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    fields = list(reader.fieldnames or [])
    ucol = _username_field(fields)
    if not ucol:
        raise RuntimeError(
            "no User Name column in Raf's export — header was: %r"
            % fields[:12])

    def spell(name: str) -> str:
        return RAF_NAME_MAP.get(" ".join(str(name or "").upper().split()),
                                name)

    names = sorted({str(r.get(ucol, "") or "").strip()
                    for r in rows if str(r.get(ucol, "") or "").strip()})
    name_rows = [{COL_REP: spell(n)} for n in names]
    roster = guests.roster(HOST, GUEST)
    claimed, missing = guests.match_rows(name_rows, roster)
    matched = {names[i]: roster_name for i, roster_name in claimed.items()}

    kept: List[Dict[str, str]] = []
    counts: Dict[str, int] = {}
    for r in rows:
        who = matched.get(str(r.get(ucol, "") or "").strip())
        if not who:
            continue
        kept.append(r)
        counts[who] = counts.get(who, 0) + 1

    log("raf guest filter: %d of %d row(s) kept, %d of %d roster name(s) "
        "found" % (len(kept), len(rows), len(matched), len(roster)))
    for sp_name, roster_name in sorted(matched.items()):
        log("  %-28s -> %s (%d row(s))"
            % (sp_name, roster_name, counts.get(roster_name, 0)))
    for name in missing:
        log("  NO SARAPLUS ROWS for roster name %r — re-spelled on Raf's "
            "side, or simply no orders in the window" % name)

    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=fields, restval="",
                       extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    w.writerows(kept)
    return out.getvalue().encode("utf-8-sig"), counts


# --- Lucy 1: pull + upload ----------------------------------------------------

def pull(start: dt.date, end: dt.date, *, headless: bool = True,
         log=print) -> bytes:
    """Raf's Sales Order History export, raw. Same panel walk as
    sp_order_log.pull_csv — SaraPlus is SaraPlus — but logged in through the
    sales-board sweep's machinery: Raf's creds, Raf's verified Lucy 1
    profile, login_healing instead of the emailed-passcode flow his account
    does not use. No Wireless per-line report: the guest reps are on fiber,
    and a missing wireless report already falls back to order-level dating in
    track_lines."""
    from patchright.sync_api import sync_playwright

    from automations.alphalete_sales_board import config as AC
    from automations.rc_contact_sync import config as C
    from automations.rc_contact_sync import sara
    from automations.rc_contact_sync.status_probe import _export_csv
    from automations.shared import saraplus as _sp

    cr = AC.creds()
    with sync_playwright() as p:
        ctx, page, base = _sp.login_healing(
            p, AC.PROFILE_DIR, cr["email"], cr["password"],
            headless=headless, creds_hint=str(AC.CREDS_PATH), log=log)
        try:
            log("logged in as %s (Raf's dealer)" % cr["email"])
            page.goto(base + C.HUB_PATH, wait_until="networkidle",
                      timeout=C.NAV_TIMEOUT_MS)
            sara.open_order_history_panel(page, log=log)
            sara._set_telerik_date(page, C.FIELD_START, start)
            sara._set_telerik_date(page, C.FIELD_END, end)
            # Customer Type: on CARLOS's dealer this must be forced to Both
            # (defaulting to Residential loses every B2B order). On RAF's
            # dealer the combo is DISABLED — readonly input pinned to
            # 'Residential' (seen on the first live run, 2026-10-08), and
            # clicking it retries until the whole pull dies. A locked combo
            # means the dealer only HAS one customer type, so the pinned
            # value already covers everything; skip the step instead.
            combo = "#%s_Input" % C.COMBO_CUSTOMER_TYPE
            locked = page.evaluate(
                "(s) => { const e = document.querySelector(s);"
                "         return !e || e.disabled || e.readOnly; }", combo)
            if locked:
                log("  customer type combo is locked on this dealer — "
                    "left as-is")
            else:
                sara._set_customer_type(page, C.CUSTOMER_TYPE_BOTH, log=log)
                # Customer Type autoposts back and can reset the dates.
                sara._set_telerik_date(page, C.FIELD_START, start)
                sara._set_telerik_date(page, C.FIELD_END, end)
            sara._submit(page, log=log)
            data = _export_csv(page, log)
            if data is None:
                raise sara.SaraError(
                    "Raf's CSV export produced no download")
            return data
        finally:
            ctx.close()


def upload(filtered: bytes, start: dt.date, end: dt.date, rows: int,
           log=print) -> bool:
    from automations.rc_contact_sync.status_probe import _upload_bytes
    env = {"pulled": dt.datetime.now().isoformat(timespec="seconds"),
           "start": start.isoformat(), "end": end.isoformat(),
           "rows": rows,
           "csv": base64.b64encode(filtered).decode()}
    return _upload_bytes(json.dumps(env).encode(), TAB, log=log)


# --- Lucy 2: fetch + merge ----------------------------------------------------

def fetch(log=print) -> Optional[Dict]:
    """The envelope off the control sheet, or None (with the reason logged)."""
    try:
        from automations.recruiting_report import fill as _fill
        from automations.rc_contact_sync.status_probe import CONTROL_SHEET
        sh = _fill._client().open_by_key(CONTROL_SHEET)
        t = sh.worksheet(TAB)
        chunks = [c[0] for c in t.get_values("A1:A200") if c and c[0]]
        if not chunks:
            log("raf guest merge: tab %r is empty — no pull has landed" % TAB)
            return None
        return json.loads(base64.b64decode("".join(chunks)))
    except Exception as e:  # noqa: BLE001
        log("raf guest merge: couldn't read tab %r (%s: %s)"
            % (TAB, type(e).__name__, str(e)[:120]))
        return None


def _age_hours(env: Dict) -> Optional[float]:
    try:
        pulled = dt.datetime.fromisoformat(str(env.get("pulled", "")))
        return (dt.datetime.now() - pulled).total_seconds() / 3600.0
    except Exception:  # noqa: BLE001
        return None


def merge_rows(carlos_csv: bytes, guest_csv: bytes, log=print) -> bytes:
    """Carlos's export + the guest rows, one CSV. Column union keyed by
    header name (the two dealers' exports are the same report, but a column
    SaraPlus adds on one side must not shift the other's). No dedup: the
    reps sell ONLY under Raf right now (Carlos 2026-10-08), and the two
    dealers' Order IDs can never be the same order."""
    a = csv.DictReader(io.StringIO(carlos_csv.decode("utf-8-sig",
                                                     errors="replace")))
    b = csv.DictReader(io.StringIO(guest_csv.decode("utf-8-sig",
                                                    errors="replace")))
    rows_a, rows_b = list(a), list(b)
    fields = list(a.fieldnames or [])
    fields += [f for f in (b.fieldnames or []) if f not in fields]
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=fields, restval="",
                       extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    w.writerows(rows_a)
    w.writerows(rows_b)
    log("raf guest merge: %d own + %d guest row(s)"
        % (len(rows_a), len(rows_b)))
    return out.getvalue().encode("utf-8-sig")


def merge(carlos_csv: bytes, *, log=print, fetcher=fetch) -> bytes:
    """What run.py calls: Carlos's export bytes in, merged bytes out.

    NEVER raises and NEVER returns less than it was given — a missing or
    stale guest pull costs the 15 guest reps' rows (said loudly), not the
    report."""
    try:
        env = fetcher(log=log)
        if not env:
            log("raf guest merge: NO GUEST DATA — the guest reps will read "
                "as zero in today's order log")
            return carlos_csv
        age = _age_hours(env)
        if age is None or age > MAX_AGE_H:
            log("raf guest merge: STALE pull (%s, %sh old > %dh) — the "
                "guest reps will read as zero in today's order log; check "
                "`logtail raf-guest-orders` on Lucy 1"
                % (env.get("pulled"), "?" if age is None else round(age, 1),
                   MAX_AGE_H))
            return carlos_csv
        guest_csv = base64.b64decode(env.get("csv", "") or "")
        if not guest_csv:
            log("raf guest merge: envelope carries no csv — skipped")
            return carlos_csv
        log("raf guest merge: using pull from %s (%.1fh old, %s row(s))"
            % (env.get("pulled"), age, env.get("rows", "?")))
        return merge_rows(carlos_csv, guest_csv, log=log)
    except Exception as e:  # noqa: BLE001
        log("raf guest merge: FAILED (%s: %s) — continuing with Carlos's "
            "rows only" % (type(e).__name__, str(e)[:160]))
        return carlos_csv


# --- main ---------------------------------------------------------------------

def main(argv=None) -> int:
    from automations.sp_order_log.run import WINDOW_DAYS

    ap = argparse.ArgumentParser(
        prog="raf_guest",
        description="Pull Raf's SaraPlus Sales Order History, keep the guest "
                    "roster's rows, hand them to Lucy 2 via the control "
                    "sheet.")
    ap.add_argument("--pull", action="store_true",
                    help="log into Raf's SaraPlus and refresh the handoff "
                         "tab (Lucy 1)")
    ap.add_argument("--show", action="store_true",
                    help="read the handoff tab back and summarize it")
    ap.add_argument("--from-file", default=None, metavar="CSV",
                    help="filter this export instead of pulling (offline)")
    ap.add_argument("--start", default=None, metavar="YYYY-MM-DD")
    ap.add_argument("--end", default=None, metavar="YYYY-MM-DD")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--no-upload", action="store_true",
                    help="with --pull / --from-file: filter and report, "
                         "write nothing to the sheet")
    args = ap.parse_args(argv)

    today = dt.date.today()
    start = (dt.date.fromisoformat(args.start) if args.start
             else today - dt.timedelta(days=WINDOW_DAYS))
    end = dt.date.fromisoformat(args.end) if args.end else today

    if args.show:
        env = fetch()
        if not env:
            return 1
        age = _age_hours(env)
        print("pulled %s (%s old), window %s..%s, %s guest row(s)"
              % (env.get("pulled"),
                 "?" if age is None else "%.1fh" % age,
                 env.get("start"), env.get("end"), env.get("rows")))
        data = base64.b64decode(env.get("csv", "") or "")
        for i, line in enumerate(
                data.decode("utf-8-sig", errors="replace").splitlines()):
            if i > 5:
                print("  ... (%d line(s))" % len(data.splitlines()))
                break
            print("  " + line[:160])
        print("=== done ===", flush=True)
        return 0

    if args.from_file:
        data = Path(args.from_file).read_bytes()
    elif args.pull:
        print("Raf SaraPlus pull %s..%s (Customer Type Both)" % (start, end))
        data = pull(start, end, headless=not args.headed)
    else:
        ap.print_help()
        return 2

    filtered, counts = filter_csv(data)
    n = sum(counts.values())
    if args.no_upload:
        print("(--no-upload: %d guest row(s), nothing written)" % n)
    else:
        if not upload(filtered, start, end, n):
            print("UPLOAD FAILED — the merge on Lucy 2 will not see this pull")
            return 1
    print("=== done ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
