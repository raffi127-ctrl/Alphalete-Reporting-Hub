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


def _add_to_headcount(ss, name: str, label: str, org_head: str, *,
                      dry_run: bool, logfn=print) -> dict:
    """Same day, same person, on the 'Org Active Headcount' tab (Eve 2026-10-20:
    every new owner goes onto the ORG board, the All Campaigns board AND the
    Headcount). Advisory: the ORG board row already exists whatever happens
    here, and a failure comes back as a status the notice spells out."""
    try:
        from automations.org_active_headcount import daily as hc_daily
        from automations.org_active_headcount import roster_add
        try:
            hws = ss.get_worksheet_by_id(hc_daily.TAB_GID)
        except Exception:                                      # noqa: BLE001
            hws = ss.worksheet(hc_daily.TAB)
        return roster_add.add_owner(hws, name, label, org_head or "",
                                    dry_run=dry_run, logfn=logfn)
    except Exception as e:  # noqa: BLE001 — never takes the board run down
        logfn(f"  ⚠ headcount add for {name} failed ({type(e).__name__}: "
              f"{str(e)[:100]}) — add them to 'Org Active Headcount' by hand")
        return {"status": "failed"}


# The ORG-board sections whose owners also belong on the Country Sales Board.
# That tab's day block is 'Fiber - All Units' off the ATT D2D tracker, so only
# the ATT Fiber section feeds it.
COUNTRY_SECTIONS = {"att fiber team"}


def _add_to_allcamp_and_country(ss, name: str, label: str, *, aliases,
                                dry_run: bool, logfn=print) -> dict:
    """Eve 2026-11-24, the chain: ORG board -> ALWAYS the All Campaigns board
    -> and, once there, the ATT Country Sales Board too.

    Same day, not 'on its next run'. All Campaigns' own roster sync would catch
    them a few minutes later anyway, but the Country board's only adder was the
    FRIDAY att_owners_list run reading LAST week — so someone whose first sale
    is a Monday stayed off it for ~11 days and their units counted nowhere.
    Both inserts reuse the boards' own add_one (row at the last data row so the
    fixed ranges grow, history blank); the day fills + newcomer last-week
    backfill of each board's daily run, which comes after this one, do the rest.

    Advisory: returns {'allcamp': status, 'country': status}; a failure is a
    status the notice spells out, never an exception."""
    out = {"allcamp": None, "country": None}
    try:
        from automations.all_campaigns_board import roster as acr
        from automations.all_campaigns_board.run import TARGET_TAB
        aws = next(w for w in ss.worksheets()
                   if w.title.strip() == TARGET_TAB.strip())
        anchor = fs.find_daily_section(_retry(aws.get_all_values),
                                       acr.agg_target_label())
        cands = fs._candidates_for(name, aliases)
        if any(fs._candidates_for(n, aliases) & cands for n in anchor.icd_rows):
            out["allcamp"] = "already"
        elif name.strip().lower() in acr.EXCLUDE:
            out["allcamp"] = "excluded"
            logfn(f"  {name} is EXCLUDED from All Campaigns (removed by hand) "
                  f"— not adding there, nor to Country")
        elif dry_run:
            out["allcamp"] = "would_add"
            logfn(f"    (dry-run) would add {name!r} to All Campaigns")
        else:
            acr.add_one(aws, name, logfn=logfn)
            out["allcamp"] = "added"
    except Exception as e:  # noqa: BLE001
        logfn(f"  ⚠ All Campaigns add for {name} failed ({type(e).__name__}: "
              f"{str(e)[:100]}) — its roster sync retries on its next run")
        out["allcamp"] = "failed"

    if out["allcamp"] not in ("added", "already", "would_add"):
        return out
    if label.strip().lower() not in COUNTRY_SECTIONS:
        out["country"] = "n/a"
        return out
    try:
        from automations.recruiting_report.fill import open_by_key
        from automations.country_sales_board.run import SHEET_ID, PROD_TAB
        from automations.att_owners_list import board as country
        cws = open_by_key(SHEET_ID).worksheet(PROD_TAB)
        res = country.sync(cws, [name], aliases=aliases, dry_run=dry_run,
                           logfn=logfn)
        out["country"] = ("added" if res.get("added") else
                          "would_add" if res.get("would_add") else "already")
    except Exception as e:  # noqa: BLE001
        logfn(f"  ⚠ Country Sales Board add for {name} failed "
              f"({type(e).__name__}: {str(e)[:100]}) — add them by hand")
        out["country"] = "failed"
    return out


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
        hc = _add_to_headcount(ss, r.name, label, r.org_head,
                               dry_run=dry_run, logfn=logfn)
        if hc.get("status") == "added":
            note += f" · Headcount row {hc.get('daily_row')}"
        elif hc.get("status") not in ("already", "would_add"):
            note += " · NOT on the Headcount tab — add by hand"
        chain = _add_to_allcamp_and_country(ss, r.name, label, aliases=aliases,
                                            dry_run=dry_run, logfn=logfn)
        if chain["allcamp"] == "failed":
            note += " · NOT on All Campaigns yet"
        if chain["country"] == "failed":
            note += " · NOT on the Country Sales Board — add by hand"
        bank.mark(bws, cmap, r.row, status=bank.ADDED, activated_on=today,
                  notes=note, dry_run=dry_run, logfn=logfn)
        out["added"].append({"name": r.name, "campaign": label,
                             "units": units, "first_day": first,
                             "org_head": r.org_head,
                             "daily_row": res.get("daily_row"),
                             "leaderboard_row": res.get("leaderboard_row"),
                             "headcount": hc.get("status"),
                             "allcamp": chain["allcamp"],
                             "country": chain["country"]})
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
