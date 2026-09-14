"""READ-ONLY: who on an upcoming chart is not in OwnerVille yet.

Run:  lucy --machine "Lucy 3" rerun digi_docs_preflight            (next chart)
      lucy --machine "Lucy 3" rerun digi_docs_preflight --date 9/21
      ... --post                                   (say it in Slack too)

WHY (Megan 2026-09-14: "we need to be able to fully send to everyone on time
for next week").

On 2026-09-14, fifteen of forty-eight new starts were not in OwnerVille's
employee directory. Nobody knew until the day itself: the add pass runs at
11:00am and the send goes thirty minutes before each person's own start, so
the first anyone heard of it was a refusal half an hour before somebody was
due to walk in. The office then spent the afternoon adding people by hand
while the clock ran, and the pass stops at 4:00pm, so anyone added late gets
nothing at all.

None of that is a hard problem. The chart is written days ahead, and the Add
Sales Rep picker is ONE list that answers the whole cohort in a single read.
Asking on Friday what we asked at 11:00 on Monday costs one page load and
turns a thirty-minute emergency into a to-do list with a weekend attached.

IT WRITES NOTHING. No adds, no sends, no Sheet. It cannot mail anybody.
"""
from __future__ import annotations

import argparse
import datetime as dt

from automations.digi_docs import namematch as nm


def _parse_date(s: str):
    """'9/21', '9/21/26' or an ISO date. Month/day assumes the coming year's
    chart, which is what somebody typing 9/21 in September means."""
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m/%d"):
        try:
            d = dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
        if fmt == "%m/%d":
            d = d.replace(year=dt.date.today().year)
        return d
    raise SystemExit(f"cannot read a date out of {s!r} — try 9/21 or 2026-09-21")


def classify(names, options):
    """(ok, ambiguous, missing) — how each board name lands in the picker.

    `ok` means the picker offers exactly one person we would confidently
    select. `ambiguous` means it offers several and we would refuse rather
    than guess. `missing` means the directory has nobody who could be them,
    which is the one that needs a human and a few days' notice.

    A person ALREADY on the campaign is not offered by the picker at all, so
    they look 'missing' here. That is why this reports, and never acts.
    """
    ok, ambiguous, missing = [], [], []
    for name in names:
        exact = [o for o in options if nm.norm(o) == nm.norm(name)]
        if len(exact) == 1:
            ok.append((name, exact[0], "exact"))
            continue
        if len(exact) > 1:
            ambiguous.append((name, exact, "identical spellings"))
            continue
        hits = nm.strict_hits(name, options)
        if len(hits) == 1:
            ok.append((name, hits[0], "name"))
            continue
        if len(hits) > 1:
            ambiguous.append((name, hits, "several could be them"))
            continue
        near = nm.unique_near_miss(name, options)
        if near:
            ok.append((name, near, "spelled differently"))
            continue
        _first, last = nm.parts(name)
        mates = [o for o in options if last and last in nm.norm(o)]
        missing.append((name, mates))
    return ok, ambiguous, missing


def main(argv=None) -> int:
    from automations.digi_docs import ownerville as ov, roster, run as _run

    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="",
                    help="the chart date to check. Default: the next dated "
                         "chart on the tab that is not in the past.")
    ap.add_argument("--post", action="store_true",
                    help="also say it in Slack. Without this it only prints.")
    args = ap.parse_args(argv)

    ws, values = _run._open_tab(None)
    cands = roster.to_send(roster.candidates(values, ws.title))
    want = _parse_date(args.date)
    if want is None:
        today = dt.date.today()
        ahead = sorted({c.chart_date for c in cands
                        if c.chart_date and c.chart_date >= today})
        if not ahead:
            print(f"{ws.title}: no chart dated today or later — nothing to "
                  f"check ahead of time")
            return 0
        want = ahead[0]
    cohort = roster.starting_today(cands, today=want)
    print(f"{ws.title}: {len(cohort)} new start(s) on the {want:%-m/%-d} chart"
          if hasattr(want, "strftime") else "")
    if not cohort:
        print(f"no chart dated {want} — nothing to check")
        return 0

    with ov.session(headless=True) as page:
        options = ov.employee_options(page)
    if not options:
        print("⛔ the Add Sales Rep picker returned NOTHING. This run says "
              "nothing about who is missing — do not act on it.")
        return 2

    ok, ambiguous, missing = classify([c.name for c in cohort], options)
    print(f"\nchecked against {len(options)} employee(s) in OwnerVille\n")
    print(f"  ready:     {len(ok)}")
    print(f"  ambiguous: {len(ambiguous)}")
    print(f"  MISSING:   {len(missing)}\n")
    for name, matched, how in ok:
        if how != "exact":
            print(f"  · {name}: matches {matched!r} ({how})")
    for name, hits, why in ambiguous:
        print(f"  ⚠ {name}: {why} — {hits[:3]}")
    for name, mates in missing:
        same = f" (surname seen in {mates[:3]})" if mates else ""
        print(f"  ⛔ {name}: nobody in the directory could be them{same}")

    if not missing and not ambiguous:
        print("\nEverybody on this chart is in OwnerVille. Monday can send.")
    if args.post:
        _post(want, ok, ambiguous, missing, len(options))
    return 0


def _post(when, ok, ambiguous, missing, total) -> None:
    """Say it in the office channel, ONCE, with the names under one ask.

    Deliberately silent when there is nothing to do: "everybody is fine" every
    Friday is the blank board that teaches people to stop reading the channel.
    """
    if not missing and not ambiguous:
        print("(nothing to report — not posting)")
        return
    from automations.digi_docs import slack_post as sp
    from automations.shared import slack_metrics_post as smp
    lines = [f"*🗂️ Digi Docs — {when:%-m/%-d} chart: "
             f"{len(missing) + len(ambiguous)} person(s) not ready*"]
    if missing:
        lines.append(f"\n*Not in OwnerVille* ({len(missing)})")
        lines += [f"   • {n}" for n, _m in sorted(missing)]
        lines.append(
            "*What's needed:* add them in OwnerVille → *Add Sales Rep*, "
            "campaign *RES-AT&T*, before their start day. Anyone still "
            "missing on the day gets no documents.")
    if ambiguous:
        lines.append(f"\n*Two people share this name* ({len(ambiguous)})")
        lines += [f"   • {n}" for n, _h, _w in sorted(ambiguous)]
        lines.append("*What's needed:* reply with the right person's "
                     "OwnerVille employee id.")
    lines.append(f"_Checked against {total} employees._")
    lines.append(sp._tags())
    smp._client().chat_postMessage(channel=sp.CHANNEL,
                                   text="\n".join(lines).rstrip())
    print("posted to Slack")


if __name__ == "__main__":
    raise SystemExit(main())
