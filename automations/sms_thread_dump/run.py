"""SMS thread dump — read every First Interview booking's SMS chat history off
the AppStream Weekly Calendar for chosen dates and park the raw threads in the
control sheet (one tab per office) for the mini and Claude to read back.

WHY (Carlos 2026-09-06): he wants the full text-message conversations behind
last week's Wed/Thu/Fri first-round bookings so Claude can outline how the
AI/team responds to applicants. WHY AGAIN (Raf 2026-09-26): same read on HIS
office (11280) plus a Raf-vs-Carlos comparison — so the dump now takes a comma
list of offices in ONE run and writes each to its OWN tab (a second office used
to clear the first office's rows). The laptop's own AppStream login is the
retired rcaptain, so the read has to happen on Lucy 2's live "Lucy Reports"
session. READ-ONLY on AppStream — the only writes are the sheet tabs and a
local JSON cache per office.

  lucy rerun sms_thread_dump                          # office 11580, last full Sat-Fri week
  ... run.py --office 11280,11580                     # both offices, that same week
  ... run.py --week 2                                 # the week before that
  ... run.py --office 11280 --days 3                  # last 3 non-Sunday days instead
  ... run.py --office 11280 --dates 09-23-2026,09-24-2026
  ... run.py --limit 3                                # first 3 applicants per office (probe)
  ... run.py --dry-run                                # scrape, print counts, no sheet write

Mechanics: the default window is the last COMPLETE recruiting week, which runs
SATURDAY to FRIDAY (Megan 2026-09-26) — not the Mon-Sun band the calendar page
itself draws, so a week normally spans two of its pages and the code shifts
between them. p=105 Weekly Calendar defaults to the current Mon-Sun band. Each
"First Interview Date: <d>. Applicants: N" header row toggles its day table.
Every data row's LAST cell holds two icons; the FIRST opens the "Applicant
History for <name>" dialog (tabs: Action History / Email Sent / SMS Sent).
The SMS Sent tab's "Chat History" table is [Direction, Type, Text, At]. We
click through every row, scrape, close, next. ~2-4s per applicant. Dates that
fall in different weeks are grouped and the calendar is shifted once per week.

Output tab "SMS Dump <office>", rows: [date, time, name, phone, board,
booked_by, status, part, thread_json]. thread_json is a JSON list of
[direction, type, text, at]; a thread longer than ~45k chars continues on extra
rows with part=2,3… (sheet cells cap at 50k). Row 1 is a meta line, row 2 the
header. The legacy "SMS Dump" tab (Carlos, 09-02→09-04) is left alone.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from automations.shared.tableau_patchright import appstream_direct_session
from automations.recruiting_report import fill as _fill

CONTROL_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
TAB_PREFIX = "SMS Dump"          # real tab is "SMS Dump <office>"
OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "output"
CELL_CAP = 45000


def _rqst(page):
    m = re.search(r"rqst=([A-Za-z0-9_-]+)", page.url or "")
    if m:
        return m.group(1)
    m = re.search(r"rqst=([A-Za-z0-9_-]+)",
                  page.evaluate("() => document.documentElement.innerHTML") or "")
    return m.group(1) if m else None


def _default_dates(today=None):
    """Most recent Wed, Thu, Fri strictly before today (the 'last week' ask)."""
    today = today or dt.date.today()
    out = []
    for wd in (2, 3, 4):  # Wed, Thu, Fri
        d = today - dt.timedelta(days=1)
        while d.weekday() != wd:
            d -= dt.timedelta(days=1)
        out.append(d)
    return sorted(out)


def _recruiting_week(today=None, back=1):
    """The last COMPLETE recruiting week as (saturday, friday).

    Recruiting counts a week Saturday→Friday (Megan 2026-09-26), not Mon→Sun
    like the calendar page's own banner. back=1 is the week just finished,
    back=2 the one before it. Called on a Saturday, back=1 is the six days
    that ended yesterday — today is day 1 of the new week and is not in it."""
    today = today or dt.date.today()
    # the most recent Friday strictly before today ends the last full week
    end = today - dt.timedelta(days=1)
    while end.weekday() != 4:                      # 4 = Friday
        end -= dt.timedelta(days=1)
    end -= dt.timedelta(days=7 * (back - 1))
    return end - dt.timedelta(days=6), end         # Saturday, Friday


def _week_dates(today=None, back=1):
    """Every day of that recruiting week except Sunday — nobody books a first
    interview on one, so asking costs a page load to be told there is none."""
    start, end = _recruiting_week(today, back)
    out, d = [], start
    while d <= end:
        if d.weekday() != 6:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def _last_days(n, today=None):
    """The n most recent non-Sunday days strictly before today. Sunday is
    skipped because nobody books first interviews on it — asking for it just
    logs 'no First Interview section' and burns a page load."""
    today = today or dt.date.today()
    out, d = [], today - dt.timedelta(days=1)
    while len(out) < n:
        if d.weekday() != 6:
            out.append(d)
        d -= dt.timedelta(days=1)
    return sorted(out)


def _fmt(d: dt.date) -> str:
    return d.strftime("%m-%d-%Y")


def _banner_week(page):
    """('08-31-2026','09-06-2026') off the 'Calendar for Week:' banner."""
    txt = page.evaluate("() => document.body.innerText") or ""
    m = re.search(r"Calendar for Week:\s*(\d{2}-\d{2}-\d{4})\s*To\s*(\d{2}-\d{2}-\d{4})", txt)
    return (m.group(1), m.group(2)) if m else (None, None)


def _shift_week(page, back: bool):
    """Click the ◀/▶ next to the week input, then Get Report."""
    ok = page.evaluate(
        """(back) => {
             const inp = [...document.querySelectorAll('input')].find(
               i => / To /.test(i.value || ''));
             if (!inp) return 'no week input';
             const grp = inp.parentElement;
             const btns = [...grp.parentElement.querySelectorAll('button, a, input[type=button]')];
             // arrows render as the elements before/after the input's wrapper
             let el = back ? (inp.previousElementSibling || grp.previousElementSibling)
                           : (inp.nextElementSibling || grp.nextElementSibling);
             if (el) { el.click(); return 'ok'; }
             return 'no arrow';
           }""", back)
    if ok != "ok":
        raise RuntimeError(f"week shift failed: {ok}")
    page.get_by_role("button", name=re.compile("Get Report", re.I)).click()
    page.wait_for_load_state("networkidle")
    time.sleep(1.5)


def _goto_week_containing(page, tok, target: dt.date):
    page.goto(f"https://www.applicantstream.com/index.cfm?p=105&rqst={tok}")
    page.wait_for_load_state("networkidle")
    time.sleep(1.5)
    for _ in range(6):
        lo, hi = _banner_week(page)
        if not lo:
            raise RuntimeError("no 'Calendar for Week' banner — not on p=105?")
        lo_d = dt.datetime.strptime(lo, "%m-%d-%Y").date()
        hi_d = dt.datetime.strptime(hi, "%m-%d-%Y").date()
        if lo_d <= target <= hi_d:
            return (lo, hi)
        _shift_week(page, back=target < lo_d)
    raise RuntimeError(f"couldn't reach week containing {target} (banner {lo}–{hi})")


def _expand_day(page, date_str: str) -> int:
    """Click the 'First Interview Date: <d>.' header; return applicant count."""
    txt = page.evaluate("() => document.body.innerText") or ""
    m = re.search(r"First Interview Date: %s\. Applicants: (\d+)" % re.escape(date_str), txt)
    if not m:
        return -1  # day absent (e.g. no interviews)
    n = int(m.group(1))
    hdr = page.get_by_text(f"First Interview Date: {date_str}.", exact=False).first
    hdr.click()
    time.sleep(1.0)
    return n


def _day_rows(page, date_str: str):
    """Row dicts for the expanded day's table (index refs for clicking)."""
    return page.evaluate(
        """(dstr) => {
             const out = [];
             const rows = [...document.querySelectorAll('tr')];
             rows.forEach((tr, i) => {
               const tds = [...tr.querySelectorAll('td')];
               if (tds.length < 7 || tr.offsetParent === null) return;
               const cells = tds.map(td => (td.innerText || '').trim());
               if (cells[0] !== dstr) return;
               const links = [...tds[tds.length - 1].querySelectorAll('a, img')];
               if (!links.length) return;
               out.push({idx: i, date: cells[0], time: cells[1], name: cells[2],
                         phone: cells[3], board: cells[4], booked_by: cells[5],
                         status: cells[6]});
             });
             return out;
           }""", date_str)


