"""The campaign half: bank -> first sale -> a row on the board -> a heads-up.

Called once per daily Org Sales Board run, AFTER every section has pulled and
filled, with the pulls still in memory. That timing is deliberate:

  * the pull is the only honest signal of "they started selling". The bank says
    who to watch; Tableau says when. Nothing here trusts a date somebody typed.
  * the sections are already filled, so inserting a row now can't shift the row
    numbers out from under a fill that is still running (the orchestrator plans
    every section off ONE grid read).
  * the section whose block just gained a row is re-filled immediately from the
    SAME pull, so the new owner's days land through the normal engine — no
    second write path that could drift from it.

A person is added the first day they have ANY production in the reporting week,
and the bank row is stamped so it never happens twice. Someone with no sales yet
is simply left alone: they stay in the bank, and tomorrow we look again.

Advisory by contract — every call site wraps this, and any failure here must
leave the board run exactly as it was (filled, and reporting the truth).
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

from automations.recruiting_report.fill import _retry
from automations.org_sales_board import fill_section as fs
from automations.org_sales_board import week as _wk
from automations.new_owners import bank, board_add, notify


def _units(pull: dict, metric: str, name: str, aliases, days: set) -> tuple:
    """(units this reporting week, first day with a sale) for one person.

    Same alias-expanded matcher the fill uses, so 'has sales' here means the
    fill would also find them — not a spelling that only this check can see."""
    cands = fs._candidates_for(name, aliases)
    key = next((k for k in pull if k in cands), None)
    if key is None:
        return 0, None
    per_day = pull[key].get(metric, {}) or {}
    total = sum(int(v) for d, v in per_day.items() if d in days)
    first = min((d for d, v in per_day.items() if d in days and int(v) > 0),
                default=None)
    return total, first


def run(ws, pulls_by_label: Dict[str, tuple], *, today: Optional[dt.date] = None,
        dry_run: bool = False, aliases=None, logfn=print) -> dict:
    """Walk the bank against this run's pulls.

    `pulls_by_label` — {section label: (pull, metric)} for the sections that
    actually pulled this run. A campaign that didn't pull (skipped, failed,
    granular retry) is simply not judged today: its people keep waiting rather
    than being read as 'no sales'.

    Returns {'added': [...], 'waiting': n, 'flagged': [...], 'posted': ts}."""
    from automations.focus_office_att.aliases import load_aliases
    aliases = aliases if aliases is not None else load_aliases()
    today = today or dt.date.today()
    week = set(_wk.reporting_week(today))
    out = {"added": [], "waiting": 0, "flagged": [], "posted": None}

    grid = _retry(ws.get_all_values)
    labels = board_add.campaign_labels(grid)
    ss = ws.spreadsheet
    bws = bank.open_bank(ss, campaigns=labels, logfn=logfn)
    cmap, rows = bank.read(bws)
    if not rows:
        logfn("  new owners: the bank is empty — nothing to watch")
        return out

    waiting = [r for r in rows if r.waiting]
    logfn(f"  new owners: {len(waiting)} of {len(rows)} bank row(s) waiting "
          f"for a first sale")
    label_by_norm = {bank._norm(l): l for l in labels}
    touched: List[str] = []

    for r in waiting:
        label = label_by_norm.get(bank._norm(r.campaign))
        if not label:
            out["flagged"].append(
                f"{r.name}: campaign {r.campaign!r} is not a section on the "
                f"board")
            bank.mark(bws, cmap, r.row, status=bank.UNKNOWN_CAMPAIGN,
                      notes=f"Pick one of: {', '.join(labels)}",
                      dry_run=dry_run, logfn=logfn)
            continue
        if label not in pulls_by_label:
            out["waiting"] += 1
            continue                      # section didn't pull today — not judged
        pull, metric = pulls_by_label[label]
        existing = board_add.already_on_board(grid, label, r.name, aliases)
        if existing:
            bank.mark(bws, cmap, r.row, status=bank.ALREADY,
                      activated_on=today,
                      notes=f"already had a row in {label} (row {existing})",
                      dry_run=dry_run, logfn=logfn)
            out["flagged"].append(f"{r.name}: already on the board in {label}")
            continue
        units, first = _units(pull, metric, r.name, aliases, week)
        if units <= 0:
            out["waiting"] += 1
            if not r.status:
                bank.mark(bws, cmap, r.row, status=bank.WAITING,
                          dry_run=dry_run, logfn=logfn)
            continue

        logfn(f"  ✚ {r.name} has {units} unit(s) in {label} this week — "
              f"adding to the board")
        res = board_add.add_owner(ws, label, r.name, org_head=r.org_head,
                                  aliases=aliases, today=today,
                                  dry_run=dry_run, logfn=logfn)
        note = (f"{units} unit(s) this week"
                + (f", first on {first.month}/{first.day}" if first else "")
                + f" · daily row {res.get('daily_row')}"
                + (f", leaderboard row {res.get('leaderboard_row')}"
                   if res.get("leaderboard_row") else ""))
        bank.mark(bws, cmap, r.row, status=bank.ADDED, activated_on=today,
                  notes=note, dry_run=dry_run, logfn=logfn)
        out["added"].append({"name": r.name, "campaign": label,
                             "units": units, "first_day": first,
                             "org_head": r.org_head,
                             "daily_row": res.get("daily_row"),
                             "leaderboard_row": res.get("leaderboard_row")})
        if label not in touched:
            touched.append(label)
        if not dry_run:
            grid = _retry(ws.get_all_values)      # rows moved under us

    # Re-fill every section that gained a row, from the pull we already have —
    # the new rows get their real days in this same run, not tomorrow.
    for label in touched:
        if dry_run:
            continue
        pull, metric = pulls_by_label[label]
        try:
            plan = fs.plan_section_fill(_retry(ws.get_all_values),
                                        fs.SectionSpec(label=label,
                                                       metric=metric),
                                        pull, raw_aliases=aliases, today=today)
            fs.apply_plan(ws, plan, dry_run=False, logfn=logfn)
        except Exception as e:  # noqa: BLE001 — the row exists either way
            logfn(f"  ⚠ re-fill of {label!r} after the insert failed "
                  f"({type(e).__name__}: {str(e)[:80]}) — the row is there and "
                  f"tomorrow's run fills it.")

    if out["added"]:
        try:
            lws = bank.open_log(ss, logfn=logfn)
            bank.append_log(lws, [[today.strftime("%m/%d/%Y"), bank.KIND_ORG,
                                   a["name"], a["campaign"],
                                   f"added to the daily block + weekly "
                                   f"leaderboard", f"{a['units']} unit(s)"]
                                  for a in out["added"]],
                            dry_run=dry_run, logfn=logfn)
            out["posted"] = notify.post(
                lws, bank.KIND_ORG,
                notify.campaign_message(out["added"], today), today,
                dry_run=dry_run, logfn=logfn)
        except Exception as e:  # noqa: BLE001 — the board add already happened
            logfn(f"  ⚠ new-owner notice failed ({type(e).__name__}: "
                  f"{str(e)[:100]}) — the rows ARE on the board; the note "
                  f"didn't go out.")
    return out
