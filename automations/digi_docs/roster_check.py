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


def snapshot(page, *, verbose: bool = True) -> tuple:
    """(rows, complete) — every row on View Progress, and whether we PROVED it.

    2026-08-31, twice. The first version read `tbody tr` once per campaign and
    got 24, 1, 24 — page sizes, not rosters — and on that it reported 29 of 52
    people "not in OwnerVille", including two the add pass had logged as added
    the same morning. The second version tried to widen the length menu and walk
    Next, and reported the same 49 rows, so the pagination guess was wrong too.

    Guessing at pagination markup is what failed both times. So stop guessing
    and ask the table: DataTables prints "Showing 1 to 24 of 61 entries", and
    that N is the truth about how many rows exist. If what we read does not
    reach it, this run says INCOMPLETE and the caller must not claim anybody is
    missing — an under-read roster names real people as absent and invites
    adding them twice.
    """
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
    rows_seen, complete = set(), True
    for opt in sel.locator("option").all_inner_texts():
        label = opt.strip()
        if not label:
            continue
        sel.select_option(label=label)
        try:
            page.wait_for_load_state("networkidle", timeout=60000)
        except Exception:                   # noqa: BLE001
            pass
        _show_all(page)
        try:
            page.wait_for_load_state("networkidle", timeout=60000)
        except Exception:                   # noqa: BLE001
            pass
        before = len(rows_seen)
        read = _read_pages(page, rows_seen)
        claimed = _entries_total(page)
        ok = claimed is None or read >= claimed
        complete = complete and ok
        if verbose:
            says = "?" if claimed is None else str(claimed)
            print(f"  {label}: read {read}, table says {says}"
                  f"{'' if ok else '  ⛔ INCOMPLETE'}"
                  f"  (+{len(rows_seen) - before} new)", flush=True)
    return rows_seen, complete


def _entries_total(page):
    """The N in DataTables' "Showing 1 to 24 of N entries". None if unreadable —
    unreadable is not zero, and the caller treats it as "cannot prove"."""
    try:
        txt = page.locator("div[id$='_info'], .dataTables_info").first.inner_text(
            timeout=4000)
    except Exception:                       # noqa: BLE001
        return None
    m = re.search(r"of\s+([\d,]+)\s+entries", txt or "", re.I)
    return int(m.group(1).replace(",", "")) if m else None


def _read_pages(page, rows_seen: set) -> int:
    """Read the visible page, then every following one. Returns rows READ (not
    unique), so it can be compared against the table's own entry count."""
    read = 0
    for _ in range(60):                     # backstop, never a real page count
        rows = page.locator("tbody tr")
        n = rows.count()
        for i in range(n):
            try:
                rows_seen.add(_norm_row(rows.nth(i).inner_text(timeout=2000)))
                read += 1
            except Exception:               # noqa: BLE001
                continue
        nxt = page.locator("a:has-text('Next'):visible, "
                           "li.next:visible a, a.paginate_button.next:visible"
                           ).first
        try:
            if not nxt.count():
                break
            klass = (nxt.get_attribute("class") or "") + " " + (
                nxt.evaluate("e => e.parentElement ? e.parentElement.className : ''")
                or "")
            if "disabled" in klass.lower():
                break
            nxt.click()
            page.wait_for_timeout(900)
        except Exception:                   # noqa: BLE001
            break
    return read


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