def _open_history(page, row) -> bool:
    """Find the row FRESH by its cell values (closed dialogs leave <tr>s in the
    DOM, so a pre-collected index goes stale), mark its history icon, and click
    it with a REAL Playwright click (JS .click() didn't fire the handler)."""
    marked = page.evaluate(
        """(want) => {
             document.querySelectorAll('[data-smsmark]').forEach(
               e => e.removeAttribute('data-smsmark'));
             const tr = [...document.querySelectorAll('tr')].find(tr => {
               const tds = [...tr.querySelectorAll('td')];
               if (tds.length < 7 || tr.offsetParent === null) return false;
               const c = tds.map(td => (td.innerText || '').trim());
               return c[0] === want.date && c[1] === want.time
                      && c[2] === want.name && c[3] === want.phone;
             });
             if (!tr) return 'no row';
             const cell = tr.querySelectorAll('td')[tr.querySelectorAll('td').length - 1];
             const el = cell.querySelector('a img, img, a');
             if (!el) return 'no icon: ' + cell.innerHTML.slice(0, 200);
             el.setAttribute('data-smsmark', '1');
             return 'ok';
           }""", {"date": row["date"], "time": row["time"],
                  "name": row["name"], "phone": row["phone"]})
    if marked != "ok":
        raise RuntimeError(f"mark failed: {marked}")
    page.locator("[data-smsmark='1']").first.scroll_into_view_if_needed()
    page.locator("[data-smsmark='1']").first.click()
    return True


