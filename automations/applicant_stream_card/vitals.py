# -*- coding: utf-8 -*-
"""Key vitals, week by week — the Trend page of the grade card.

Megan 2026-11-13: "we should have a 'trend' section as the 1st page where we
list their key vitals": 1st round retention, 2nd round retention, new start
retention, 1st rounds showed, sent to call list, 2nd round showed, RTCL.

Source: AppStream -> Retention Details report (p=783), one week at a time,
through the reader the Recruiting Funnel Board uses
(funnel_board.fetch.report_week). Megan 2026-11-13: new start retention is
"on the retention details report in applicant stream" — its "Retention New
Starts Scheduled" row read 53% for 11280 the week the Focus Report's p=783
pull showed 0%. The card pulls it ITSELF rather than reading another
report's sheet: each card pulls its own sources (no cross-report reuse).

The report gives daily COUNTS; each vital is worked out from the week's
totals, so a week is never an average of daily percentages:
    1st round retention   1st showed / 1st booked
    2nd round retention   2nd showed / 2nd booked
    new start retention   new starts showed / new starts scheduled
    sent to call list     every intake path's sent-to-call-list
    RTCL                  AppStream's Retention Call List, rebuilt from the
                          numerator report_week stores (retb) / sent

The pull needs the AppStream session, so it runs on a Lucy and writes a
control-sheet tab, "AS Vitals <office>", that the card reads anywhere — the
same pattern as the AI Settings tab. AppStream's week is Sunday-Saturday.

    lucy rerun as_card_vitals --office 11280
    python -m automations.applicant_stream_card.vitals --office 11280 --dry-run

READ-ONLY in AppStream. Writes only its own tab.
"""
from __future__ import annotations  # Lucy runs Python 3.9 — keep lazy

import argparse
import datetime as dt
import json
import sys

CONTROL_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
TAB_PREFIX = "AS Vitals"
WEEKS = 8

# (fetch_office metric key, what the card calls it, percent?)
VITALS = [
    # Megan's order, 2026-11-13: the funnel top to bottom, each count
    # followed by its retention.
    ("pull", "Sent to call list", False),
    ("pct_apps_booked_first", "RTCL (call list booked for a 1st)", True),
    ("first_showed", "1st rounds showed", False),
    ("pct_first_retention", "1st round retention", True),
    ("second_showed", "2nd rounds showed", False),
    ("pct_second_retention", "2nd round retention", True),
    ("new_starts_showed", "New starts showed", False),
    ("pct_new_start_retention", "New start retention", True),
]
KEYS = [k for k, _l, _p in VITALS]


def tab_for(office):
    return "{} {}".format(TAB_PREFIX, office)


def last_sundays(n=WEEKS, today=None):
    """The Sundays starting the last `n` FINISHED Sun-Sat weeks, oldest first."""
    today = today or dt.date.today()
    this_sunday = today - dt.timedelta(days=(today.weekday() + 1) % 7)
    return [this_sunday - dt.timedelta(weeks=i) for i in range(n, 0, -1)]


def _client():
    from automations.recruiting_report import fill as _fill
    return _fill._client()


def to_rows(weeks):
    """[(sunday, {key: value})] -> sheet rows (row 1 stamp, row 2 header)."""
    body = [["pulled {} from AppStream p=783".format(
        dt.datetime.now().isoformat(timespec="seconds"))] + [""] * len(KEYS),
        ["week"] + KEYS]
    for sunday, vals in weeks:
        body.append([sunday.isoformat()] + [
            "" if vals.get(k) is None else str(vals.get(k)) for k in KEYS])
    return body


def parse(values):
    """Sheet rows -> ([(sunday, {key: float|None})], stamp) oldest first."""
    if not values or len(values) < 3:
        return [], None
    head = values[1]
    out = []
    for raw in values[2:]:
        if not raw or not raw[0]:
            continue
        try:
            sunday = dt.date.fromisoformat(raw[0].strip())
        except ValueError:
            continue
        vals = {}
        for i, key in enumerate(head[1:], start=1):
            cell = raw[i].strip() if i < len(raw) else ""
            try:
                vals[key] = float(cell) if cell else None
            except ValueError:
                vals[key] = None
        out.append((sunday, vals))
    out.sort(key=lambda w: w[0])
    return out, values[0][0] if values[0] else None


