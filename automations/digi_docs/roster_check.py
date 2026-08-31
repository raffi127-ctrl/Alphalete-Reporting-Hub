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

The only honest answer is to look at the roster itself. One page load, one walk
across the campaign dropdown with Show All on, read every row. Answers the
whole cohort at once, in a couple of minutes.

It WRITES NOTHING: no adds, no Sheet, no Slack. It cannot send.
"""
from __future__ import annotations

import re

from automations.digi_docs import ownerville as _ov, roster, run as _run
from automations.digi_docs.ownerville import present, snapshot


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
        rows_seen, complete = snapshot(page)
    print(f"\nroster: {len(rows_seen)} row(s) read\n")
    if not complete:
        print("⛔ INCOMPLETE — at least one campaign returned fewer rows than "
              "the table says it has. This run cannot say who is missing, and "
              "nothing here should be acted on or posted.")
        return 2
    if not rows_seen:
        print("⛔ read NOTHING off View Progress — this check says nothing "
              "about who is in OwnerVille. Do not act on it.")
        return 2

    missing = [c.name for c in cohort if not present(rows_seen, c.name)]
    inov = len(cohort) - len(missing)
    print(f"IN OwnerVille : {inov}")
    print(f"MISSING       : {len(missing)}")
    for n in missing:
        print(f"  • {n}")

    if args.post:
        lines = [f"*New starts added to OV* — {inov} of {len(cohort)} "
                 f"on today's chart are in OwnerVille"]
        if missing:
            lines += ["", f"*Not in OV ({len(missing)})* — these have nothing "
                          f"to generate against when their send comes round:"]
            lines += [f"• {n}" for n in missing]
        else:
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