def _dialog_state(page) -> str:
    """One-line debug of what's on screen after a failed dialog wait."""
    return page.evaluate(
        """() => {
             const dlg = [...document.querySelectorAll('.ui-dialog, [role=dialog]')]
                          .filter(d => d.offsetParent !== null);
             return 'visible dialogs=' + dlg.length + ' first=' +
                    (dlg[0] ? (dlg[0].innerText || '').slice(0, 120).replace(/\\n/g, '|') : '-');
           }""")


def _scrape_thread(page):
    """In the open dialog: click SMS Sent, scrape Chat History rows."""
    page.get_by_text("SMS Sent", exact=True).first.click()
    page.wait_for_selector("text=Chat History", timeout=15000)
    time.sleep(0.6)
    return page.evaluate(
        """() => {
             const tbl = [...document.querySelectorAll('table')].find(
               t => t.offsetParent !== null
                    && /Direction/.test(t.innerText)
                    && /\\bAt\\b/.test(t.innerText));
             if (!tbl) return null;
             const out = [];
             [...tbl.querySelectorAll('tr')].forEach(tr => {
               const tds = [...tr.querySelectorAll('td')];
               if (tds.length >= 4)
                 out.push(tds.slice(0, 4).map(td => (td.innerText || '').trim()));
             });
             return out;
           }""")


def _close_dialog(page):
    for sel in ("button:has-text('Close')",
                ".ui-dialog-titlebar-close",
                "[class*='dialog'] [class*='close']"):
        try:
            page.locator(sel).first.click(timeout=3000)
            time.sleep(0.5)
            return
        except Exception:
            pass
    page.keyboard.press("Escape")
    time.sleep(0.5)


def _write_tab(records, meta: str, office: str):
    """One tab per office — "SMS Dump 11280" — so dumping a second office does
    not clear the first one's rows (the whole point of the comparison)."""
    tab = "{} {}".format(TAB_PREFIX, office)
    gc = _fill._client()
    sh = gc.open_by_key(CONTROL_SHEET_ID)
    try:
        ws = sh.worksheet(tab)
        ws.clear()
    except Exception:
        ws = sh.add_worksheet(tab, rows=4000, cols=10)
    rows = [[meta, "", "", "", "", "", "", "", ""],
            ["date", "time", "name", "phone", "board", "booked_by", "status",
             "part", "thread_json"]]
    for r in records:
        blob = json.dumps(r.get("thread") or r.get("error") or [], ensure_ascii=False)
        parts = [blob[i:i + CELL_CAP] for i in range(0, max(len(blob), 1), CELL_CAP)]
        for pi, chunk in enumerate(parts, 1):
            rows.append([r["date"], r["time"], r["name"], r["phone"], r["board"],
                         r["booked_by"], r["status"], pi, chunk])
    ws.update(values=rows, range_name="A1", raw=True)
    return tab, len(rows)


