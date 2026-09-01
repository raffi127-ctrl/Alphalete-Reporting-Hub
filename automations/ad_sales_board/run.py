"""Refresh the Ad Sales Board — the Source Report week by week, pull + names.

  python -m automations.ad_sales_board.run              # live: current + previous ad-week
  python -m automations.ad_sales_board.run --dry-run    # pull + report, write nothing
  python -m automations.ad_sales_board.run --office 11580
  python -m automations.ad_sales_board.run --weeks 4    # backfill: current + 3 back
  python -m automations.ad_sales_board.run --anchor 08-12-2026   # one explicit week

An ad-week runs MONDAY → SUNDAY (see weeks.py — the fleet's WE convention).
Each run re-pulls its target weeks from AppStream's Source Report (p=702) per
office, joins the applicant names from the Call List import, and rewrites ONLY
the (manager, week) pairs it actually pulled — everything older stays frozen
exactly as it was last written, same freeze rule as the monthly dashboard.

The visible board is one stacked scroll of every week for the picked manager,
newest on top — each block opens with a WEEK ENDING band row this job writes
into the data itself.
"""
from __future__ import annotations  # Lucy 2 / mini run Python 3.9

import argparse
import datetime as dt
import sys
import traceback

from automations.indeed_source_report import fetch, parse
from automations.indeed_source_report.offices import OFFICES
from automations.indeed_source_report.run import CITY_AGNOSTIC, _headline

from . import names, sheet, weeks

CARD_ID = "ad-sales-board"
CARD_NAME = "Ad Sales Board (weekly Source Report)"
# Same `standalone-` family prefix as the monthly job, for the same reason: the
# watcher's miss reports and this job's own crash posts must share one incident
# thread instead of talking past each other.
INCIDENT_KEY = "standalone-ad-sales-board"


def _publish_outcome(status, headline, details, *, started_at=None, dry_run=False):
    """Hub run row + corrections-channel alert, both best-effort — copied from
    the monthly job (see its comment for the standing rules this implements)."""
    if dry_run:
        return
    import os
    if not os.environ.get("HUB_REPORT_ID"):
        try:
            from automations.shared import hub_activity
            hub_activity.log_completed(CARD_ID, CARD_NAME, status=status,
                                       started_at=started_at)
        except Exception:  # noqa: BLE001 — reporting never sinks the report
            pass
    try:
        if status == "success":
            from automations.shared import incident_thread as _inc
            _inc.resolve_if_open(INCIDENT_KEY, what="*Ad Sales Board*",
                                 detail="Clean refresh — every office wrote.")
        else:
            from automations.day_orchestrator import notify
            notify.post_alert(headline, details, tag=INCIDENT_KEY,
                              incident=INCIDENT_KEY, label="*Ad Sales Board*")
    except Exception as e:  # noqa: BLE001 — Slack must not fail the run
        print("  (corrections post skipped: %s)" % e, flush=True)


def ads_for_week(html):
    """Merged ad rows for one office-week — the monthly parse.

    The "[Action required] New application for" wrapper is stripped BEFORE the
    noise filter sees it: parse.NOISE would junk those rows and they are real
    applicants. `parse.load_table` does that per-subject since 2026-08-27, so
    the substitution here is belt-and-braces — it stays because `rescued_total`
    is counted off this same HTML, and because a plain text substitution on the
    HTML reaches the table cells the subjects live in."""
    return parse.ads_for_month(names.WRAPPER.sub("", html))


def _owner_expect():
    """office id -> the owner name AppStream prints for it (roster spelling)."""
    from automations.funnel_board.roster import CAPTAINSHIP, ORG
    return {str(o): w for n, o, w in list(ORG) + list(CAPTAINSHIP)}


def _same_owner(got, want):
    """True when two owner spellings name the same person.

    Token overlap, not equality: the roster carries AppStream's own spelling
    and it varies in case and form ('CARLOS HIDALGO' vs 'Carlos Hidalgo',
    Salik's office listed under 'Muhammad UI Haque'). Any shared name token
    passes; a completely different person shares none.
    """
    a = {w for w in str(got).lower().split() if w.isalpha()}
    b = {w for w in str(want).lower().split() if w.isalpha()}
    return bool(a and b and (a & b))


