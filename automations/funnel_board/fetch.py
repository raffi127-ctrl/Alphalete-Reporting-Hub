"""Pull the eleven funnel metrics out of AppStream's Retention - Details (new).

The report runs SUN-SAT. A Mon-Sun week is therefore assembled from two report
weeks: Mon-Sat from the week containing that Monday, and the trailing Sunday
from the following report week.

Metric rows are `tr.mainRow[data-id]`; the per-recruiter breakdown underneath is
`tr.adminRow` and is skipped. Keying on data-id rather than the label text means
a wording change upstream can't silently break the pull.
"""
import datetime as dt
import re
import sys

from automations.shared.tableau_patchright import appstream_direct_session
from automations.recruiting_report import fetch_office

REPORT_P = 783

# Focus-Report metric  ->  AppStream mainRow label (resolved to data-id at runtime)
WANT = {
    "sent":    "Email Apps Sent to Call List",
    # Email is not the only intake path. Applicants also arrive via manual entry,
    # the resume scooper and file import, and each has its own sent-to-call-list
    # line. Counting email alone understates the call-list denominator, which is
    # what makes bookings/sends exceed 100% for anyone using those paths.
    # INTAKE — what actually arrived. Applies is built from these, not from the
    # processing rows: on 8/10 Rafael received 31 emails but vetted 623, because
    # Monday worked through Sunday's 227. Received answers "how many applied".
    "emails_rx": "Emails Received",
    "scoop_rx":  "Resume Scooper",
    "file_rx":   "File Import",
    "manual":  "Manual Apps Entry",
    "scoop_s": "Sent To Call List Resume Scooper",
    "file_s":  "Sent To Call List File Import",
    # Removals happen on the scooper path too; Total Applies needs both.
    "rm_scoop": "Removed From Resume Scooper",
    "removed": "Removed From Process Emails",
    # Calibrated against the live Focus Report, Rafael Hidalgo, wk 7/27-8/2:
    # "Total First Interviews" = 645 matches; "First Interviews Booked" = 689 does not.
    "b1":      "Total First Interviews",
    "s1":      "First Interviews Showed Up",
    "b2":      "Total Second Interviews",
    "s2":      "Second Interviews Showed Up",
    # Same calibration: "Offered Job From Second Round" = 54 matches;
    # "Position Offered from Second Calendar" = 52 does not.
    "off":     "Offered Job From Second Round",
    "bob":     "Brought on Board Booked",
    "nss":     "Total New Starts Scheduled",
    "nsh":     "New Starts Showed Up",
}
# Total Applies is NOT measured — it is sent + removed.

_JS_ROWS = """() => {
    const t = document.getElementById('totalsTable');
    if (!t) return null;
    const head = [...t.rows[0].cells].map(c => c.innerText.trim());
    const rows = [...t.querySelectorAll('tr.mainRow')].map(r => ({
        id:    r.getAttribute('data-id'),
        group: r.getAttribute('data-group-name') || '',
        isRet: r.getAttribute('data-is-retention') === '1',
        label: (r.cells[0] ? r.cells[0].innerText : '')
                 .replace(/view details/i, '').replace(/\\s+/g, ' ').trim(),
        vals:  [...r.cells].slice(1).map(c => c.innerText.trim())
    }));
    return {head, rows};
}"""


def _num(s):
    s = (s or "").strip().replace(",", "")
    if s in ("", "-", "N/A"):
        return 0
    if s.endswith("%"):
        return None                      # retention rows: recomputed, not stored
    try:
        return int(float(s))
    except ValueError:
        return 0


