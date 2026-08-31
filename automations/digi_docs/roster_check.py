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

from automations.digi_docs import roster, run as _run


def _norm_row(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def snapshot(page, *, verbose: bool = True) -> set:
    """Every row on View Progress, across every campaign, Show All on."""
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
    except Exception:                       # noqa: BLE001
        pass
    sel = _campaign_select(page)
    rows_seen = set()
    for opt in sel.locator("option").all_inner_texts():
        label = opt.strip()
        if not label:
            continue
        sel.select_option(label=label)
        try:
            page.wait_for_load_state("networkidle", timeout=60000)
        except Exception:                   # noqa: BLE001
            pass
        _show_all(page)                     # the default 3-week window hides reps
        try:
            page.wait_for_load_state("networkidle", timeout=60000)
        except Exception:                   # noqa: BLE001
            pass
        pages = _read_every_page(page, rows_seen)
        if verbose:
            print(f"  {label}: {pages} page(s), {len(rows_seen)} row(s) so far",
                  flush=True)
    return rows_seen


def _read_every_page(page, rows_seen: set) -> int:
    """Read the WHOLE table, not the page of it DataTables happens to show.

    2026-08-31: the first version read `tbody tr` once per campaign and got 24,
    1, 24 — those are PAGE sizes, not rosters. It then reported 29 of 52 people
    "not in OwnerVille", including two the add pass had logged as added the
    same morning. A paginated read that calls itself a roster is worse than no
    check at all: it names real people as missing and invites someone to add
    them twice.

    Widen the length menu to its largest option first (DataTables names it
    <something>_length), then walk Next until the button stops being clickable.
    """
    try:                                    # biggest page size on offer
        length = page.locator("select[name$='_length']:visible").first
        if length.count():
            opts = [o.strip() for o in length.locator("option").all_inner_texts()]
            best = max(opts, key=lambda o: (o.strip().lower() in ("all", "-1"),
                                            int(re.sub(r"\D", "", o) or 0)))
            length.select_option(label=best)
            page.wait_for_timeout(1200)
    except Exception:                       # noqa: BLE001 — walk pages instead
        pass
    seen_pages = 0
    while seen_pages < 40:                  # backstop, never a real page count
        seen_pages += 1
        rows = page.locator("tbody tr")
        for i in range(rows.count()):
            try:
                rows_seen.add(_norm_row(rows.nth(i).inner_text(timeout=2000)))
            except Exception:               # noqa: BLE001
                continue
        nxt = page.locator("a.next:visible, li.next:visible a, "
                           "a.paginate_button.next:visible").first
        try:
            if not nxt.count():
                break
            cls = (nxt.get_attribute("class") or "") + " " + (
                nxt.evaluate("e => e.parentElement ? e.parentElement.className "
                             ": ''") or "")
            if "disabled" in cls.lower():
                break
            nxt.click()
            page.wait_for_timeout(900)
        except Exception:                   # noqa: BLE001
            break
    return seen_pages


def present(rows_seen: set, name: str) -> bool:
    """Every part of the name somewhere in one row, in order, whitespace-loose —
    the same shape ov_upload._rep_row matches with."""
    parts = [re.escape(p) for p in name.split() if p]
    if not parts:
        return False
    pat = re.compile(r"\s+".join(parts), re.I)
    return any(pat.search(r) for r in rows_seen)


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
        rows_seen = snapshot(page)
    print(f"\nroster: {len(rows_seen)} row(s) read\n")
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