def _scrape_office(page, tok, office, dates, date_strs, limit):
    """Everything for ONE office: switch to it, walk each date's table, scrape.
    Dates in different calendar weeks are handled — the banner is re-checked
    per date, so a window that straddles a Sunday still reads clean."""
    page.goto("https://www.applicantstream.com/index.cfm?p=104&rqst={}&newOfficeId={}"
              .format(tok, office))
    page.wait_for_load_state("networkidle")
    time.sleep(1.0)

    records, scraped, week = [], 0, None
    for d, ds in zip(dates, date_strs):
        if week is None or not (week[0] <= d <= week[1]):
            lo, hi = _goto_week_containing(page, tok, d)
            week = (dt.datetime.strptime(lo, "%m-%d-%Y").date(),
                    dt.datetime.strptime(hi, "%m-%d-%Y").date())
            print("[sms_dump] {}: on week {} -> {}".format(office, lo, hi), flush=True)
        n = _expand_day(page, ds)
        if n < 0:
            print("[sms_dump] {} {}: no First Interview section — skipped"
                  .format(office, ds), flush=True)
            continue
        rows = _day_rows(page, ds)
        print("[sms_dump] {} {}: header says {}, table rows {}"
              .format(office, ds, n, len(rows)), flush=True)
        for row in rows:
            if limit and scraped >= limit:
                break
            rec = dict(row)
            rec.pop("idx", None)
            rec["office"] = office
            try:
                if not _open_history(page, row):
                    raise RuntimeError("history link not found")
                page.wait_for_selector("text=Applicant History for", timeout=15000)
                thread = _scrape_thread(page)
                rec["thread"] = thread or []
                if not thread:
                    rec["error"] = "no chat table"
            except Exception as e:  # noqa: BLE001 — one bad row must not kill the run
                state = ""
                try:
                    state = " · " + _dialog_state(page)
                except Exception:
                    pass
                rec["error"] = "{}: {}{}".format(
                    type(e).__name__, str(e).splitlines()[0][:120], state)
                print("[sms_dump]   {}: {}".format(row["name"], rec["error"]), flush=True)
            finally:
                _close_dialog(page)
            records.append(rec)
            scraped += 1
            if scraped % 10 == 0:
                print("[sms_dump]   …{} applicants read ({})".format(scraped, office),
                      flush=True)
        # collapse the day again to keep row indices stable per-day
        try:
            page.get_by_text("First Interview Date: {}.".format(ds), exact=False).first.click()
            time.sleep(0.8)
        except Exception:
            pass
    return records


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--office", default="11580",
                    help="one id or a comma list, e.g. 11280,11580")
    ap.add_argument("--dates", default="",
                    help="comma list MM-DD-YYYY; default last Wed/Thu/Fri")
    ap.add_argument("--days", type=int, default=0,
                    help="instead of --dates: the N most recent non-Sunday days")
    ap.add_argument("--week", type=int, nargs="?", const=1, default=0,
                    help="a whole recruiting week, Sat-Fri: 1 = the week just "
                         "finished (the default when nothing else is given), 2 = "
                         "the one before it")
    ap.add_argument("--limit", type=int, default=0, help="stop after N applicants per office")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    offices = [o.strip() for o in str(a.office).split(",") if o.strip()]
    if a.dates:
        dates = [dt.datetime.strptime(s.strip(), "%m-%d-%Y").date()
                 for s in a.dates.split(",") if s.strip()]
    elif a.days:
        dates = _last_days(a.days)
    else:
        # A recruiting week is Sat-Fri, and an audit that reports "the week" has
        # to mean that week — a Wed/Thu/Fri sample is the tail of one.
        dates = _week_dates(back=a.week or 1)
    dates = sorted(dates)
    date_strs = [_fmt(d) for d in dates]
    print("[sms_dump] offices {}, dates {}".format(offices, date_strs), flush=True)

    per_office = {}
    with appstream_direct_session(verbose=True) as page:
        tok = _rqst(page)
        if not tok:
            raise RuntimeError("no rqst token on the console page")
        for office in offices:
            per_office[office] = _scrape_office(page, tok, office, dates,
                                                date_strs, a.limit)

    OUTPUT_DIR.mkdir(exist_ok=True)
    rc = 0
    for office, records in per_office.items():
        (OUTPUT_DIR / "sms_thread_dump_{}.json".format(office)).write_text(
            json.dumps(records, indent=1, ensure_ascii=False))
        with_thread = sum(1 for r in records if r.get("thread"))
        meta = ("sms_thread_dump {:%Y-%m-%d %H:%M} office={} dates={} applicants={} "
                "with_sms={}".format(dt.datetime.now(), office, ",".join(date_strs),
                                     len(records), with_thread))
        if a.dry_run:
            print("[sms_dump] DRY RUN — no sheet write. " + meta, flush=True)
            continue
        if not records:
            print("[sms_dump] {}: nothing scraped — tab left alone".format(office),
                  flush=True)
            rc = 1
            continue
        tab, nrows = _write_tab(records, meta, office)
        print("[sms_dump] {}: {} applicants ({} with SMS), {} rows → tab '{}'"
              .format(office, len(records), with_thread, nrows, tab), flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