def report_week(page, rqst, start: dt.date, verbose=True):
    """Run the report for the Sun-Sat week containing `start`.

    Returns {date -> {metric -> int}} keyed by real dates.
    """
    page.goto("https://applicantstream.com/index.cfm?rqst=%s&p=%d" % (rqst, REPORT_P),
              wait_until="domcontentloaded", timeout=60000)
    page.wait_for_selector("form[name=frmRR] input[name=weekStart]", timeout=30000)

    # frmRR is a plain POST to index.cfm. Two traps here:
    #  * The visible `weekStart` datepicker is decorative — the server echoes it
    #    back but ignores it. `startDate2` (hidden, MM/DD/YYYY) is what actually
    #    selects the period, and it defaults to today. Posting only weekStart
    #    silently returns the CURRENT week, which reads exactly like success.
    #  * The form has an input named "submit", shadowing form.submit(), so the
    #    prototype method has to be called directly.
    # Submitting natively also sidesteps the jQuery datepicker, which patchright's
    # isolated world can't reach anyway.
    page.evaluate("""([slash, dash]) => {
        const f = document.forms['frmRR'];
        f.startDate2.value = slash;
        f.weekStart.removeAttribute('readonly');
        f.weekStart.value = dash;
        HTMLFormElement.prototype.submit.call(f);
    }""", [start.strftime("%m/%d/%Y"), start.strftime("%m-%d-%Y")])
    # Big offices (Rafael 11280, Khalil 11901) render this grid slowly — 60s is
    # not enough for them.
    page.wait_for_selector("#totalsTable tr.mainRow", timeout=240000)
    page.wait_for_timeout(1200)

    data = page.evaluate(_JS_ROWS)
    if not data:
        raise RuntimeError("totalsTable missing for weekStart=%s" % start)

    # Header: ['Action', 'Aug 02, 2026 Sunday', ..., 'Weekly Total']
    dates = []
    for h in data["head"][1:]:
        m = re.match(r"([A-Za-z]{3})\s+(\d{1,2}),\s*(\d{4})", h)
        if m:
            dates.append(dt.datetime.strptime(" ".join(m.groups()), "%b %d %Y").date())
    if len(dates) != 7:
        raise RuntimeError("expected 7 day columns, got %d from %r" % (len(dates), data["head"]))
    # The week's start day is a PER-OFFICE setting — some offices report Sun-Sat,
    # others Mon-Sun. Don't assume; the caller covers the target range by pulling
    # whatever report weeks it takes.

    by_label, ret_label = {}, {}
    for r in data["rows"]:
        (ret_label if r["isRet"] else by_label).setdefault(r["label"], r)

    missing = [k for k, lab in WANT.items() if lab not in by_label]
    if missing:
        raise RuntimeError("rows not found on the report: %s\navailable: %s"
                           % ([WANT[k] for k in missing], sorted(by_label)[:60]))

    out = {d: {} for d in dates}
    for key, label in WANT.items():
        vals = by_label[label]["vals"]
        for i, d in enumerate(dates):
            out[d][key] = _num(vals[i]) or 0
    for d in dates:
        # every intake path, on the date the applicant actually arrived
        out[d]["applies"] = (out[d]["emails_rx"] + out[d]["scoop_rx"]
                             + out[d]["file_rx"] + out[d]["manual"])

    # AppStream's own "Retention Call List" is a COHORT stat (of the apps saved to
    # the call list in this period, what share got a first interview booked) and
    # does NOT equal bookings/sends for the same period. It only exists as a
    # percentage, so store the numerator it implies — that way a stitched Mon-Sun
    # week rebuilds correctly as sum(numerator)/sum(sent) instead of averaging rates.
    rl = ret_label.get("Retention Call List")
    for i, d in enumerate(dates):
        pct = None
        if rl:
            raw = (rl["vals"][i] or "").strip()
            if raw.endswith("%"):
                try:
                    pct = float(raw[:-1]) / 100.0
                except ValueError:
                    pct = None
        # AppStream's denominator is the FULL call list, not just the email path
        # (Rashad's reported 48.8% lines up with bookings/total, not /email). So
        # scale by every sent-to-call-list source, not out[d]["sent"] alone.
        tot_sent = (out[d]["sent"] + out[d]["manual"]
                    + out[d]["scoop_s"] + out[d]["file_s"])
        out[d]["retb"] = int(round(pct * tot_sent)) if pct is not None else 0
    if verbose:
        print("   week %s..%s ok" % (dates[0], dates[-1]), flush=True)
    return out


def mon_sun_week(page, rqst, monday: dt.date, today=None, verbose=True):
    """Assemble a true Mon-Sun week out of the two Sun-Sat report weeks.

    Mon-Sat come from the report week containing `monday`; the trailing Sunday
    lives in the NEXT report week. AppStream clamps a future weekStart back to
    the current week, so when the trailing Sunday hasn't happened yet the second
    pull is skipped and that day is simply absent — an in-flight week, not an
    error.
    """
    assert monday.weekday() == 0, "%s is not a Monday" % monday
    today = today or dt.date.today()
    first = report_week(page, rqst, monday, verbose=verbose)      # Sun before .. Sat
    sunday = monday + dt.timedelta(days=6)

    second = {}
    if sunday <= today:
        second = report_week(page, rqst, monday + dt.timedelta(days=7), verbose=verbose)
        if sunday not in second:
            # clamped back to the same week — treat as not yet reportable
            if verbose:
                print("   ! next report week unavailable; %s left pending" % sunday, flush=True)
            second = {}

    merged, pending = {}, []
    for i in range(7):
        d = monday + dt.timedelta(days=i)
        if d in first:
            merged[d] = first[d]
        elif d in second:
            merged[d] = second[d]
        elif d <= today:
            raise RuntimeError("day %s missing from both report weeks" % d)
        else:
            pending.append(d)
    if pending and verbose:
        print("   (not yet reportable: %s)" % ", ".join(str(d) for d in pending), flush=True)
    return merged


def main():
    office = sys.argv[1] if len(sys.argv) > 1 else "11580"
    hint = sys.argv[2] if len(sys.argv) > 2 else "CARLOS HIDALGO"
    monday = (dt.datetime.strptime(sys.argv[3], "%Y-%m-%d").date()
              if len(sys.argv) > 3 else dt.date(2026, 8, 3))

    with appstream_direct_session(headless=False, verbose=True) as page:
        if not fetch_office._switch_office(page, office, hint):
            raise SystemExit("office switch to %s failed" % office)
        page.wait_for_timeout(1500)
        rqst = re.search(r"rqst=([A-Za-z0-9-]+)", page.url).group(1)

        # one-time: show what mainRows exist, so label drift is visible
        page.goto("https://applicantstream.com/index.cfm?rqst=%s&p=%d" % (rqst, REPORT_P),
                  wait_until="domcontentloaded", timeout=60000)

        print("\n=== office %s — Mon-Sun week of %s ===" % (office, monday))
        week = mon_sun_week(page, rqst, monday)

        keys = ["applies", "removed", "sent", "b1", "s1", "b2", "s2", "off", "bob", "nss", "nsh"]
        print("\n%-12s %s" % ("", "  ".join(k.rjust(7) for k in keys)))
        tot = {k: 0 for k in keys}
        for d in sorted(week):
            row = week[d]
            for k in keys:
                tot[k] += row[k]
            print("%-12s %s" % (d.strftime("%a %m/%d"),
                                "  ".join(str(row[k]).rjust(7) for k in keys)))
        print("%-12s %s" % ("WEEK", "  ".join(str(tot[k]).rjust(7) for k in keys)))
        print("\ncheck: sent + removed = %d + %d = %d  (applies %d)"
              % (tot["sent"], tot["removed"], tot["sent"] + tot["removed"], tot["applies"]))


if __name__ == "__main__":
    main()
