"""Did this report DELIVER, or did it merely run?

WHY THIS EXISTS (Megan 2026-09-09)
----------------------------------
The standing requirement for #claudecorrections is one sentence: a ticket goes
green only when the thing is actually fixed. It did not hold, and the reason was
that "ran" and "delivered" were the same word everywhere in the code.

`reconcile.verify` answers `unknown` for any report whose `verify` block says
`not_configured` — 112 of them — and the orchestrator turns `unknown` into DONE
("ran; verify not wired"), which publishes `success`, which calls
`hub_publish._clear_failure`, which posts "RESOLVED. It just ran clean." So a
report that exits 0 having sent nothing closed its own ticket.

leaders_call is the case that proved it. On Monday 2026-09-08 its thread got two
green checks (13:39 and 14:34) and the recognition deck reached neither
#top-leaders-alphalete-org nor #alphalete-gp-sales all day.

WHAT THIS IS
------------
One question with three honest answers, asked from evidence that already exists.
Nothing here is a new source of truth — it reads what the reports and the
orchestrator already write:

    DELIVERED      we can point at proof: today's manifest, the configured
                   verifier, a post-watch done-marker, or the report's own say-so
    NOT_DELIVERED  we looked and the proof is absent
    UNKNOWN        nothing here can tell — and that is NOT permission to go green

THE RULE IT EXISTS TO ENFORCE: only DELIVERED closes a ticket.

WHY UNKNOWN CANNOT MEAN GREEN, AND WHY IT ALSO CANNOT MEAN RED FOREVER
----------------------------------------------------------------------
Turning UNKNOWN into a close is what produced the false greens. Turning it into
a permanent open ticket would be the same mistake pointed the other way — a wall
of false red teaches people to ignore the channel exactly as fast as a wall of
false green, and it would land on 112 reports at once.

So UNKNOWN does neither. It leaves the ticket open, says once in the thread that
the run went clean but nothing could confirm the delivery, and names the report
so its verify gets wired. And for the report classes where delivery genuinely
cannot be observed — a probe, an installer, a one-shot utility whose whole job IS
exiting 0 — the answer is a DECLARATION in schedule_config:

    "close_on": "exit_zero"

Declared per report, never guessed. Same rule as `hand_run_only` and
`logs_on_event_only`: the code does not get to decide that a report is
unverifiable, a person does, in writing, where the next person can read it.

`python -m automations.shared.delivery_check --all` prints the verdict for every
report the orchestrator knows about — the sample Megan asked for before this is
allowed to hold anything back.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = REPO_ROOT / "automations" / "day_orchestrator" / "schedule_config.json"

DELIVERED = "delivered"
NOT_DELIVERED = "not_delivered"
UNKNOWN = "unknown"

# The declared escape hatch. A report whose delivery is not observable says so
# here and its clean run closes its ticket exactly as it always did.
CLOSE_ON_EXIT_ZERO = "exit_zero"

_CFG_CACHE: Optional[dict] = None


def _reports() -> dict:
    global _CFG_CACHE
    if _CFG_CACHE is None:
        try:
            _CFG_CACHE = json.loads(
                _CONFIG_PATH.read_text(encoding="utf-8")).get("reports") or {}
        except Exception:  # noqa: BLE001 — unreadable config: claim nothing
            _CFG_CACHE = {}
    return _CFG_CACHE


def _report(report_id: str) -> dict:
    r = _reports().get(report_id)
    if isinstance(r, dict):
        return r
    # The dashed manifest spelling of the same id (vantura-board-audit vs
    # vantura_board_audit) — the two are used interchangeably across producers.
    want = report_id.replace("_", "-").lower()
    for rid, rec in _reports().items():
        if rid.replace("_", "-").lower() == want and isinstance(rec, dict):
            return rec
    # The Hub CARD id, when it isn't a respelling of the config id: the watcher
    # opens `standalone-brand-health-audit` for config `brand_audit`, and without
    # this its close_on was never read (2026-10-26). Only an unambiguous card —
    # office-metrics alone stands for a dozen configs.
    try:
        from automations.day_orchestrator.hub_publish import _HUB_CARD
        owners = [cid for cid, card in _HUB_CARD.items() if card == report_id]
    except Exception:  # noqa: BLE001 — a lookup aid, never a reason to fail
        owners = []
    if len(owners) == 1 and isinstance(_reports().get(owners[0]), dict):
        return _reports()[owners[0]]
    return {}


def declared_exit_zero(report_id: str) -> bool:
    """Has a PERSON declared that exit 0 is this report's delivery?"""
    return (_report(report_id).get("close_on") or "") == CLOSE_ON_EXIT_ZERO


# ------------------------------------------------------------------ evidence --

