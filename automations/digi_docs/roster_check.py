"""READ-ONLY: who on today's chart is actually in OwnerVille, and who is not.

Run:  lucy --machine "Lucy 3" rerun digi_docs_roster_check

WHY (2026-08-31). The add pass died twice mid-cohort, and the runs that
followed refused nearly everyone with the same line:

    ⛔ Peter Mitka: not in the Add Sales Rep employee list

That message has two OPPOSITE meanings. Either the person is already in
OwnerVille, so the Add picker no longer offers them and everything is fine —
or they are genuinely not an available employee and will have nothing to
generate against when their bundle is due. Reading the add log cannot tell
those apart, and guessing wrong means new starts do not get their contracts.

ONE PERSON AT A TIME, NOT THE WHOLE LIST (2026-09-21). This used to read every
row of View Progress and compare. It never once worked: it read 24 of 144 and
said INCOMPLETE every time, and the 8/31 and 9/14 fixes (bigger page, walk
Next, pick "All") all failed the same way. roster_probe found why — the table
is SERVER-SIDE (DataTables serverSide=true): the browser only ever holds the
one page OwnerVille sends, OwnerVille ignores the page-size menu, and asking
it for every row returns nothing. No click can read the whole list.

The search box is also server-side, and it DOES work — it is how the send
finds each person every five minutes. So this loads RES-AT&T once and asks the
search about each person on today's chart: the same question, answered the
way that works.

It WRITES NOTHING: no adds, no Sheet, and Slack only with --post. It cannot
send.
"""
from __future__ import annotations

import re

from automations.digi_docs import config, roster, run as _run


def count_matches(page, name: str) -> int:
    """How many RES-AT&T rows carry this whole name, using the table's own
    search. 0 = not there, 1 = there, 2+ = more than one record (the Jaylen
    Anthony case). Exact name only: this answers "is THIS person there", so a
    typo'd namesake does not count as them."""
    from automations.headshots.ov_upload import _search_box, _search_probes
    parts = [p for p in name.split() if p]
    if not parts:
        return 0
    pat = re.compile(r"\s+".join(re.escape(p) for p in parts), re.I)
    best = 0
    for probe in _search_probes(name):
        box = _search_box(page)
        box.fill("")
        # Key by key: this table filters on keyup, which fill() never fires.
        box.press_sequentially(probe, delay=40)
        try:
            # Server-side: each keystroke is a request, so wait for the
            # answer rather than a fixed pause.
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:                                   # noqa: BLE001
            pass
        page.wait_for_timeout(600)
        n = page.locator("tbody tr").filter(has_text=pat).count()
        best = max(best, n)
        if n:
            break
    return best


def check(page, names) -> dict:
    """{name: rows found} for each name, off ONE page load."""
    from automations.b2b_dispositions.capture import capture_rqst
    from automations.headshots.ov_upload import (
        VIEW_PROGRESS_P, _campaign_select, _show_all,
    )
    rqst = capture_rqst(page)
    page.set_default_navigation_timeout(90000)
    page.goto(f"https://v2.ownerville.com/index.cfm?p={VIEW_PROGRESS_P}"
              f"&rqst={rqst}", wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=60000)
    except Exception:                                       # noqa: BLE001
        pass
    _campaign_select(page).select_option(label=config.ADD_CAMPAIGN)
    try:
        page.wait_for_load_state("networkidle", timeout=60000)
    except Exception:                                       # noqa: BLE001
        pass
    # Show All, not the default last-3-weeks window: somebody added weeks ago
    # who is starting now is still "in OwnerVille".
    _show_all(page)
    out = {}
    for n in names:
        try:
            out[n] = count_matches(page, n)
        except Exception as e:                              # noqa: BLE001
            print(f"  {n}: could not check ({type(e).__name__})")
            out[n] = -1
    return out


def main(argv=None) -> int:
    import argparse
    from automations.digi_docs import ownerville as ov

    ap = argparse.ArgumentParser()
    ap.add_argument("--post", action="store_true",
                    help="also say it in the day's Digi Docs Slack thread. "
                         "Without this the check only prints.")
    args = ap.parse_args(argv)

    ws, values = _run._open_tab(None)
    cands = roster.to_send(roster.candidates(values, ws.title))
    cohort = roster.starting_today(cands)
    print(f"{ws.title}: {len(cohort)} on today's chart(s)\n")
    if not cohort:
        print("no chart dated for today — nothing to check")
        return 0

    with ov.session(headless=True) as page:
        found = check(page, [c.name for c in cohort])

    inov = [n for n, k in found.items() if k == 1]
    missing = [n for n, k in found.items() if k == 0]
    twice = [n for n, k in found.items() if k >= 2]
    unchecked = [n for n, k in found.items() if k < 0]
    print(f"IN OwnerVille ({config.ADD_CAMPAIGN}) : {len(inov)}")
    print(f"MISSING                  : {len(missing)}")
    for n in missing:
        print(f"  • {n}")
    if twice:
        print(f"MORE THAN ONE RECORD     : {len(twice)}")
        for n in twice:
            print(f"  • {n} ({found[n]} rows) — the send will refuse to guess")
    if unchecked:
        print(f"COULD NOT CHECK          : {len(unchecked)}")
        for n in unchecked:
            print(f"  • {n}")
    # A check that could not ask about somebody has not answered the
    # question, and must not read as a clean pass.
    if unchecked:
        return 2

    if args.post:
        lines = [f"*New starts added to OV* — {len(inov)} of {len(cohort)} "
                 f"on today's chart are in OwnerVille"]
        if missing:
            lines += ["", f"*Not in OV ({len(missing)})* — these have nothing "
                          f"to generate against when their send comes round:"]
            lines += [f"• {n}" for n in missing]
        if twice:
            lines += ["", f"*More than one record ({len(twice)})* — the send "
                          f"will not guess between them:"]
            lines += [f"• {n}" for n in twice]
        if not (missing or twice):
            lines.append("Everyone on today's chart is in. Nothing is missing.")
        try:
            from automations.digi_docs import slack_post as _sp
            from automations.shared import slack_metrics_post as smp
            smp.post_reply_text_only("\n".join(lines),
                                     thread_ts=_sp._thread_ts(smp),
                                     channel_id=_sp.CHANNEL)
            print("\nposted to the Digi Docs thread")
        except Exception as e:              # noqa: BLE001
            print(f"\nSlack post failed: {type(e).__name__}: {str(e)[:160]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