def pull_day(page, tok, d, agnostic, want_owner=None):
    """Received-per-ad for ONE day: (pieces, day total).

    An AppStream day report that comes back with a header but no data rows is
    indistinguishable from a day on which nobody applied — `parse` simply
    yields no ads and nothing raises. That silent empty happened to roughly
    one office-day in thirty on 2026-08-27 (Jamis lost Thu/Fri/Sat, Aya a
    Wednesday, Jackie a Sunday — whole days blank across every one of their
    ads), so an empty day is re-submitted once before it is believed. The
    caller decides what to do with a still-empty day; this never writes zeros
    over a day it could not read.
    """
    for attempt in (1, 2):
        html, owner, _n = fetch.source_report(
            page, tok, weeks.fmt_mdY(d), weeks.fmt_mdY(d))
        if want_owner and not _same_owner(owner, want_owner):
            raise RuntimeError(
                "WRONG OFFICE on %s: asked for %r, the report came back for "
                "%r. Another job sharing this AppStream session switched the "
                "office mid-run; refusing to attribute one office's emails to "
                "another." % (d.isoformat(), want_owner, owner))
        ads, _flags = ads_for_week(html)
        if agnostic:
            ads = parse.merge_across_cities(ads)
        total = sum(g["rec"]["apps"] for g in ads)
        if total or attempt == 2:
            return ads, total
        print("     (%s came back empty — re-submitting once)" % d.isoformat(),
              flush=True)
    return [], 0


def slot_totals(block):
    """(per-slot totals, per-slot known?) over one (manager, week) carry block."""
    tot, known = [0] * 7, [False] * 7
    for slots in block.values():
        for i, v in enumerate(slots):
            if v != "":
                known[i] = True
                tot[i] += v
    return tot, known


def _closest(base, cands, floor=0.5):
    """The ad on this inbox whose role best matches `base`, or [] if none is
    close enough.

    A one-day window merges fewer title variants than a seven-day one, so the
    same posting can land on a different base role. Exact matching then drops
    real emails: Carlos's April weeks lost 192 in a single week that way, all
    from inboxes running more than one ad, which the unambiguous-inbox rule
    deliberately refuses. Token overlap recovers those without ever crediting
    an ad that is merely on the same account.
    """
    want = set(base.split())
    if not want:
        return []
    best, score = None, 0.0
    for g in cands:
        have = set(g["base"].lower().split())
        if not have:
            continue
        j = len(want & have) / float(len(want | have))
        if j > score:
            best, score = g, j
    return [best] if best is not None and score >= floor else []


def ad_key(inbox, title, city, agnostic):
    """Stable identity for one merged ad row, used to carry the accumulated
    received-per-day counts (T..Z) across rewrites: the weekly refresh
    regenerates every row, but a finished day's count can only come from the
    one-day pull that captured it. City-agnostic managers merge cities, so
    their key skips the (joined, order-sensitive) city string."""
    k = (inbox, parse.base_role(title).lower())
    return k if agnostic else k + (str(city).lower(),)