def manifest_ids(report_id: str) -> list:
    """Every id this report's manifest could be FILED under, most likely first.

    THE ONE THAT ALMOST SHIPPED WRONG (caught 2026-09-09 by running the sample
    against the mini). A manifest is written under the id the report's own code
    uses, which is very often NOT its schedule_config key: the mini's manifests
    today are `captainship-abp-6days`, `org-sales-board`, `daily-focus`,
    `recruiter-retention-daily` — dashed — while the config keys are
    `captainship_abp_6days`, `org_sales_board`, `daily_focus`,
    `recruiter_retention_daily`. `_clear_failure` is called with the config key.

    Asking only for the config key would have found nothing for almost every
    report that writes a manifest at all — and "no manifest" is UNKNOWN, which
    HOLDS A TICKET OPEN. That is precisely the wall of false red this module is
    under orders not to build, and it would have looked like a design flaw
    rather than a lookup bug.

    notify._manifest_id already resolves the declared half of this
    (schedule_config's `verify: {report_id: …}`); the dashed spelling is the
    undeclared half, and both are tried."""
    out = [report_id]
    dashed = report_id.replace("_", "-").lower()
    if dashed not in out:
        out.append(dashed)
    declared = ((_report(report_id).get("verify") or {}).get("report_id"))
    if declared and declared not in out:
        out.insert(1, declared)
    return out


def _from_manifest(report_id: str, day: dt.date) -> Optional[Tuple[str, str]]:
    """Today's run-manifest, if it wrote one — under any of its spellings.

    A manifest is the report's own account of what it did, and the freshness
    rule is the same one _verify_manifest applies: only TODAY's counts, because
    a run that crashes before writing leaves the prior one in place."""
    m = None
    try:
        from automations.shared.run_manifest import read_manifest
        for mid in manifest_ids(report_id):
            m = read_manifest(mid)
            if m:
                break
    except Exception:  # noqa: BLE001
        return None
    if not m:
        return None
    try:
        if dt.datetime.fromisoformat(m.get("run_ts", "")).date() != day:
            return None                     # stale: not evidence about today
    except Exception:  # noqa: BLE001
        return None
    failed = list(m.get("failed") or [])
    kind = str(m.get("kind") or "")
    if kind in ("finding", "unfilled_icd"):
        # The run did its whole job and is reporting what it SAW. That is a
        # delivery; the finding is a separate ticket that a re-run cannot close
        # (incident_thread.keys_for_clean_run).
        return DELIVERED, "manifest: ran and delivered, with findings to review"
    if failed:
        return NOT_DELIVERED, "manifest: {} part(s) failed — {}".format(
            len(failed), ", ".join(str(f) for f in failed[:3]))
    if m.get("ok") is False:
        return NOT_DELIVERED, "manifest: the run recorded ok=false"
    return DELIVERED, "manifest: nothing failed"


def _from_verifier(report_id: str, day: dt.date) -> Optional[Tuple[str, str]]:
    """The report's own configured `verify` block, run for real.

    `not_configured` is the whole reason this module exists, so it answers
    nothing here rather than the soft pass reconcile gives the orchestrator."""
    rec = _report(report_id)
    vcfg = rec.get("verify") or {}
    vtype = vcfg.get("type") or "not_configured"
    if vtype in ("not_configured", ""):
        return None
    try:
        from automations.day_orchestrator import reconcile
        res = reconcile.verify(type("R", (), {"verify": vcfg})(), day,
                               dry_run=False, verbose=False)
    except Exception as e:  # noqa: BLE001 — a verifier that blows up knows nothing
        return None if not str(e) else None
    if res.unknown:
        return None
    if res.ok:
        return DELIVERED, "verify({}): {}".format(vtype, res.note)
    return NOT_DELIVERED, "verify({}): {}".format(vtype, res.note)


def _from_post_watch(report_id: str, day: dt.date) -> Optional[Tuple[str, str]]:
    """A post-watch done-marker — the file a self-scheduled poster's wrapper
    touches ONLY on a clean post. Machine-local by design, so its absence proves
    nothing on any other box; only its presence is evidence."""
    try:
        from automations.day_orchestrator import post_watch as pw
        for w in pw.WATCH_TARGETS:
            # The incident is keyed by the WATCH id ("stf_field_check__watch"),
            # not the real report id -- matching report_id alone meant no watch
            # ticket could ever read DELIVERED, so failure-stf_field_check__watch
            # stayed open after the 10/17 23:00 run left its marker.
            if report_id not in (w.report_id, w.watch_id):
                continue
            if pw.evaluate(w, day, dt.datetime.now()) == "ok":
                return DELIVERED, "post-watch done-marker present"
    except Exception:  # noqa: BLE001
        return None
    return None