def write(office, weeks, gc=None):
    body = to_rows(weeks)
    gc = gc or _client()
    sh = gc.open_by_key(CONTROL_SHEET_ID)
    tab = tab_for(office)
    try:
        ws = sh.worksheet(tab)
        ws.clear()
    except Exception:  # noqa: BLE001 — gspread's missing-tab error varies
        ws = sh.add_worksheet(tab, rows=max(len(body) + 10, 30),
                              cols=len(KEYS) + 1)
    ws.update(values=body, range_name="A1", raw=True)
    return tab, len(body)


def read(office, gc=None):
    """([(sunday, {key: value})], stamp) or ([], None). Never raises: a sheet
    that can't be reached reads the same as never pulled."""
    try:
        gc = gc or _client()
        values = gc.open_by_key(CONTROL_SHEET_ID).worksheet(
            tab_for(office)).get_all_values()
    except Exception:  # noqa: BLE001
        return [], None
    return parse(values)


def trend(weeks, key):
    """(latest, change vs the average of the 3 weeks before) or (None, None)."""
    vals = [v.get(key) for _s, v in weeks]
    if not vals or vals[-1] is None:
        return None, None
    before = [v for v in vals[-4:-1] if v is not None]
    if not before:
        return vals[-1], None
    return vals[-1], vals[-1] - sum(before) / len(before)


def from_days(days):
    """{date: {metric: int}} for one report week -> {vital key: value}."""
    t = {}
    for d in days.values():
        for k, v in d.items():
            t[k] = t.get(k, 0) + (v or 0)
    sent = (t.get("sent", 0) + t.get("manual", 0) + t.get("scoop_s", 0)
            + t.get("file_s", 0))

    def pct(a, b):
        return round(100.0 * t.get(a, 0) / t[b], 1) if t.get(b) else None
    return {
        "pct_first_retention": pct("s1", "b1"),
        "pct_second_retention": pct("s2", "b2"),
        "pct_new_start_retention": pct("nsh", "nss"),
        "first_showed": t.get("s1"),
        "pull": sent,
        "second_showed": t.get("s2"),
        "new_starts_showed": t.get("nsh"),
        "pct_apps_booked_first": (round(100.0 * t.get("retb", 0) / sent, 1)
                                  if sent else None),
    }


def _rqst(page):
    import re
    m = re.search(r"rqst=([A-Za-z0-9_-]+)", page.url or "")
    if m:
        return m.group(1)
    m = re.search(r"rqst=([A-Za-z0-9_-]+)", page.evaluate(
        "() => document.documentElement.innerHTML") or "")
    return m.group(1) if m else None


def pull(office, n=WEEKS, page=None):
    """[(first day, {key: value})] for the last `n` finished weeks."""
    from automations.funnel_board import fetch as FB
    from automations.recruiting_report import fetch_office as fo
    if not fo._switch_office(page, office, "", confirm_denial=True):
        raise RuntimeError("could not switch to office {}".format(office))
    page.wait_for_timeout(1500)
    rqst = _rqst(page)
    if not rqst:
        raise RuntimeError("no rqst token after switching to {}".format(office))
    out = []
    for sunday in last_sundays(n):
        days = FB.report_week(page, rqst, sunday, verbose=False)
        vals = from_days(days)
        out.append((min(days) if days else sunday, vals))
        print("[vitals] {} week of {}: {}".format(
            office, min(days) if days else sunday, ", ".join(
                "{}={}".format(k, vals.get(k)) for k in KEYS)), flush=True)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--office", default="11280", help="one id or a comma list")
    ap.add_argument("--weeks", type=int, default=WEEKS)
    ap.add_argument("--dry-run", action="store_true",
                    help="pull and print, write nothing")
    a = ap.parse_args(argv)
    from automations.shared.tableau_patchright import appstream_direct_session
    offices = [o.strip() for o in str(a.office).split(",") if o.strip()]
    rc = 0
    with appstream_direct_session(verbose=True, yield_if_busy=True) as page:
        page.wait_for_timeout(3000)
        for office in offices:
            try:
                weeks = pull(office, a.weeks, page)
            except Exception as e:  # noqa: BLE001 — one office never stops the rest
                print("[vitals] {} FAILED: {}: {}".format(
                    office, type(e).__name__, e), flush=True)
                rc = 1
                continue
            if not any(v for _s, vals in weeks for v in vals.values()
                       if v is not None):
                print("[vitals] {}: every week came back empty — not "
                      "written".format(office), flush=True)
                rc = 1
                continue
            if a.dry_run:
                print(json.dumps([(s.isoformat(), v) for s, v in weeks],
                                 indent=1), flush=True)
                continue
            tab, n = write(office, weeks)
            print("[vitals] {} -> {} ({} rows)".format(office, tab, n),
                  flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