def rows_for(manager, label, week_start, ads, name_rows, day_recv):
    """The data-tab rows for one (manager, week): a WEEK ENDING band row first
    (the visible board is one stacked scroll of all weeks — the band is each
    block's blue divider), then one row per ad (Pull, its names, L..R = names
    sent to call list per DAY, S = the ad's rank in its week, and T..Z =
    emails RECEIVED per day Monday..Sunday from the one-day pulls), an
    unmatched-names row when the join couldn't place someone, and a TOTAL row
    last (label in the Ad Title column — the board's first visible column).
    A manager with NO name feed at all (the captainship-only offices) gets
    blank name cells, not zeros — blank means "no feed"; same idea for T..Z:
    blank means "that day was never pulled", zero means "pulled, nobody came".

    `day_recv` maps ad_key -> 7-slot list (int or "") of received counts."""
    iso = week_start.isoformat()
    agnostic = manager in CITY_AGNOSTIC
    names_for, days_for, unmatched, unmatched_days = names.attach(
        ads, name_rows, agnostic, week_start)
    fed = bool(name_rows)

    def day_cells(counts):
        if not fed:
            return [""] * 7
        # blank for a zero day — the sales boards leave no-sale days empty
        return [c if c else "" for c in counts]

    sunday = week_start + dt.timedelta(days=6)
    out = [[manager, label, "", "", "WEEK ENDING %s — %s"
            % (sunday.strftime("%-m/%-d"), label),
            "", "", "", "", "", iso] + [""] * 15]
    tot = parse.blank()
    for g in ads:
        for f in parse.FIELDS:
            tot[f] += g["rec"][f]
    tot_days = [0] * 7
    tot_recv = [""] * 7
    for rank, g in enumerate(ads, 1):
        got = names_for.get(id(g), [])
        days = days_for.get(id(g), [0] * 7)
        tot_days = [a + b for a, b in zip(tot_days, days)]
        recv = day_recv.get(ad_key(g["inbox"], g["title"], g["city"], agnostic),
                            [""] * 7)
        tot_recv = [(a if a != "" else 0) + b if b != "" else a
                    for a, b in zip(tot_recv, recv)]
        out.append([manager, label, parse.account_name(g["inbox"]), g["inbox"],
                    g["title"], g["city"], g["rec"]["apps"], g["rec"]["scl"],
                    len(got) if fed else "", ", ".join(got), iso]
                   + day_cells(days) + [rank] + list(recv))
    if unmatched:
        tot_days = [a + b for a, b in zip(tot_days, unmatched_days)]
        out.append([manager, label, "—", "", "— names with no matching ad —",
                    "", "", "", len(unmatched), ", ".join(unmatched), iso]
                   + day_cells(unmatched_days) + [""] * 8)
    n_names = sum(len(v) for v in names_for.values()) + len(unmatched)
    out.append([manager, label, "", "", "TOTAL", "", tot["apps"], tot["scl"],
                n_names if fed else "", "", iso] + day_cells(tot_days) + [""]
               + tot_recv)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--office", action="append", help="limit to office id(s)")
    ap.add_argument("--weeks", type=int, default=2,
                    help="how many ad-weeks back from today, current included (default 2)")
    ap.add_argument("--anchor", action="append",
                    help="explicit week anchor(s) mm-dd-yyyy (any day in the week works)")
    ap.add_argument("--day", action="append",
                    help="one-day received pull(s) mm-dd-yyyy (fills that day's "
                         "AC..AI slot; default: yesterday, unless --anchor is used)")
    ap.add_argument("--allow-shrink", action="store_true",
                    help="accept a pull whose weekly total is LOWER than what "
                         "is stored (normally rejected as a short pull — pass "
                         "this only when a parser change really did lower it)")
    ap.add_argument("--heal-days", type=int, default=14,
                    help="re-pull any missing day this many days back when a "
                         "week's day counts fall short of its weekly total "
                         "(0 disables; default 14)")
    ap.add_argument("--reset", action="store_true",
                    help="drop ALL existing data rows before writing — only for "
                         "week-definition migrations (e.g. the Wed→Mon switch); "
                         "every kept week must be re-pulled afterwards")
    ap.add_argument("--headed", action="store_true")
    a = ap.parse_args(argv)
    run_started = dt.datetime.now()
    today = dt.date.today()

    if a.anchor:
        wins = [weeks.window(weeks.anchor_for(
            dt.datetime.strptime(x, "%m-%d-%Y").date())) for x in a.anchor]
    else:
        wins = weeks.windows_back(max(1, a.weeks), today)

    # Received-per-day: the Source Report only aggregates a range, so a day's
    # count exists only if that single day was pulled. The daily run pulls
    # YESTERDAY (final once the day ended) and the counts accumulate in T..Z;
    # --day backfills specific days. Every day target's week must be in the
    # weekly windows, or its rows would never be rewritten.
    if a.day:
        day_targets = [dt.datetime.strptime(x, "%m-%d-%Y").date() for x in a.day]
    elif not a.anchor:
        day_targets = [today - dt.timedelta(days=1)]
    else:
        day_targets = []
    have = {s for _l, s, _e in wins}
    for d in day_targets:
        anc = weeks.anchor_for(d)
        if anc not in have:
            wins.append(weeks.window(anc))
            have.add(anc)
    targets = [(o, n) for o, n in OFFICES if not a.office or o in a.office]
    print("[ad_sales_board] weeks: %s — days: %s — %d offices"
          % (", ".join(w[0] for w in wins),
             ", ".join(d.isoformat() for d in day_targets) or "none",
             len(targets)), flush=True)

    # Preflight, same reason as the monthly job: prove the write BEFORE a long
    # browser pull, or a permission fault wastes the whole pass.
    sess = sheet.session(verbose=True)
    if not a.dry_run:
        try:
            # Three attempts: sheets.googleapis.com read-timeouts come in
            # bursts (three consecutive runs aborted on one 2026-09-01), and a
            # transient network blip should not kill a run that hasn't pulled
            # anything yet. A real permission fault fails all three instantly.
            for _probe in (1, 2, 3):
                try:
                    sheet.probe_write(sess)
                    break
                except Exception:  # noqa: BLE001
                    if _probe == 3:
                        raise
                    print("[ad_sales_board] preflight probe failed (attempt "
                          "%d/3) — retrying in 20s" % _probe, flush=True)
                    import time as _t
                    _t.sleep(20)
        except Exception as e:  # noqa: BLE001 — the reason matters more than the trace
            print("[ad_sales_board] ABORT — cannot write the workbook as this "
                  "machine's identity: %s" % str(e)[:200], flush=True)
            print("  fix: run build_tab.py once if the 'Ad Sales Data' tab does "
                  "not exist yet; otherwise install the applicant_tracker "
                  "service-account key or share the workbook with this machine. "
                  "Nothing was pulled and nothing was changed.", flush=True)
            _publish_outcome(
                "failed",
                "🧲 *Ad Sales Board ABORTED — this machine can't write the workbook*",
                ["• Preflight write failed before anything was pulled: %s" % str(e)[:200],
                 "• If the 'Ad Sales Data' tab is missing, run "
                 "automations/ad_sales_board/build_tab.py once from the laptop.",
                 "• Nothing was pulled and nothing was changed."],
                started_at=run_started, dry_run=a.dry_run)
            return 3

    # Names first — a plain Sheets read; if it fails nothing was pulled yet.
    call_rows = names.load_call_list(sess, sheet.API)
    print("[ad_sales_board] call-list rows loaded: %d" % len(call_rows), flush=True)

    # Existing rows are read BEFORE the browser opens: rewriting a week must
    # CARRY OVER its accumulated received-per-day cells (AC..AI) — those came
    # from one-day pulls on days now gone, and cannot be re-derived. Rows are
    # normalized to the internal 26-wide shape (A..S + the 7 recv slots); the
    # helper columns T..AB in between are never part of a row.
    if a.reset:
        print("[ad_sales_board] --reset: dropping ALL existing rows", flush=True)
        existing = []
    else:
        existing = []
        for r in sheet.get_values(sess, sheet.data_range("A2:AI20000")):
            r = list(r) + [""] * (35 - len(r))
            existing.append(r[:19] + r[28:35])
    carry = {}   # (manager, label) -> {ad_key: [7 recv slots]}
    for r in existing:
        if not r[0] or not r[1] or r[4] == "TOTAL" or r[2] == "—" \
                or str(r[4]).startswith("WEEK ENDING"):
            continue
        slots = [_int_or_blank(v) for v in r[19:26]]
        carry.setdefault((r[0], r[1]), {})[
            ad_key(r[3], r[4], r[5], r[0] in CITY_AGNOSTIC)] = slots

    from automations.shared.tableau_patchright import appstream_direct_session
    fresh, failures = {}, []      # fresh[(manager, label)] = data rows
    rescued_total = 0
    expect = _owner_expect()
    empty_days = []               # (manager, date) a day report would not read
    # allow_form_login ONLY when a human asked for a headed run. AppStream put an
    # interactive human-check on the login form in v2026.08.20.1, so unattended
    # that path CANNOT complete — it just crashes with "console never rendered
    # #searchMC after login", which reads like a site change and sends whoever
    # picks it up hunting for the wrong thing. This report was the last one still
    # passing True (2026-08-27); every other scheduled AppStream/Tableau report
    # passes False (d793ea3). With False the run stops on the reuse failure and
    # says the one thing that fixes it: re-seed the session.
    with appstream_direct_session(headless=not a.headed, verbose=False,
                                  allow_form_login=a.headed) as page:
        tok = fetch.token(page)
        for oid, name in targets:
            try:
                fetch.select_office(page, tok, oid)
                agnostic = name in CITY_AGNOSTIC
                want_owner = expect.get(str(oid))
                weekly = []
                for label, start, end in wins:
                    html, owner, nrows = fetch.source_report(
                        page, tok, weeks.fmt_mdY(start), weeks.fmt_mdY(end))
                    if want_owner and not _same_owner(owner, want_owner):
                        raise RuntimeError(
                            "WRONG OFFICE for %s: asked for %r, the report came "
                            "back for %r. Another job sharing this AppStream "
                            "session switched the office mid-run."
                            % (label, want_owner, owner))
                    rescued = len(names.WRAPPER.findall(html))
                    rescued_total += rescued
                    ads, _flags = ads_for_week(html)
                    if agnostic:
                        ads = parse.merge_across_cities(ads)
                    weekly.append((label, start, ads, nrows, rescued))
                # SELF-HEAL. A week's day counts must add up to its weekly
                # total; when they fall short, the missing days are days this
                # office never actually captured (an empty day report, a
                # failed run, or a week that predates day tracking). Re-pull
                # exactly those, so the board converges on its own instead of
                # needing someone to notice and queue a backfill. The
                # reconciliation identity is what makes this terminate: a week
                # whose days already add up is never re-pulled, so genuine
                # zero-days cost nothing.
                heal = []
                for label, start, ads, _n, _r in weekly:
                    if a.heal_days <= 0 or (today - start).days > a.heal_days:
                        continue
                    tot, known = slot_totals(carry.get((name, label), {}))
                    if sum(tot) >= sum(g["rec"]["apps"] for g in ads):
                        continue                  # already fully accounted for
                    for i in range(7):
                        d = start + dt.timedelta(days=i)
                        if known[i] or d >= today or d in day_targets:
                            continue              # today is still filling up
                        heal.append(d)
                if heal:
                    print("     [heal] %-22s re-pulling %s"
                          % (name[:22], ", ".join(d.isoformat() for d in heal)),
                          flush=True)

                # One-day pulls: a finished day's received count per ad. Kept
                # as raw pieces — a one-day window can merge/fold cities
                # differently than the week's (fewer cities visible), so each
                # piece is matched onto the WEEK's ad rows below, fuzzily,
                # the same way names.attach does.
                day_pieces = {}   # label -> [(inbox, base, city, slot, n)]
                pulled_slots = {}  # label -> {slot} actually re-read this run
                for d in sorted(set(day_targets) | set(heal)):
                    anc = weeks.anchor_for(d)
                    dlabel = weeks.window(anc)[0]
                    dads, dtotal = pull_day(page, tok, d, agnostic, want_owner)
                    if not dtotal:
                        # Blank, not zero: a day we could not read must stay
                        # visibly missing so the heal pass retries it.
                        empty_days.append((name, d))
                        continue
                    slot = (d - anc).days
                    pulled_slots.setdefault(dlabel, set()).add(slot)
                    for g in dads:
                        if g["rec"]["apps"]:
                            day_pieces.setdefault(dlabel, []).append(
                                (g["inbox"], g["base"].lower(),
                                 g["city"].lower(), slot, g["rec"]["apps"]))
                for label, start, ads, nrows, rescued in weekly:
                    recv = {k: list(v)
                            for k, v in carry.get((name, label), {}).items()}
                    # Clear every slot this run re-read, across all ads, before
                    # applying. Otherwise a day's old value survives on the ad
                    # it used to be credited to while the new value lands on
                    # another — the counts are then held twice. That is exactly
                    # what the closest-title matching exposed on 2026-08-29:
                    # eight of Carlos's weeks swung from under-counting to
                    # over-counting (Apr 27: +256) the moment pieces started
                    # landing on different rows than before. Days that came
                    # back empty are NOT cleared — an unread day must not
                    # destroy what an earlier run legitimately captured.
                    for _slot in pulled_slots.get(label, ()):
                        for _v in recv.values():
                            _v[_slot] = ""
                    # map this run's day pieces onto the week's ad rows:
                    # exact (inbox, base, city) first, else (inbox, base)
                    # taken by the biggest Pull; re-pulled days REPLACE the
                    # carried value, split pieces landing on one row SUM.
                    by_inbox = {}
                    for g in ads:
                        by_inbox.setdefault(g["inbox"], []).append(g)
                    applied, missed, unmatched_keys = {}, 0, []
                    for inbox, base, city, slot, n in day_pieces.get(label, []):
                        cands = [g for g in ads
                                 if g["inbox"] == inbox
                                 and g["base"].lower() == base]
                        if not cands:
                            # A one-day window merges fewer variants than a
                            # seven-day one, so the same posting can carry a
                            # different base role on the day than in the week.
                            # When the inbox runs exactly ONE ad that week the
                            # answer is unambiguous, so take it. With several,
                            # guessing would put real numbers on the wrong ad
                            # row — a silent wrong beats nothing, so it stays
                            # dropped and gets named in the log instead.
                            sole = by_inbox.get(inbox, [])
                            if len(sole) == 1:
                                cands = sole
                            elif sole:
                                # Several ads on this inbox: take the closest
                                # title rather than drop real emails. Same
                                # account, near-identical role — far better
                                # than a hole. Below the threshold it still
                                # refuses, so a genuinely different ad is
                                # never credited to the wrong row.
                                cands = _closest(base, sole)
                        if not cands:
                            missed += n
                            if len(unmatched_keys) < 4:
                                unmatched_keys.append("%s | %s"
                                                      % (inbox, base[:38]))
                            continue
                        exact = [g for g in cands
                                 if g["city"].lower() == city]
                        tgt = (exact[0] if len(exact) == 1
                               else max(cands, key=lambda g: g["rec"]["apps"]))
                        k = ad_key(tgt["inbox"], tgt["title"], tgt["city"],
                                   agnostic)
                        applied[(k, slot)] = applied.get((k, slot), 0) + n
                    carried = sum(1 for s in recv.values()
                                  if any(x != "" for x in s))
                    for (k, slot), n in applied.items():
                        recv.setdefault(k, [""] * 7)[slot] = n
                    if applied or carried or missed:
                        # Name the manager and the week: a bare "N dropped"
                        # line cannot be traced back to an office, which cost
                        # an hour on 2026-08-27. When pieces are dropped, name
                        # the inbox+base that would not join too — that is the
                        # evidence needed to fix the join rather than guess.
                        print("     [recv] %-22s %-22s carried=%d applied=%d "
                              "dropped=%d%s"
                              % (name[:22], label, carried, len(applied), missed,
                                 ("  unmatched: " + "; ".join(unmatched_keys))
                                 if unmatched_keys else ""), flush=True)
                    wk_names = names.in_window(call_rows, name, start, end=start + dt.timedelta(days=6))
                    fresh[(name, label)] = rows_for(name, label, start, ads,
                                                    wk_names, recv)
                    print("  OK   %-24s %-22s raw=%-4d ads=%-3d pull=%-5d names=%d%s"
                          % (name[:24], label, nrows, len(ads),
                             sum(g["rec"]["apps"] for g in ads), len(wk_names),
                             "  (+%d wrapped subjects kept)" % rescued if rescued else ""),
                          flush=True)
            except Exception as e:  # noqa: BLE001 — one office must not kill the run
                failures.append((oid, name, _headline(e)))
                print("  FAIL %-24s %s" % (name, _headline(e)[:70]), flush=True)
                # The WHOLE error, unclipped — a failure you cannot read is a
                # failure you cannot fix (see the monthly job, 2026-08-24).
                for ln in str(e).strip().splitlines():
                    print("       | %s" % ln.rstrip()[:200], flush=True)

    if not fresh:
        print("nothing pulled — leaving the sheet alone", flush=True)
        _publish_outcome("failed",
                         "🧲 *Ad Sales Board — nothing pulled, sheet left alone*",
                         ["• Every office failed; see the log."],
                         started_at=run_started, dry_run=a.dry_run)
        return 1

    # SHRINK GUARD. Emails only accumulate, so a week's total can never fall.
    # When a fresh pull comes back SMALLER than what is already stored, the
    # pull is short — not the truth — and writing it destroys good data:
    # 2026-08-27, Drew Tepper's finished Aug 17-23 week (746, reconciled
    # against all seven of its days) was overwritten by a 416 pull, taking his
    # day counts with it. Keep the stored block and say so.
    stored_total = {}
    for r in existing:
        if len(r) > 10 and r[0] and r[4] == "TOTAL" and isinstance(r[6], (int, float)):
            stored_total[(r[0], r[1])] = r[6]
    shrunk = []
    for key in list(fresh):
        tr = [r for r in fresh[key] if r[4] == "TOTAL"]
        was, now = stored_total.get(key), (tr[0][6] if tr else None)
        # Tolerance: AppStream's own history drifts a little as spam and
        # duplicates are removed server-side — a fresh pull of 1072 against a
        # stored 1077 is churn, not a short pull, and rejecting it froze
        # Carlos's Apr 27 week in its over-counted state (2026-09-01). Reject
        # only a MEANINGFUL shrink: more than 2% AND more than 10 emails.
        # The wrong-office pulls this guard exists for miss by 30-70%.
        meaningful = (was and isinstance(now, (int, float))
                      and (was - now) > max(10, was * 0.02))
        if meaningful and not a.allow_shrink:
            shrunk.append((key[0], key[1], was, now))
            del fresh[key]                 # keep what is already on the sheet
    if shrunk:
        print("\nSHORT PULLS REJECTED — kept the stored week instead (re-run "
              "those offices, or pass --allow-shrink if a parser change really "
              "did lower the counts):", flush=True)
        for mgr, label, was, now in shrunk:
            print("   %-24s %-22s stored=%-6d pulled=%-6d" % (mgr[:24], label, was, now),
                  flush=True)

    # Freeze rule: rewrite only the (manager, week) pairs this run pulled.
    # `existing` was read before the browser opened (the AC..AI carry needed it).
    pulled = set(fresh)
    keep = [r for r in existing
            if len(r) > 1 and r[0] and (r[0], r[1]) not in pulled]
    new = list(keep)
    for key in fresh:
        new.extend(fresh[key])
    print("[ad_sales_board] refreshed %d manager-weeks; kept %d existing rows"
          % (len(pulled), len(keep)), flush=True)

    # Deterministic order: roster, then week newest-first (column K is ISO so
    # it sorts as text), leaving each block's internal pull-desc order alone.
    order = {n: i for i, (_o, n) in enumerate(OFFICES)}
    block = {}
    for i, r in enumerate(new):
        block.setdefault((r[0], r[1]), i)
    new.sort(key=lambda r: (order.get(r[0], 999),
                            _desc_iso(r[10] if len(r) > 10 else ""),
                            block[(r[0], r[1])]))
    new = _numeric_cols(new)

    managers = sorted({r[0] for r in new}, key=lambda m: order.get(m, 999))
    week_list = sorted({(r[10] if len(r) > 10 else "", r[1]) for r in new},
                       reverse=True)
    week_labels = [w[1] for w in week_list]

    if a.dry_run:
        print("\nDRY RUN — would write %d rows (%d managers, %d weeks: %s)"
              % (len(new), len(managers), len(week_labels),
                 ", ".join(week_labels[:6])), flush=True)
    else:
        # Two ranges on purpose: the helper columns T..AB between them must
        # never be touched by a row write (see sheet.py).
        sheet.clear(sess, sheet.data_range("A2:S20000"))
        sheet.clear(sess, sheet.data_range("AC2:AI20000"))
        sheet.put_values(sess, sheet.data_range("A2"),
                         [(list(r) + [""] * 26)[:19] for r in new])
        sheet.put_values(sess, sheet.data_range("AC2"),
                         [(list(r) + [""] * 26)[19:26] for r in new])
        sheet.put_values(sess, sheet.data_range("W2"),
                         [[managers[i] if i < len(managers) else "",
                           week_labels[i] if i < len(week_labels) else ""]
                          for i in range(max(len(managers), len(week_labels)))])
        print("[ad_sales_board] wrote %d rows" % len(new), flush=True)
        # No week picker to stamp any more: the visible board is one stacked
        # scroll of every week, newest on top (Carlos 2026-08-27 — "no
        # dropdown i just have to scroll down").

    # RECONCILIATION. A finished week's day counts must add up to its weekly
    # total; anything else means days are missing or double-counted. Checking
    # it here is the difference between the job telling us and someone
    # noticing weeks later — which is exactly how the 2026-08-27 gaps were
    # found (by hand, after the fact).
    short = []
    for (mgr, label), rws in fresh.items():
        tr = [r for r in rws if len(r) > 10 and r[4] == "TOTAL"]
        if not tr:
            continue
        r = list(tr[0]) + [""] * 26
        start = dt.date.fromisoformat(r[10])
        if start + dt.timedelta(days=6) >= today:
            continue                       # week still filling up
        pull = r[6] if isinstance(r[6], (int, float)) else 0
        got = sum(v for v in r[19:26] if isinstance(v, (int, float)))
        if pull and got != pull:
            short.append((mgr, label, pull, got))
    if short:
        print("\nDAY COUNTS DO NOT RECONCILE (finished weeks) — the heal pass "
              "will retry the missing days on the next run:", flush=True)
        for mgr, label, pull, got in sorted(short):
            print("   %-24s %-22s weekly=%-6d days=%-6d diff=%+d"
                  % (mgr[:24], label, pull, got, got - pull), flush=True)
    else:
        print("\nDay counts reconcile against the weekly totals for every "
              "finished week written.", flush=True)
    if empty_days:
        print("\nDay reports that came back EMPTY twice (left blank, not zero; "
              "the heal pass retries them):", flush=True)
        for mgr, d in empty_days:
            print("   %-24s %s" % (mgr[:24], d.isoformat()), flush=True)

    if rescued_total:
        print("\n%d '[Action required] New application for …' subjects were "
              "unwrapped and counted as real ads this run." % rescued_total,
              flush=True)
    if failures:
        print("\nFAILED OFFICES (%d) — their weeks were left untouched:" % len(failures),
              flush=True)
        for oid, name, err in failures:
            print("   %-8s %-30s %s" % (oid, name[:30], err), flush=True)
        _publish_outcome(
            "partial",
            "🧲 *Ad Sales Board — %d of %d office(s) did not refresh*"
            % (len(failures), len(targets)),
            ["• %s (%s): %s" % (name, oid, str(err)[:160])
             for oid, name, err in failures]
            + ["• Their weeks were left untouched; every other office wrote."],
            started_at=run_started, dry_run=a.dry_run)
        return 2
    _publish_outcome("success", "", [], started_at=run_started, dry_run=a.dry_run)
    return 0