# A review-gated board email's "-approved" phase. The gate writes that Hub row
# when it FINDS the checkmark, before it mails, so the row proves approval, not
# delivery; the gate's own `sent` stamp (board_autosend/<kind>/<day>.json,
# written only after the send returns 0) is the delivery proof. Without this
# probe a clean 7:16 send left its ticket reading "nothing can confirm" all day
# (2026-10-19).
_GATED_EMAILS = {
    "sales-board-screenshot-email-approved": "org",
    "country-sales-board-email-approved": "country",
}


def _from_review_gate(report_id: str, day: dt.date) -> Optional[Tuple[str, str]]:
    key = _GATED_EMAILS.get(report_id)
    if not key:
        return None
    try:
        from automations.board_emails import auto_send as A
        if A.local_sent(A.TARGETS[key], day):
            return DELIVERED, "the review gate stamped today's email sent"
    except Exception:  # noqa: BLE001
        return None
    # Not stamped on THIS box claims nothing: the gate runs on Lucy 1 only.
    return None


def _ledger_ids(report_id: str) -> list:
    """Every id a delivery could have been recorded under: the manifest
    spellings plus the module the report runs (`automations.X.run` -> X),
    which is what an un-tagged standalone run records itself as."""
    ids = list(manifest_ids(report_id))
    for part in (_report(report_id).get("command") or [])[:1]:
        m = re.match(r"automations\.([a-z0-9_]+)", str(part))
        if m and m.group(1) not in ids:
            ids.append(m.group(1))
    return ids


def _last_failed_at(report_id: str, day: dt.date) -> dt.datetime:
    """When this report last alerted today (the failure stamp hub_publish
    writes), else the start of the day. A delivery only counts if it came
    AFTER the failure it is meant to answer."""
    start = dt.datetime.combine(day, dt.time.min)
    try:
        p = REPO_ROOT / "output" / "logs" / f".failalert-{report_id}"
        at = dt.datetime.fromtimestamp(p.stat().st_mtime)
        return at if at.date() == day and at > start else start
    except OSError:
        return start


# ON since 2026-10-19 (Megan: "we need to fix EVERYTHING"). The ledger closes a
# ticket only when nothing better has an opinion (no phase count, verify,
# manifest or post-watch) and only on a delivery made after the last failure.
# Set False to go back to "names the delivery it saw, stays open".
LEDGER_CLOSES = True


def _from_ledger(report_id: str, day: dt.date) -> Optional[Tuple[str, str]]:
    """The delivery ledger: did this report put something in front of its
    audience (a real Slack channel, an email) since it last failed?

    LAST probe on purpose: a manifest naming failed parts, a verifier, a phase
    count all outrank it. It exists for the reports that have none of those —
    20 of the 137 tickets stranded 2026-09-28..10-19 were exactly "ran clean,
    nothing can confirm" on reports that had in fact delivered (Raf
    2026-10-19). Absence claims nothing: UNKNOWN stays UNKNOWN."""
    try:
        from automations.shared import delivery_ledger
        rec = delivery_ledger.delivered_since(
            _ledger_ids(report_id), _last_failed_at(report_id, day))
    except Exception:  # noqa: BLE001
        return None
    if not rec:
        return None
    return DELIVERED, "delivered {} to {} at {}".format(
        rec.get("kind"), rec.get("dest"), str(rec.get("at"))[11:16])


# The Hub Activity log, read at most once a minute per process.
#
# WHY A TTL AND NOT A PLAIN CACHE: the only multi-phase question worth asking is
# "has the LAST pass landed yet", and the 4am orchestrator is one long-lived
# process that is still publishing at 7:30pm. A cache with no expiry would answer
# the evening's phase-2 publish out of the morning's snapshot, undercount, and
# refuse to close a ticket that had genuinely delivered — the false-red this
# module is under orders not to create. A minute is far longer than a sweep and
# far shorter than a phase gap.
_HUB_TTL_S = 60
_HUB_ROWS: Optional[list] = None
_HUB_AT = 0.0


def _hub_rows() -> list:
    """Hub Activity records; [] if they can't be read (which claims nothing)."""
    global _HUB_ROWS, _HUB_AT
    import time
    if _HUB_ROWS is not None and (time.time() - _HUB_AT) < _HUB_TTL_S:
        return _HUB_ROWS
    try:
        from automations.day_orchestrator import hub_publish
        _HUB_ROWS = hub_publish._ws().get_all_records()
    except Exception:  # noqa: BLE001
        _HUB_ROWS = []
    _HUB_AT = time.time()
    return _HUB_ROWS


