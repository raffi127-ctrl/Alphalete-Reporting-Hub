"""SMS thread dump — read every First Interview booking's SMS chat history off
the AppStream Weekly Calendar for chosen dates and park the raw threads in the
control sheet (tab "SMS Dump") for the mini to read back.

WHY (Carlos 2026-09-06): he wants the full text-message conversations behind
last week's Wed/Thu/Fri first-round bookings in HIS office (11580) so Claude
can outline how the AI/team responds to applicants. The laptop's own AppStream
login is the retired rcaptain, so the read has to happen here on Lucy 2's live
"Lucy Reports" session. READ-ONLY on AppStream — the only writes are the sheet
tab and a local JSON cache.

  lucy rerun sms_thread_dump                      # office 11580, last Wed/Thu/Fri
  ... run.py --office 11580 --dates 09-02-2026,09-03-2026,09-04-2026
  ... run.py --limit 3                            # first 3 applicants only (probe)
  ... run.py --dry-run                            # scrape, print counts, no sheet write

Mechanics: p=105 Weekly Calendar defaults to the current Mon-Sun band. Each
"First Interview Date: <d>. Applicants: N" header row toggles its day table.
Every data row's LAST cell holds two icons; the FIRST opens the "Applicant
History for <name>" dialog (tabs: Action History / Email Sent / SMS Sent).
The SMS Sent tab's "Chat History" table is [Direction, Type, Text, At]. We
click through every row, scrape, close, next. ~2-4s per applicant.

Output tab rows: [date, time, name, phone, board, booked_by, status, part,
thread_json]. thread_json is a JSON list of [direction, type, text, at]; a
thread longer than ~45k chars continues on extra rows with part=2,3… (sheet
cells cap at 50k). Row 1 is a meta line, row 2 the header.
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
TAB = "SMS Dump"
RAW_PATH = (Path(__file__).resolve().parent.parent.parent / "output"
            / "sms_thread_dump.json")
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
    DOM, so a pre-collected index goes stale) and click its first icon link."""
    return page.evaluate(
        """(want) => {
             const tr = [...document.querySelectorAll('tr')].find(tr => {
               const tds = [...tr.querySelectorAll('td')];
               if (tds.length < 7 || tr.offsetParent === null) return false;
               const c = tds.map(td => (td.innerText || '').trim());
               return c[0] === want.date && c[1] === want.time
                      && c[2] === want.name && c[3] === want.phone;
             });
             if (!tr) return false;
             const tds = tr.querySelectorAll('td');
             const link = tds[tds.length - 1].querySelector('a');
             if (!link) return false;
             link.click();
             return true;
           }""", {"date": row["date"], "time": row["time"],
                  "name": row["name"], "phone": row["phone"]})


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


def _write_tab(records, meta: str):
    gc = _fill._client()
    sh = gc.open_by_key(CONTROL_SHEET_ID)
    try:
        ws = sh.worksheet(TAB)
        ws.clear()
    except Exception:
        ws = sh.add_worksheet(TAB, rows=2000, cols=10)
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
    return len(rows)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--office", default="11580")
    ap.add_argument("--dates", default="",
                    help="comma list MM-DD-YYYY; default last Wed/Thu/Fri")
    ap.add_argument("--limit", type=int, default=0, help="stop after N applicants")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    dates = ([dt.datetime.strptime(s.strip(), "%m-%d-%Y").date()
              for s in a.dates.split(",") if s.strip()]
             if a.dates else _default_dates())
    date_strs = [_fmt(d) for d in dates]
    print(f"[sms_dump] office {a.office}, dates {date_strs}", flush=True)

    records, scraped = [], 0
    with appstream_direct_session(verbose=True) as page:
        tok = _rqst(page)
        if not tok:
            raise RuntimeError("no rqst token on the console page")
        page.goto(f"https://www.applicantstream.com/index.cfm?p=104&rqst={tok}&newOfficeId={a.office}")
        page.wait_for_load_state("networkidle")
        time.sleep(1.0)
        lo, hi = _goto_week_containing(page, tok, dates[0])
        print(f"[sms_dump] on week {lo} → {hi}", flush=True)

        for d in date_strs:
            n = _expand_day(page, d)
            if n < 0:
                print(f"[sms_dump] {d}: no First Interview section — skipped", flush=True)
                continue
            rows = _day_rows(page, d)
            print(f"[sms_dump] {d}: header says {n}, table rows {len(rows)}", flush=True)
            for row in rows:
                if a.limit and scraped >= a.limit:
                    break
                rec = dict(row)
                rec.pop("idx", None)
                try:
                    if not _open_history(page, row):
                        raise RuntimeError("history link not found")
                    page.wait_for_selector("text=Applicant History for", timeout=15000)
                    thread = _scrape_thread(page)
                    rec["thread"] = thread or []
                    if not thread:
                        rec["error"] = "no chat table"
                except Exception as e:  # noqa: BLE001 — one bad row must not kill the run
                    rec["error"] = f"{type(e).__name__}: {str(e).splitlines()[0][:160]}"
                    print(f"[sms_dump]   {row['name']}: {rec['error']}", flush=True)
                finally:
                    _close_dialog(page)
                records.append(rec)
                scraped += 1
                if scraped % 10 == 0:
                    print(f"[sms_dump]   …{scraped} applicants read", flush=True)
            # collapse the day again to keep row indices stable per-day
            try:
                page.get_by_text(f"First Interview Date: {d}.", exact=False).first.click()
                time.sleep(0.8)
            except Exception:
                pass

    RAW_PATH.parent.mkdir(exist_ok=True)
    RAW_PATH.write_text(json.dumps(records, indent=1, ensure_ascii=False))
    with_thread = sum(1 for r in records if r.get("thread"))
    meta = (f"sms_thread_dump {dt.datetime.now():%Y-%m-%d %H:%M} office={a.office} "
            f"dates={','.join(date_strs)} applicants={len(records)} with_sms={with_thread}")
    if a.dry_run:
        print(f"[sms_dump] DRY RUN — no sheet write. {meta}", flush=True)
        return 0
    nrows = _write_tab(records, meta)
    print(f"[sms_dump] finished: {len(records)} applicants ({with_thread} with SMS), "
          f"{nrows} rows → tab '{TAB}'", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
