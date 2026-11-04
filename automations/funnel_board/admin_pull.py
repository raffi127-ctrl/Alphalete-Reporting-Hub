"""Admin-breakdown pull for ONE office — who did each funnel action, per day.

AppStream's Retention - Details (new) (p=783, the Focus Report's source) lists,
under every metric row, one `tr.adminRow` per recruiter/admin when the admin
breakdown is on. funnel_board/fetch.py deliberately skips those rows; this
pulls them for a single office across a range of Sun-Sat report weeks and
leaves the RAW table (head + every mainRow with its adminRows) as JSON, so a
standalone Focus Report can grow a "who did it" group under each metric.

Runs where a live AppStream session is (Lucy 2). Output goes two places:
  * output/admin_pull_<office>.json on the runner (checkpointed per week)
  * a tab of the control workbook (--tab), 45k-char JSON chunks down column A,
    so a laptop can read the result back without shell access to the runner.

  python -m automations.funnel_board.admin_pull --office 22192 --owner "Justin Wood" \
      --start 2026-04-26 --end 2026-11-01 --tab "JW Admin Data"
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from automations.shared.tableau_patchright import appstream_direct_session

REPO = Path(__file__).resolve().parents[2]
CONTROL_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
REPORT_P = 783
CHUNK = 45000

_JS_TABLE = """() => {
    const t = document.getElementById('totalsTable');
    if (!t) return null;
    const head = [...t.rows[0].cells].map(c => c.innerText.trim());
    const rows = []; let cur = null;
    for (const tr of t.querySelectorAll('tr')) {
        const cells = [...tr.cells].map(c => (c.innerText || '')
            .replace(/view details/i, '').replace(/\\s+/g, ' ').trim());
        if (tr.classList.contains('mainRow')) {
            cur = {id: tr.getAttribute('data-id'), group: tr.getAttribute('data-group-name') || '',
                   isRet: tr.getAttribute('data-is-retention') === '1',
                   label: cells[0], vals: cells.slice(1), admins: {}};
            rows.push(cur);
        } else if (tr.classList.contains('adminRow') && cur) {
            cur.admins[cells[0]] = cells.slice(1);
        }
    }
    const cbs = [...document.querySelectorAll('input[type=checkbox]')].map(c => ({
        name: c.name || '', id: c.id || '', checked: c.checked,
        label: ((c.parentElement || {}).innerText || '').slice(0, 60)}));
    return {head, rows, cbs};
}"""


def log(m):
    print(m, flush=True)


def switch(page, oid, rqst):
    """Office switch by URL (funnel_board/run.py: the autocomplete drops keys on Lucy 2)."""
    for attempt in range(3):
        try:
            page.goto("https://applicantstream.com/index.cfm?p=104&rqst=%s&newOfficeId=%s"
                      % (rqst, oid), timeout=60000, wait_until="domcontentloaded")
            page.wait_for_timeout(1800)
            who = page.evaluate(
                "() => (document.body.innerText.match(/Office ID: *(\\d+)/) || [])[1]")
            if who == oid:
                return True
            if attempt == 2:
                body = " ".join(page.evaluate("() => (document.body.innerText||'')").split())[:220]
                log("   %s: landed on %s | %s" % (oid, who or "?", body))
        except Exception as e:  # noqa: BLE001
            if attempt == 2:
                log("   %s: %s: %s" % (oid, type(e).__name__, str(e)[:120]))
        page.wait_for_timeout(1500)
    return False


def report_week(page, rqst, start: dt.date):
    """Submit the report for the Sun-Sat week containing `start`, admin breakdown ON.
    Same two traps as fetch.py: the visible weekStart picker is decorative
    (startDate2 selects the period) and the form has an input named "submit"."""
    def _submit():
        page.goto("https://applicantstream.com/index.cfm?rqst=%s&p=%d" % (rqst, REPORT_P),
                  wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector("form[name=frmRR] input[name=weekStart]", timeout=30000)
        page.evaluate("""([slash, dash]) => {
            const f = document.forms['frmRR'];
            f.startDate2.value = slash;
            f.weekStart.removeAttribute('readonly');
            f.weekStart.value = dash;
            for (const cb of document.querySelectorAll('input[type=checkbox]')) {
                const key = (cb.name||'') + ' ' + (cb.id||'') + ' ' + ((cb.parentElement||{}).innerText||'');
                if (/admin|breakdown/i.test(key) && !cb.checked) cb.checked = true;
            }
            HTMLFormElement.prototype.submit.call(f);
        }""", [start.strftime("%m/%d/%Y"), start.strftime("%m-%d-%Y")])

    for attempt in range(3):
        _submit()
        try:
            page.wait_for_selector("#totalsTable tr.mainRow", timeout=150000)
            break
        except Exception:  # noqa: BLE001
            if attempt == 2:
                raise
    page.wait_for_timeout(1200)
    data = page.evaluate(_JS_TABLE)
    if not data:
        raise RuntimeError("totalsTable missing for weekStart=%s" % start)
    n_admin = sum(len(r["admins"]) for r in data["rows"])
    log("   week %s: %d rows, %d admin rows, head=%s" % (start, len(data["rows"]), n_admin, data["head"][:2]))
    return data


def write_tab(tab: str, payload: dict):
    from automations.recruiting_report import fill as _fill
    sh = _fill._client().open_by_key(CONTROL_SHEET_ID)
    try:
        ws = sh.worksheet(tab)
        ws.clear()
    except Exception:  # noqa: BLE001 -- worksheet-not-found
        ws = sh.add_worksheet(title=tab, rows=400, cols=1)
    txt = json.dumps(payload)
    rows = [[txt[i:i + CHUNK]] for i in range(0, len(txt), CHUNK)]
    ws.update("A1", rows, value_input_option="RAW")
    log("wrote %d chunk(s) (%d chars) to tab %r" % (len(rows), len(txt), tab))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--office", required=True)
    ap.add_argument("--owner", default="")
    ap.add_argument("--start", required=True, help="first report Sunday, YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="last report Sunday, YYYY-MM-DD")
    ap.add_argument("--tab", default="", help="control-workbook tab to dump the JSON into")
    a = ap.parse_args(argv)
    start, end = dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end)
    sundays = []
    d = start
    while d <= end:
        sundays.append(d)
        d += dt.timedelta(days=7)
    out_path = REPO / "output" / ("admin_pull_%s.json" % a.office)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"office": a.office, "owner": a.owner, "pulled": dt.datetime.now().isoformat(timespec="seconds"),
               "weeks": {}}
    log("admin_pull: office %s (%s), %d report weeks %s..%s" % (a.office, a.owner, len(sundays), start, end))
    with appstream_direct_session(verbose=True) as page:
        page.wait_for_timeout(3000)
        page.wait_for_selector("#searchMC", timeout=20000)
        rqst = re.search(r"rqst=([A-Za-z0-9-]+)", page.url).group(1)
        if not switch(page, a.office, rqst):
            raise SystemExit("could not switch to office %s" % a.office)
        for sun in sundays:
            try:
                payload["weeks"][sun.isoformat()] = report_week(page, rqst, sun)
            except Exception as e:  # noqa: BLE001
                log("   week %s FAILED: %s: %s" % (sun, type(e).__name__, str(e)[:160]))
                payload["weeks"][sun.isoformat()] = {"error": "%s: %s" % (type(e).__name__, str(e)[:160])}
            out_path.write_text(json.dumps(payload))
    ok = sum(1 for w in payload["weeks"].values() if "rows" in w)
    log("pulled %d/%d weeks -> %s" % (ok, len(sundays), out_path))
    if a.tab:
        write_tab(a.tab, payload)
    return 0 if ok == len(sundays) else 1


if __name__ == "__main__":
    sys.exit(main())
