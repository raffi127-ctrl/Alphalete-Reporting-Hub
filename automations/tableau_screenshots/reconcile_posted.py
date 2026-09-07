"""Declare the boards each channel is OWED today, read what actually landed in
today's thread, and raise a real incident on the difference.

WHY THIS EXISTS (2026-09-07)
----------------------------
Lucy 3's ownerville session went cold at 02:18 and never re-seeded, so the
morning capture run died on the Tableau SSO hop:

    _sso_to_tableau -> page.goto(sso_url) -> patchright TimeoutError

EIGHT of the nine boards never posted to ANY channel, and nothing alerted. The
only incident in #claudecorrections-and-requests that morning was
`failure-tableau_screenshots_box` — about the ONE board that DID post. The
channel made the small failure loud and the big one silent, which is the exact
inversion that costs a morning.

run.py already reconciles posted-vs-expected (`missing_trackers`, `held`) and
that logic is correct — but it lives INSIDE the run, between the capture loop and
`write_manifest()`. A run that DIES never reaches it: no manifest, no
section_drop_alert, no incident. "The report crashed" and "the report quietly
delivered 1 of 9" look identical from the channel.

So this check does not depend on the run surviving. It reads the EXPECTED set
from pages.py/slack_post.py (the same declarations the poster uses, so they can
never drift) and the ACTUAL set from the channels themselves, and compares. It
can run after a crashed capture, from a different machine, or as its own agent.

WHAT COUNTS AS A REAL MISS (the churn "declare expected, stay quiet when you
genuinely can't tell" rule)
-----------------------------------------------------------------------------
Three outcomes per channel, never two:

  • thread absent          -> the whole day's post is missing (kind 'no_post').
  • thread present, gaps   -> those boards are genuinely missing (kind 'section').
  • channel UNREADABLE     -> say nothing about it. `find_thread_ts` raises
                              DedupReadUnavailable when the history read itself
                              fails, and "I couldn't look" must never be reported
                              as "it isn't there" — that is how a red circle
                              turns into noise people stop reading. Unreadable
                              channels are counted and NAMED in the note, so the
                              gap in coverage is visible without being an alarm.

A LATE board (Box) is not missing until its catch-up has had its window: before
`LATE_DUE_HHMM` it is deliberately absent and reporting it would fire every
single morning. Same for a board held for a stale extract — the settle passes run
to 14:00, so the honest deadline for "this board is not coming" is after them.

DEDUP / NOISE. The alert goes through section_drop_alert, so it inherits the
incident thread, the 45-minute cooldown and the ✅-on-clean-run close. A board
missing from EVERY channel is reported ONCE ("all channels"), not once per
channel — 8 boards x 10 orgs would otherwise be 80 bullet lines in a channel
whose whole design rule is that a drop reads at a glance.

  python -m automations.tableau_screenshots.reconcile_posted            # report
  python -m automations.tableau_screenshots.reconcile_posted --alert    # + incident
  python -m automations.tableau_screenshots.reconcile_posted --date 2026-09-07
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from automations.tableau_screenshots import pages as pages_mod
from automations.tableau_screenshots import slack_post as sp

# The report id the incident is filed under. Deliberately the MORNING run's id,
# not a new one: a missing board is that report's failure, so the ✅ that
# `section_drop_alert.resolved()` puts on a clean tableau_screenshots run closes
# this thread too, instead of leaving a second thread nobody owns.
REPORT_ID = "tableau-screenshots"

# Before this, a `late` board (Box) is SUPPOSED to be absent — the ~7am catch-up
# has not run. Reporting it earlier would alert every morning at 4:31.
LATE_DUE_HHMM = "09:00"

# Before this, a board the morning run HELD for a stale extract may still be
# coming: the settle passes run hourly 10:00-14:00 (schedule_config
# tableau_screenshots_settle_*). After the last one, nobody is coming.
SETTLE_DONE_HHMM = "14:30"


@dataclass
class OrgResult:
    org: str
    expected: List[str] = field(default_factory=list)
    present: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    thread_missing: bool = False
    unreadable: str = ""          # non-empty = we could not look; NOT a miss

    @property
    def label(self) -> str:
        return sp.ORG_LABEL.get(self.org, self.org)


@dataclass
class Reconciliation:
    day: dt.date
    orgs: List[OrgResult] = field(default_factory=list)

    @property
    def readable(self) -> List[OrgResult]:
        return [o for o in self.orgs if not o.unreadable]

    @property
    def unreadable(self) -> List[OrgResult]:
        return [o for o in self.orgs if o.unreadable]

    @property
    def threads_missing(self) -> List[OrgResult]:
        return [o for o in self.readable if o.thread_missing]

    @property
    def with_gaps(self) -> List[OrgResult]:
        return [o for o in self.readable if o.missing and not o.thread_missing]

    @property
    def clean(self) -> bool:
        """True when every channel we COULD read has everything it is owed.

        An unreadable channel does not make the day clean OR dirty — it makes it
        unknown, and unknown is reported in the note, never as a drop."""
        return not self.threads_missing and not self.with_gaps

    def missing_everywhere(self) -> List[str]:
        """Board ids absent from EVERY readable channel that expects them."""
        out = []
        for pid in pages_mod.default_ids() + [p["id"] for p in pages_mod.PAGES
                                              if pages_mod.is_opt_in_only(p)]:
            owed = [o for o in self.readable if pid in o.expected]
            if owed and all(pid in o.missing for o in owed):
                out.append(pid)
        return out


def _hhmm_passed(day: dt.date, hhmm: str, now: Optional[dt.datetime]) -> bool:
    """Has `hhmm` passed on `day`? A PAST day is entirely over, so everything is
    due; a FUTURE day nothing is."""
    now = now or dt.datetime.now()
    if now.date() > day:
        return True
    if now.date() < day:
        return False
    h, m = (int(x) for x in hhmm.split(":"))
    return now.time() >= dt.time(h, m)


def expected_for(org: str, day: dt.date, *,
                 now: Optional[dt.datetime] = None) -> List[str]:
    """The board ids `org` should have in today's thread BY NOW.

    Reads the same declarations the poster reads (slack_post.tracker_ids_for ->
    ORG_TRACKERS / pages.default_ids), so an org's board list can never drift
    between what we post and what we audit. A `late` board is excluded until its
    catch-up window has passed."""
    ids = list(sp.tracker_ids_for(org, pages_mod.PAGES))
    if _hhmm_passed(day, LATE_DUE_HHMM, now):
        return ids
    return [i for i in ids if not (pages_mod.by_id(i) or {}).get("late")]


def reconcile(day: Optional[dt.date] = None, *, client=None,
              orgs: Optional[Sequence[str]] = None,
              now: Optional[dt.datetime] = None) -> Reconciliation:
    """Read every channel's thread and diff it against what that channel is owed.

    Never raises for a channel-level problem: an org we cannot read is recorded
    as `unreadable` and excluded from the miss counts."""
    day = day or dt.date.today()
    if client is None:
        from automations.shared import slack_metrics_post as smp
        client = smp._client()
    rep = Reconciliation(day=day)
    for org in (orgs if orgs is not None else list(sp.ORG_CHANNELS)):
        want = expected_for(org, day, now=now)
        res = OrgResult(org=org, expected=want)
        present: set = set()
        seen_any = False
        thread_missing_everywhere = True
        for channel in sp.channels_for(org):
            try:
                ts, _legacy = sp.find_thread_ts(client, channel, day)
            except Exception as e:                    # noqa: BLE001
                # DedupReadUnavailable (or any read failure) = we could not look.
                res.unreadable = f"{type(e).__name__}: {str(e)[:90]}"
                break
            if not ts:
                continue                              # no thread in THIS channel
            thread_missing_everywhere = False
            try:
                got = sp.posted_ids(client, channel, ts, pages_mod.PAGES, day)
            except Exception as e:                    # noqa: BLE001
                res.unreadable = f"{type(e).__name__}: {str(e)[:90]}"
                break
            present = got if not seen_any else (present & got)
            seen_any = True
        if res.unreadable:
            rep.orgs.append(res)
            continue
        if thread_missing_everywhere:
            res.thread_missing = True
            res.missing = list(want)
        else:
            res.present = sorted(present)
            res.missing = [i for i in want if i not in present]
        rep.orgs.append(res)
    return rep


def _title(pid: str) -> str:
    return (pages_mod.by_id(pid) or {}).get("title") or pid


def failed_parts(rep: Reconciliation) -> List[str]:
    """The alert's bullet list — compressed so one bad morning is readable.

    A board missing from every channel that expects it is ONE line, not one per
    channel. 8 boards x 10 orgs is 80 bullets in a channel whose entire design
    rule is that a drop reads at a glance."""
    parts: List[str] = []
    everywhere = set(rep.missing_everywhere())
    for pid in sorted(everywhere):
        parts.append(f"{_title(pid)} — missing from ALL channels")
    for o in rep.threads_missing:
        parts.append(f"{o.label} — no tracker thread at all today")
    for o in rep.with_gaps:
        rest = [i for i in o.missing if i not in everywhere]
        if rest:
            parts.append(f"{o.label} — missing "
                         + ", ".join(_title(i) for i in rest))
    return parts


def alert_if_incomplete(rep: Reconciliation, *, dry_run: bool = False) -> bool:
    """Raise ONE incident for everything this day is still missing.

    Returns True if an alert was posted. A clean day posts nothing — and so does
    a day we could not read, which is the whole point of the unreadable split."""
    parts = failed_parts(rep)
    if not parts:
        return False
    from automations.shared import section_drop_alert as sda
    unread = rep.unreadable
    note = "; ".join(filter(None, [
        f"{len(rep.threads_missing)} channel(s) have NO tracker thread today"
        if rep.threads_missing else "",
        f"{len(unread)} channel(s) could not be read, so nothing is claimed "
        f"about them: " + ", ".join(o.label for o in unread) if unread else "",
        "expected set comes from pages.py + slack_post.ORG_TRACKERS, so this "
        "counts what each channel is actually owed",
    ]))
    kind = "no_post" if (rep.threads_missing and not rep.with_gaps) else "section"
    return sda.alert(
        report_id=REPORT_ID, failed=parts, kind=kind, day=rep.day,
        note=note, dry_run=dry_run,
        remediation={
            "fix": "re-run the capture once the machine's ownerville/Tableau "
                   "session is live (`lucy login_check` on that runner first) — "
                   "`lucy rerun tableau_screenshots_settle_am` posts only what "
                   "is still missing and never duplicates a board already in "
                   "the thread.",
        })


def summary(rep: Reconciliation) -> str:
    lines = [f"=== tracker reconciliation {rep.day} ==="]
    for o in rep.orgs:
        if o.unreadable:
            lines.append(f"  ?  {o.label}: UNREADABLE — {o.unreadable}")
        elif o.thread_missing:
            lines.append(f"  X  {o.label}: NO THREAD "
                         f"(owed {len(o.expected)})")
        elif o.missing:
            lines.append(f"  !  {o.label}: {len(o.present)}/{len(o.expected)} "
                         f"— missing " + ", ".join(_title(i) for i in o.missing))
        else:
            lines.append(f"  ok {o.label}: {len(o.present)}/{len(o.expected)}")
    if rep.clean:
        lines.append("every readable channel has everything it is owed.")
    return "\n".join(lines)


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="Reconcile the tracker boards each channel is owed against "
                    "what actually landed in today's thread.")
    ap.add_argument("--date", help="YYYY-MM-DD (default: today)")
    ap.add_argument("--alert", action="store_true",
                    help="raise an incident when boards are genuinely missing")
    ap.add_argument("--dry-run", action="store_true",
                    help="with --alert, print the alert instead of posting it")
    ap.add_argument("--orgs", default=None,
                    help="comma-separated org keys (default: all)")
    a = ap.parse_args(argv)
    day = dt.date.fromisoformat(a.date) if a.date else dt.date.today()
    orgs = [o.strip() for o in a.orgs.split(",")] if a.orgs else None
    rep = reconcile(day, orgs=orgs)
    print(summary(rep), flush=True)
    if a.alert:
        posted = alert_if_incomplete(rep, dry_run=a.dry_run)
        print("alert posted" if posted else "nothing to alert", flush=True)
    # Exit 0 always: this is a WATCHER. A non-zero exit would make the
    # orchestrator retry it and treat a correctly-detected gap as its own
    # failure, which is how a watcher starts alerting about itself.
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