def _from_phases(report_id: str, day: dt.date) -> Optional[Tuple[str, str]]:
    """A multi-phase card that has not finished today's passes has not delivered,
    whatever else says otherwise. Same declaration hub_publish._phase_complete
    reads (hub_cards daily_runs) — leaders_call's 2pm tab fill writes a perfectly
    good manifest and has sent nothing, which is why this probe runs FIRST."""
    try:
        from automations.day_orchestrator import hub_publish
        want = hub_publish.expected_runs_today(report_id, day)
        if want <= 1:
            return None
        card = hub_publish.hub_card_id(report_id)
        if not card:
            return None
        stamp = day.isoformat()
        got = sum(1 for r in _hub_rows()
                  if str(r.get("Report ID") or "").strip() == card
                  and str(r.get("Started At") or "").startswith(stamp)
                  and str(r.get("Status") or "").strip().lower()
                  in ("success", "done"))
        if got < want:
            return NOT_DELIVERED, "pass {} of {} for today".format(got, want)
    except Exception:  # noqa: BLE001
        return None
    return None


# -------------------------------------------------------------------- verdict --

def verdict(report_id: str, day: Optional[dt.date] = None, *,
            delivered: Optional[bool] = None) -> Tuple[str, str]:
    """(DELIVERED | NOT_DELIVERED | UNKNOWN, why) for `report_id` today.

    `delivered=` is a caller that KNOWS — a report that watched its own post
    land. It outranks everything: nothing here can see more than the code that
    did the sending.

    Order matters. The phase check runs FIRST among the evidence because it is
    the one thing that can be false while every other signal is true: phase 1 of
    leaders_call writes a perfectly good manifest.

    Never raises. An error anywhere answers UNKNOWN, which holds a ticket open —
    the safe direction for this module, and the one that gets noticed."""
    day = day or dt.date.today()
    if delivered is True:
        return DELIVERED, "the run confirmed its own delivery"
    if delivered is False:
        return NOT_DELIVERED, "the run reported it delivered nothing"
    led = None
    try:
        if declared_exit_zero(report_id):
            return DELIVERED, "declared close_on: exit_zero in schedule_config"
        for probe in (_from_phases, _from_verifier, _from_manifest,
                      _from_post_watch, _from_review_gate):
            got = probe(report_id, day)
            if got:
                return got
        led = _from_ledger(report_id, day)
        if led and LEDGER_CLOSES:
            return led
    except Exception as e:  # noqa: BLE001
        return UNKNOWN, "delivery check errored ({})".format(type(e).__name__)
    if led:
        return UNKNOWN, ("its own check isn't wired, but it {} — if that is the "
                         "whole report, put a ✅ on this post".format(led[1]))
    return UNKNOWN, ("nothing can confirm this report delivered — its `verify` "
                     "is not wired and it wrote no manifest today")


def may_close(report_id: str, day: Optional[dt.date] = None, *,
              delivered: Optional[bool] = None) -> Tuple[bool, str, str]:
    """(may this run close its ticket?, verdict, why). The one call sites use."""
    v, why = verdict(report_id, day, delivered=delivered)
    return v == DELIVERED, v, why


# ------------------------------------------------------------------------ CLI --

def main(argv=None) -> int:
    """Print the verdict for one report, or for every report in the schedule.

    THE SAMPLE (Megan 2026-09-09): "validate against a real sample of today's
    reports before you rely on it — I don't want the channel to flip into a wall
    of false-red the same way it had false-green." `--all` is that check, and it
    names every report that would now be held back so the list can be worked
    down rather than discovered in the channel."""
    import argparse
    ap = argparse.ArgumentParser(
        description="Did a report DELIVER, or did it merely run?")
    ap.add_argument("report_id", nargs="?", help="one report id")
    ap.add_argument("--all", action="store_true",
                    help="every report in schedule_config")
    ap.add_argument("--scheduled-only", action="store_true",
                    help="with --all: skip off-scheduler handles and probes")
    ap.add_argument("--date", help="YYYY-MM-DD (default: today)")
    a = ap.parse_args(argv)
    day = dt.date.fromisoformat(a.date) if a.date else dt.date.today()

    if a.report_id and not a.all:
        v, why = verdict(a.report_id, day)
        print("{:<12} {}  — {}".format(v.upper(), a.report_id, why))
        return 0 if v == DELIVERED else 1

    rows = []
    for rid, rec in sorted(_reports().items()):
        if a.scheduled_only and not rec.get("on_scheduler"):
            continue
        v, why = verdict(rid, day)
        rows.append((v, rid, why))
    for v in (NOT_DELIVERED, UNKNOWN, DELIVERED):
        got = [r for r in rows if r[0] == v]
        print("\n=== {} ({}) ===".format(v.upper(), len(got)))
        for _v, rid, why in got:
            print("  {:<42} {}".format(rid[:42], why[:88]))
    print("\n{} report(s): {} delivered · {} not delivered · {} unknown".format(
        len(rows),
        sum(1 for r in rows if r[0] == DELIVERED),
        sum(1 for r in rows if r[0] == NOT_DELIVERED),
        sum(1 for r in rows if r[0] == UNKNOWN)))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