def _desc_iso(iso):
    """Sort helper: ISO date -> string that orders newest FIRST under plain
    ascending sort (works because the digits are fixed-width)."""
    return "".join(chr(255 - ord(c)) for c in str(iso))


def _int_or_blank(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return ""


def _numeric_cols(rows):
    """Re-type Pull / To Call List / # Names (G,H,I = idx 6..8), the two day
    grids (L..R names = idx 11..17, T..Z received = idx 19..25) and the Rank
    (S = idx 18) on recycled rows, same reason as the monthly job's _numeric:
    sheet-recycled values come back as strings and text numbers kill numeric
    formats and future CF."""
    out = []
    for r in rows:
        rr = list(r)
        for i in (6, 7, 8, 11, 12, 13, 14, 15, 16, 17, 18,
                  19, 20, 21, 22, 23, 24, 25):
            if i < len(rr) and isinstance(rr[i], str) and rr[i].strip():
                try:
                    rr[i] = int(float(rr[i]))
                except ValueError:
                    pass
        out.append(rr)
    return out


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        _tail = traceback.format_exc().strip().splitlines()[-1][:200]
        _publish_outcome(
            "failed",
            "🧲 *Ad Sales Board CRASHED before finishing*",
            ["• %s" % _tail,
             "• Full traceback in output/logs/ad_sales_board_*.log on the "
             "machine that ran it."],
            dry_run=("--dry-run" in sys.argv))
        sys.exit(1)
