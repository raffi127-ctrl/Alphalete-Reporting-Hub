"""Second rounds -> each new owner's reception Google Contacts, + the audit.

    python -m automations.second_round_contacts.run                 # dry: plan the adds
    python -m automations.second_round_contacts.run --write         # create the contacts
    python -m automations.second_round_contacts.run --audit         # dry: what the audit would do
    python -m automations.second_round_contacts.run --audit --write # remove / graduate
    options: --owner "Name" (one roster row), --date YYYY-MM-DD (one day),
             --no-ownerville (audit without the badging check)

DRY RUN IS THE DEFAULT. The Lucy 1 cards pass --write (12:00 and 15:30 for the
adds -- owners update ApplicantStream late, Carlos 2026-10-31 -- and 06:00 for
the audit). Every pass re-reads this week (Sunday on, Saturday too on Sunday),
so a late-marked second round goes in on the next pass; "already there" = the
same phone or email anywhere in that account, so nothing is ever doubled.

Exit codes: 0 clean · 1 something failed (Hub card red) · 2 bad arguments.
Python 3.9-safe (Lucy 1).
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import sys
from typing import Dict, List, Optional, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from automations.second_round_contacts import config as C
from automations.second_round_contacts import contacts as K
from automations.second_round_contacts import roster as R
from automations.second_round_contacts import rules
from automations.second_round_contacts import state as S


def _log(msg: str) -> None:
    print(msg, flush=True)


# ------------------------------------------------------------ AppStream --

def read_lists(app, office: str, labels, days: List[dt.date]) -> List[Tuple[str, dt.date, dict]]:
    """[(label, day, applicant)] off ONE Retention Details load for `office`."""
    from automations.linkedin_2nd_round_contacts.run import (_READ_TABLE, _count,
                                                              date_header, to_applicants)
    owner = app.select_office(office)
    _log("  [%s] %s" % (office, owner))
    app.open_retention_details()
    hrefs = [(label, d, app.detail_href(label, date_header(d))) for label in labels for d in days]
    out: List[Tuple[str, dt.date, dict]] = []
    for label, d, href in hrefs:
        if not _count(href):
            continue
        app._goto_detail(href)
        t = app.page.evaluate(_READ_TABLE)
        people = to_applicants(t["header"], t["rows"])
        _log("    %s %s: %d" % (label, date_header(d), len(people)))
        out.extend((label, d, p) for p in people)
    return out


def read_offices(app, offices: List[str], labels, days: List[dt.date]):
    """(found, errors) across an owner's offices. For the ADDS only: one office
    this login cannot open must not stop the numbers from the other one."""
    from automations.applicant_tracker.applicantstream import OfficeNotAvailable
    found: List[Tuple[str, dt.date, dict]] = []
    errors: List[str] = []
    for office in offices:
        try:
            found.extend(read_lists(app, office, labels, days))
        except OfficeNotAvailable as e:
            _log("  ApplicantStream office %s not available (%s)" % (office, e))
            errors.append("office %s not available" % office)
        except Exception as e:  # noqa: BLE001 -- one office never sinks the other
            _log("  ApplicantStream office %s read failed (%s: %s)" % (office, type(e).__name__, str(e)[:160]))
            errors.append("office %s %s" % (office, type(e).__name__))
    return found, errors


def plan_adds(found: List[Tuple[str, dt.date, dict]], phones: Dict[str, str],
              emails: Dict[str, str]) -> List[dict]:
    """plan() rows with the EARLIEST day a person appeared attached."""
    from automations.applicant_contacts import contacts as AC
    found = sorted(found, key=lambda x: x[1])
    first_day: Dict[str, dt.date] = {}
    applicants = []
    for _label, d, a in found:
        k = S.key_for(a)
        if k in first_day:
            continue
        first_day[k] = d
        applicants.append(a)
    rows = AC.plan(applicants, phones, emails)
    for r in rows:
        r["day"] = first_day.get(S.key_for(r["applicant"]))
    return rows


# ----------------------------------------------------------------- pass --

def run_pass(owners: List[R.Owner], days: List[dt.date], *, write: bool,
             ws=None) -> int:
    from automations.applicant_tracker.applicantstream import session
    st = S.load()
    failed = 0
    with session() as app:
        for o in owners:
            if not K.has_token(o.account):
                msg = "no Contacts token for %s (%s) -- authorize it once on this machine" % (o.account, K.token_file(o.account))
                _log("  %s: %s" % (o.owner, msg))
                if ws is not None and write:
                    R.stamp(ws, o, "SKIPPED: " + msg)
                continue
            found, errors = read_offices(app, o.offices, C.ADD_LABELS, days)
            failed += len(errors)
            if len(errors) == len(o.offices):      # nothing was read at all
                if ws is not None and write:
                    R.stamp(ws, o, "FAILED: " + "; ".join(errors))
                continue
            try:
                svc = K.service(o.account)
                phones, emails = K.existing_index(svc)
                group = K.ensure_group(svc, C.GROUP) if write else None
            except Exception as e:  # noqa: BLE001
                _log("  %s: Google Contacts (%s) failed: %s: %s" % (o.owner, o.account, type(e).__name__, str(e)[:160]))
                failed += 1
                if ws is not None and write:
                    R.stamp(ws, o, "FAILED: contacts %s" % type(e).__name__)
                continue
            rows = plan_adds(found, phones, emails)
            added = exists = skipped = 0
            acct = st.setdefault(o.account, {})
            for r in rows:
                a = r["applicant"]
                name = " ".join(x for x in (a.get("first_name"), a.get("last_name")) if x)
                if r["status"] == "exists":
                    exists += 1
                    continue
                if r["status"] == "skip":
                    skipped += 1
                    _log("    skip %s: %s" % (name, r["why"]))
                    continue
                day = r["day"] or dt.date.today()
                display = K.display_name(a, day)
                if not write:
                    _log("    would add %s  (%s / %s)" % (display, a.get("phone", ""), a.get("email", "")))
                    added += 1
                    continue
                try:
                    rn = K.create(svc, group, a, display=display, note=K.note_for(o.owner, o.office, day))
                except Exception as e:  # noqa: BLE001
                    _log("    FAILED %s: %s" % (display, str(e)[:160]))
                    failed += 1
                    continue
                acct[S.key_for(a)] = S.entry(a, resource_name=rn, owner=o.owner, office=o.office,
                                             second_round=day, display=display)
                S.save(st)
                added += 1
                _log("    + %s" % display)
            res = "%d added, %d already there, %d skipped (%d second-round rows read)%s%s" % (
                added, exists, skipped, len(found), "" if write else " [DRY RUN]",
                "".join(" -- FAILED: %s" % e for e in errors))
            _log("  %s: %s" % (o.owner, res))
            if ws is not None and write:
                R.stamp(ws, o, res)
    return failed


# ---------------------------------------------------------------- audit --

def audit_offices(owner: R.Owner, entries: Dict[str, dict]) -> List[str]:
    """The roster's offices plus any office a tracked contact was added from.
    Taking an old funnel off the roster must not make its people look not hired."""
    out = list(owner.offices)
    for e in entries.values():
        office = e.get("office")
        if office and e.get("status") == S.TRACKED and office not in out:
            out.append(office)
    return out


def gather_facts(app, offices: List[str], keys: set, today: dt.date) -> Dict[str, dict]:
    """{key: {offered, bob, ns_sched, ns_showed}} for the tracked people, across
    every office. A read that fails RAISES: the audit then skips this owner,
    because a person whose office went unread would look not hired and get
    deleted."""
    days = [today - dt.timedelta(days=i) for i in range(C.AUDIT_LOOKBACK_DAYS, -1, -1)]
    found: List[Tuple[str, dt.date, dict]] = []
    for office in offices:
        found.extend(read_lists(app, office, C.AUDIT_LABELS, days))
    facts: Dict[str, dict] = {k: {} for k in keys}
    slot = {C.LABEL_OFFERED: "offered", C.LABEL_BOB: "bob", C.LABEL_NS_SCHED: "ns_sched",
            C.LABEL_NS_SHOWED: "ns_showed", C.LABEL_SHOWED: "showed"}
    for label, d, a in found:
        k = S.key_for(a)
        if k not in facts:
            continue
        f = slot.get(label)
        if f and (facts[k].get(f) is None or d < facts[k][f]):
            facts[k][f] = d
    return facts


def run_audit(owners: List[R.Owner], *, write: bool, ownerville: bool = True,
              ws=None, today: Optional[dt.date] = None) -> int:
    from automations.applicant_tracker.applicantstream import session
    today = today or dt.date.today()
    st = S.load()
    by_account = {o.account: o for o in owners}
    failed = 0
    # 1. ApplicantStream facts, one session for every office
    facts_all: Dict[str, Dict[str, dict]] = {}
    with session() as app:
        for account, entries in st.items():
            o = by_account.get(account)
            if not o:
                continue
            keys = {k for k, e in entries.items() if e.get("status") == S.TRACKED}
            if not keys:
                continue
            try:
                facts_all[account] = gather_facts(app, audit_offices(o, entries), keys, today)
            except Exception as e:  # noqa: BLE001
                _log("  %s: ApplicantStream read failed (%s) -- audit skipped for this owner" % (o.owner, type(e).__name__))
                failed += 1
    # 2. OwnerVille progress, only for the people who showed up to a start
    progress: Dict[str, Optional[int]] = {}
    want: Dict[str, list] = collections.defaultdict(list)
    for account, facts in facts_all.items():
        o = by_account[account]
        for k, f in facts.items():
            if f.get("ns_showed"):
                e = st[account][k]
                want[o.ov_campaign].append(" ".join(x for x in (e.get("first_name"), e.get("last_name")) if x))
    if want and ownerville:
        from automations.second_round_contacts import ownerville as OV
        try:
            progress = OV.progress_many(dict(want), log=_log)
        except Exception as e:  # noqa: BLE001
            _log("  OwnerVille unavailable (%s) -- badging rule waits" % type(e).__name__)
    # 3. decide + apply
    for account, facts in facts_all.items():
        o = by_account[account]
        svc = K.service(o.account) if write else None
        deleted = hired = waiting = 0
        for k, f in facts.items():
            e = st[account][k]
            name = " ".join(x for x in (e.get("first_name"), e.get("last_name")) if x)
            f = dict(f, progress=progress.get(name))
            verdict, why = rules.decide(e, f, today)
            if verdict == rules.DELETE:
                deleted += 1
                _log("    %s %s: %s" % ("remove" if write else "would remove", e.get("display", name), why))
                if write:
                    try:
                        if K.still_exists(svc, e["resourceName"]):
                            K.delete(svc, e["resourceName"])
                        e["status"] = S.REMOVED
                        e["removed"] = today.isoformat()
                        e["reason"] = why
                    except Exception as ex:  # noqa: BLE001
                        _log("    FAILED removing %s: %s" % (name, str(ex)[:160]))
                        failed += 1
            elif verdict == rules.HIRED:
                hired += 1
                _log("    %s: %s" % (e.get("display", name), why))
                if write:
                    e["status"] = S.HIRED
                    e["hired"] = today.isoformat()
            else:
                waiting += 1
        if write:
            S.save(st)
        res = "audit: %d removed, %d graduated (hired+badged), %d waiting%s" % (
            deleted, hired, waiting, "" if write else " [DRY RUN]")
        _log("  %s: %s" % (o.owner, res))
        if ws is not None and write:
            R.stamp(ws, o, res)
    return failed


# ----------------------------------------------------------------- main --

def main(argv=None) -> int:
    from automations.linkedin_2nd_round_contacts.run import days_to_read
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true", help="create / remove contacts (default: dry run)")
    ap.add_argument("--audit", action="store_true", help="run Raf's removal rules instead of the adds")
    ap.add_argument("--owner", default=None, help="only this roster row (name as on the tab)")
    ap.add_argument("--date", default=None, help="adds: read only this day (YYYY-MM-DD)")
    ap.add_argument("--no-ownerville", action="store_true", help="audit without the View Progress check")
    args = ap.parse_args(argv)
    C.OUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        ws = R.open_tab()
        owners = R.read(ws)
    except Exception as e:  # noqa: BLE001
        print("roster tab unreadable: %s: %s" % (type(e).__name__, str(e)[:200]), file=sys.stderr)
        return 1
    if args.owner:
        owners = [o for o in owners if o.owner.lower() == args.owner.strip().lower()]
        if not owners:
            print("no roster row named %r" % args.owner, file=sys.stderr)
            return 2
    active = [o for o in owners if o.active]
    _log("=== 2nd rounds -> reception contacts%s: %d active owner(s) on '%s' ===" % (
        " [AUDIT]" if args.audit else "", len(active), C.ROSTER_TAB))
    for o in owners:
        _log("  %s%s%s" % (o.label, "" if o.active else "  (inactive)",
                            "" if K.has_token(o.account) else "  (no token yet)"))
    if not active:
        _log("nothing to do")
        return 0
    if args.audit:
        failed = run_audit(active, write=args.write, ownerville=not args.no_ownerville, ws=ws)
    else:
        try:
            days = [dt.date.fromisoformat(args.date)] if args.date else days_to_read(dt.date.today())
        except ValueError:
            print("bad --date, use YYYY-MM-DD", file=sys.stderr)
            return 2
        failed = run_pass(active, days, write=args.write, ws=ws)
    if not args.write:
        _log("DRY RUN -- re-run with --write to apply")
    print("=== done ===", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
