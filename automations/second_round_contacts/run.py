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
    # `days` may be ONE list for every label, or {label: days} when a label
    # needs its own window -- the BOB mark is filed under the START date, so it
    # is the one metric that has to be read into the future.
    per_label = days if isinstance(days, dict) else {lab: days for lab in labels}
    hrefs = [(label, d, app.detail_href(label, date_header(d)))
             for label in labels for d in per_label.get(label, [])]
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
            added = exists = skipped = removed = 0
            # THE MEMORY, FROM THE ACCOUNT IF THIS MACHINE HAS NONE. The
            # state file is local, so a box that has never run this job
            # starts blank -- and blank means the REMOVED check below sees
            # nobody, so everyone the audit has ever taken out goes straight
            # back on the owner's phone. The cards carry their own note, so
            # the slice is read back off the account rather than off whoever
            # happened to run it last (2026-11-22, moving this step onto the
            # office's own machine).
            if o.account not in st:
                try:
                    got = S.rebuild(svc)
                except Exception as e:                      # noqa: BLE001
                    # Better to add a duplicate than to drop the pass: say so
                    # loudly, because this is the one path that can double a
                    # contact list.
                    _log("  %s: could not read this account's own cards (%s) "
                         "-- running with no memory, duplicates possible"
                         % (o.owner, type(e).__name__))
                else:
                    if got:
                        _log("  %s: no local record -- rebuilt %d card(s) off "
                             "the account itself" % (o.owner, len(got)))
                        st[o.account] = got
                        S.save(st)
            acct = st.setdefault(o.account, {})
            for r in rows:
                a = r["applicant"]
                name = " ".join(x for x in (a.get("first_name"), a.get("last_name")) if x)
                # A REMOVAL STAYS A REMOVAL. plan() only dedupes against the
                # live contacts, so the moment the audit takes somebody out
                # they look brand new to this pass and the next run puts them
                # straight back -- out at 7pm, in at 6am, every day until the
                # week rolls past. The state is the memory of that decision.
                # Only the audit puts one back, when the missing mark shows up
                # (rules.restore).
                prior = acct.get(S.key_for(a))
                if prior and prior.get("status") == S.REMOVED:
                    removed += 1
                    _log("    skip %s: taken out %s (%s)" % (
                        name, prior.get("removed", "?"), prior.get("reason", "")))
                    continue
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
            res = "%d added, %d already there, %d skipped, %d left out (%d second-round rows read)%s%s" % (
                added, exists, skipped, removed, len(found), "" if write else " [DRY RUN]",
                "".join(" -- FAILED: %s" % e for e in errors))
            _log("  %s: %s" % (o.owner, res))
            if ws is not None and write:
                R.stamp(ws, o, res)
    return failed


# ---------------------------------------------------------------- audit --

def from_old_office(owner: R.Owner, entries: Dict[str, dict]) -> set:
    """Tracked contacts added from an office that is no longer on the owner's
    row. Their office is gone (Omar's 24153, closed 2026-11-04), so the audit
    cannot see what happened to them: they are KEPT for good, never removed on
    missing data (Eve 2026-11-05)."""
    return {k for k, e in entries.items()
            if e.get("status") == S.TRACKED and e.get("office")
            and e.get("office") not in owner.offices}


def gather_facts(app, offices: List[str], keys: set, today: dt.date) -> Dict[str, dict]:
    """{key: {offered, bob, ns_sched, ns_showed}} for the tracked people, across
    every office. A read that fails RAISES: the audit then skips this owner,
    because a person whose office went unread would look not hired and get
    deleted."""
    back = [today - dt.timedelta(days=i) for i in range(C.AUDIT_LOOKBACK_DAYS, -1, -1)]
    # The BOB mark alone is read forward too: it is filed under the day they
    # are due to START, which has not happened yet.
    days = {label: back for label in C.AUDIT_LABELS}
    days[C.LABEL_BOB] = back + [today + dt.timedelta(days=i)
                                for i in range(1, C.BOB_FORWARD_DAYS + 1)]
    found: List[Tuple[str, dt.date, dict]] = []
    for office in offices:
        found.extend(read_lists(app, office, C.AUDIT_LABELS, days))
    facts: Dict[str, dict] = {k: {} for k in keys}
    slot = {C.LABEL_OFFERED: "offered", C.LABEL_BOB: "bob", C.LABEL_NS_SCHED: "ns_sched",
            C.LABEL_NS_SHOWED: "ns_showed", C.LABEL_SHOWED: "showed"}
    # Which labels came back with ANYBODY on them, across every office and day
    # of this read -- whether or not the person is one we track. An empty
    # keeper list is the difference between "nobody was BOB'd" and "we did not
    # manage to read who was", and those must never look the same: the second
    # one would take every contact out at once.
    seen = {label for label, _d, _a in found}
    for label, d, a in found:
        k = S.key_for(a)
        if k not in facts:
            continue
        f = slot.get(label)
        if f and (facts[k].get(f) is None or d < facts[k][f]):
            facts[k][f] = d
    return facts, seen


def run_audit(owners: List[R.Owner], *, write: bool, ownerville: bool = True,
              evening: bool = False,
              ws=None, today: Optional[dt.date] = None) -> int:
    from automations.applicant_tracker.applicantstream import session
    today = today or dt.date.today()
    st = S.load()
    by_account = {o.account: o for o in owners}
    # THE AUDIT ONLY SEES WHAT THE STATE HOLDS, so on a machine that has
    # never run this job it sees nothing and audits nobody -- every card
    # already on the owner's phone would sit there for ever. The cards carry
    # their own note, so an account with no slice is read back off the
    # account before the loop below, not instead of it (2026-11-22, moving
    # this step onto the office's own machine).
    filled = False
    for o in owners:
        if o.account in st or not K.has_token(o.account):
            continue
        try:
            got = S.rebuild(K.service(o.account))
        except Exception as e:                              # noqa: BLE001
            _log("  %s: could not read this account's own cards (%s) -- "
                 "nothing of theirs is audited this pass"
                 % (o.owner, type(e).__name__))
            continue
        if got:
            _log("  %s: no local record -- rebuilt %d card(s) off the "
                 "account itself" % (o.owner, len(got)))
            st[o.account] = got
            filled = True
    if filled and write:
        S.save(st)
    failed = 0
    # 1. ApplicantStream facts, one session for every office
    facts_all: Dict[str, Dict[str, dict]] = {}
    seen_all: Dict[str, set] = {}
    with session() as app:
        for account, entries in list(st.items()):
            o = by_account.get(account)
            if not o:
                continue
            old = from_old_office(o, entries)
            for k in sorted(old):
                e = entries[k]
                _log("    %s %s: added from office %s, no longer on the row -- kept for good" % (
                    "keep" if write else "would keep", e.get("display", k), e.get("office")))
                if write:
                    e["status"] = S.KEPT
                    e["kept"] = today.isoformat()
                    e["reason"] = "office %s left the roster row" % e.get("office")
            if old and write:
                S.save(st)
            keys = {k for k, e in entries.items() if e.get("status") == S.TRACKED} - old
            # The way back. Somebody taken out is no longer TRACKED, so
            # without this their late mark is never read and they can never
            # come back (Megan 2026-11-17 for the 7pm rule; Eve 2026-11-19 for
            # every rule).
            keys |= {k for k, e in entries.items()
                     if rules.restorable(e, today)} - old
            if not keys:
                continue
            try:
                facts_all[account], seen_all[account] = gather_facts(
                    app, o.offices, keys, today)
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
        group = K.ensure_group(svc, C.GROUP) if write else None
        # THE KEEPER HAS TO HAVE BEEN READ. The evening rule removes everybody
        # who is not marked BOB, so a read that returned no BOB rows at all
        # does not mean "nobody was brought on board" -- it means we could not
        # tell, and acting on it would empty the whole group in one pass. A
        # blank is only an answer when the data proves it is one.
        keeper_read = C.EVENING_KEEPER in seen_all.get(account, set())
        if evening and not keeper_read:
            _log("  %s: NOT REMOVING ANYONE -- '%s' came back empty for every "
                 "office and day read, so a missing mark cannot be told apart "
                 "from a missing read" % (o.owner, C.EVENING_KEEPER))
            failed += 1
        deleted = hired = waiting = restored = 0
        for k, f in facts.items():
            e = st[account][k]
            name = " ".join(x for x in (e.get("first_name"), e.get("last_name")) if x)
            f = dict(f, progress=progress.get(name))
            # ALREADY OUT. Back in only if the mark its removal was missing
            # has since shown up -- rules.restore says which mark, per rule.
            if e.get("status") == S.REMOVED:
                back, why = rules.restore(e, f, today)
                if not back:
                    continue
                restored += 1
                _log("    %s %s: %s" % (
                    "put back" if write else "would put back",
                    e.get("display", name), why))
                if write:
                    try:
                        rn = K.create(svc, group, e,
                                      display=e.get("display") or name,
                                      note=K.note_for(e.get("owner", o.owner),
                                                      e.get("office", ""),
                                                      dt.date.fromisoformat(e["second_round"])))
                        # A new card means a NEW resourceName; keeping the old
                        # one would point every later rule at a contact that
                        # no longer exists.
                        e["resourceName"] = rn
                        e["status"] = S.TRACKED
                        e["restored"] = today.isoformat()
                        e["reason"] = why
                        e.pop("removed", None)
                        e.pop("removed_by", None)
                        e.pop("removed_rule", None)
                    except Exception as ex:  # noqa: BLE001
                        _log("    FAILED putting %s back: %s" % (name, str(ex)[:160]))
                        failed += 1
                continue
            verdict, why = rules.decide(e, f, today,
                                        evening=evening and keeper_read)
            if verdict == rules.DELETE:
                deleted += 1
                _log("    %s %s: %s" % ("remove" if write else "would remove", e.get("display", name), why))
                if write:
                    try:
                        # A 404 ON THE STORED ID IS NOT PROOF THEY ARE OFF
                        # THE PHONE. A card re-created since carries a new
                        # resourceName, and the old one is all the file has
                        # -- so "gone" gets written while the live card
                        # stays, and nothing looks at them again. Ask the
                        # account by the key everything else dedupes on
                        # before concluding anything (2026-11-22).
                        rn = e["resourceName"]
                        if K.still_exists(svc, rn):
                            K.delete(svc, rn)
                        else:
                            again = K.find_ours(svc, k)
                            if again:
                                _log("      (its card came back under a new "
                                     "id — removing that one)")
                                K.delete(svc, again)
                                e["resourceName"] = again
                        e["status"] = S.REMOVED
                        e["removed"] = today.isoformat()
                        e["reason"] = why
                        # Which rule did it, so the 7pm pass knows what it may
                        # undo. Only ever the evening one.
                        ev = evening and keeper_read and rules.evening_removal(e, f, today)
                        if ev:
                            e["removed_by"] = rules.EVENING
                        else:
                            e.pop("removed_by", None)
                        rule = rules.removal_rule(why, ev or None)
                        if rule:
                            e["removed_rule"] = rule
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
        res = "audit: %d removed, %d put back, %d graduated (hired+badged), %d waiting%s" % (
            deleted, restored, hired, waiting, "" if write else " [DRY RUN]")
        _log("  %s: %s" % (o.owner, res))
        if ws is not None and write:
            R.stamp(ws, o, res)
    return failed


def check_rebuild(owners: List[R.Owner]) -> int:
    """READ-ONLY: does the account's own cards say what the file says?

    The whole case for moving this job onto the office's own computer is
    that the memory can be read back off the account, so a machine without
    the file is not a machine without the memory. That is a CLAIM until it
    is run where both exist -- Lucy 1, which has the file and the tokens --
    and the only answer that settles it is a diff.

    Writes nothing: no contact, no file, no sheet. It reads Contacts and
    prints.
    """
    st = S.load()
    worst = 0
    for o in owners:
        if not K.has_token(o.account):
            _log("  %s: no Contacts token on this machine -- cannot check"
                 % o.owner)
            continue
        have = st.get(o.account) or {}
        try:
            got = S.rebuild(K.service(o.account))
        except Exception as e:                              # noqa: BLE001
            _log("  %s: Contacts read failed: %s: %s"
                 % (o.owner, type(e).__name__, str(e)[:160]))
            worst = max(worst, 1)
            continue
        # WHAT SHOULD BE ON THE ACCOUNT, by status. Comparing against
        # TRACKED alone called every KEPT card "extra", and a KEPT card is
        # one we deliberately leave on the owner's phone -- somebody who
        # left, who Raf may rehire months down the road. Fifteen lines of
        # correct behaviour reported as findings is how a check stops being
        # read.
        live = {k for k, e in have.items() if e.get("status") == S.TRACKED}
        kept = {k for k, e in have.items() if e.get("status") == S.KEPT}
        gone = {k for k, e in have.items()
                if e.get("status") in (S.REMOVED, S.HIRED)}
        found = set(got)
        missed = sorted((live | kept) - found)
        extra = sorted(found - live - kept - gone)
        undead = sorted(found & gone)
        _log("  %s (%s): file has %d tracked + %d kept, the account gives "
             "back %d" % (o.owner, o.account, len(live), len(kept), len(found)))
        for k in missed:
            e = have[k]
            _log("    NOT REBUILT  %s (%s) — on file, not readable off the "
                 "card" % (e.get("display", k), e.get("status", "?")))
        for k in extra:
            _log("    EXTRA        %s — on the account, nothing on file"
                 % got[k].get("display", k))
        for k in undead:
            e = have[k]
            # Not a rebuild fault: the file says this card was deleted and
            # it is still there, which is a removal that did not happen.
            _log("    STILL THERE  %s — file says %s on %s, card is still "
                 "on the account"
                 % (got[k].get("display", k), e.get("status"),
                    e.get("removed") or e.get("hired") or "?"))
        for k in sorted(live & found):
            was, now = have[k], got[k]
            for field in ("second_round", "office", "owner"):
                if str(was.get(field, "")) != str(now.get(field, "")):
                    _log("    DISAGREES    %s %s: file %r, card %r"
                         % (was.get("display", k), field,
                            was.get(field), now.get(field)))
                    worst = max(worst, 1)
        # EXTRA and STILL THERE are worth reading and are not rebuild
        # failures: one is a card nobody recorded, the other a removal that
        # did not happen. Only a card the file has and the rebuild cannot
        # give back says the memory does not survive the move.
        if missed:
            worst = max(worst, 1)
    return worst


def unstick_removals(owners: List[R.Owner], *, write: bool) -> int:
    """People the file calls removed whose card is still on the account.

    THE ONES ALREADY STUCK. `still_exists` used to answer False for every
    error, not just a 404, so a rate-limited pass marked people REMOVED
    without deleting anything -- 22 of them on Raf's account on
    2026-11-22, every one a second round between 11/9 and 11/12, which is
    what one bad pass on the biggest account looks like. The fix stops new
    ones; it cannot clear these, because nothing looks at a removed person
    again.

    IT PUTS THEM BACK TO TRACKED RATHER THAN DELETING THEM. The audit's
    rules decide who comes off a phone, and they have had a fortnight of
    new facts since: somebody here may have been rehired, or shown up
    late. Deleting them from here would be this function overruling the
    rules on 22 real people. Tracked is the state they were in before the
    bad pass, so the next audit simply decides them again -- and now the
    delete either happens or says it failed.
    """
    st = S.load()
    found = 0
    for o in owners:
        if not K.has_token(o.account):
            _log("  %s: no Contacts token on this machine -- cannot check"
                 % o.owner)
            continue
        entries = st.get(o.account) or {}
        gone = {k: e for k, e in entries.items()
                if e.get("status") == S.REMOVED}
        if not gone:
            continue
        try:
            on_account = set(S.rebuild(K.service(o.account)))
        except Exception as e:                              # noqa: BLE001
            _log("  %s: Contacts read failed (%s) -- skipped"
                 % (o.owner, type(e).__name__))
            continue
        stuck = sorted(set(gone) & on_account)
        _log("  %s: %d marked removed, %d of them still on the account"
             % (o.owner, len(gone), len(stuck)))
        for k in stuck:
            e = entries[k]
            _log("    %s %s — removed %s (%s)"
                 % ("putting back" if write else "would put back",
                    e.get("display", k), e.get("removed", "?"),
                    e.get("reason", "")))
            if write:
                e["status"] = S.TRACKED
                for f in ("removed", "removed_by", "removed_rule", "reason"):
                    e.pop(f, None)
                e["unstuck"] = dt.date.today().isoformat()
        found += len(stuck)
        if stuck and write:
            S.save(st)
    if not write:
        _log("  [DRY RUN] nothing changed. --write puts them back to tracked, "
             "and the next audit decides them again.")
    return 0 if found == 0 else 0


def why_removed(owners: List[R.Owner]) -> int:
    """READ-ONLY: which rule took each account's people off the phone.

    Reads the local state file and nothing else -- no Contacts, no
    ApplicantStream. Asked because a count on its own cannot be judged:
    Cyrus's account showed 91 removed against 20 still tracked on
    2026-11-22, where Raf's was 177 against 143 and Hasan's 13 against 24.
    A ratio that far out is either a lot of second rounds that went nowhere
    or a rule firing on missing data, and those two want opposite actions.

    "not hired / left as a message" is the one to watch: it fires seven days
    after a second round when ApplicantStream shows no BOB, no offer and no
    scheduled start. An office that does not mark its outcomes looks exactly
    like an office whose candidates all said no.
    """
    import collections
    st = S.load()
    for o in owners:
        entries = st.get(o.account) or {}
        if not entries:
            _log("  %s: nothing on file on this machine" % o.owner)
            continue
        by_status = collections.Counter(e.get("status", "?")
                                        for e in entries.values())
        why = collections.Counter()
        when = collections.Counter()
        for e in entries.values():
            if e.get("status") != S.REMOVED:
                continue
            r = str(e.get("reason", "") or "?").split(":")[0].strip()
            why[r or "?"] += 1
            when[str(e.get("removed", "?"))[:10]] += 1
        _log("  %s (%s): %s" % (o.owner, o.account,
                                ", ".join("%s %d" % (k, v)
                                          for k, v in sorted(by_status.items()))))
        for r, n in why.most_common():
            _log("      %-56s %d" % (r, n))
        busiest = when.most_common(3)
        if busiest:
            _log("      busiest removal days: %s"
                 % ", ".join("%s (%d)" % (d, n) for d, n in busiest))
    return 0


# ----------------------------------------------------------------- main --

def main(argv=None) -> int:
    from automations.linkedin_2nd_round_contacts.run import days_to_read
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true", help="create / remove contacts (default: dry run)")
    ap.add_argument("--audit", action="store_true", help="run Raf's removal rules instead of the adds")
    ap.add_argument("--evening", action="store_true",
                    help="the end-of-day pass: also drop today's second rounds "
                         "that were marked neither showed up nor offered. "
                         "Never pass this before the day is over -- earlier, a "
                         "blank only means nobody has marked it yet.")
    ap.add_argument("--owner", default=None, help="only this roster row (name as on the tab)")
    ap.add_argument("--date", default=None, help="adds: read only this day (YYYY-MM-DD)")
    ap.add_argument("--no-ownerville", action="store_true", help="audit without the View Progress check")
    ap.add_argument("--why-removed", action="store_true",
                    help="READ-ONLY: which rule removed each account's "
                         "people, and on which days. Reads the local state "
                         "file only -- no Contacts, no ApplicantStream.")
    ap.add_argument("--unstick-removals", action="store_true",
                    help="people the file calls removed whose card is still "
                         "on the account. Dry by default; --write puts them "
                         "back to tracked so the next audit decides them "
                         "again. It never deletes a contact itself.")
    ap.add_argument("--check-rebuild", action="store_true",
                    help="READ-ONLY: diff each account's own cards against "
                         "the local state file, and print. Writes nothing. "
                         "Run it where the file is (Lucy 1) to prove a "
                         "machine without the file can still know what was "
                         "created.")
    args = ap.parse_args(argv)
    # The evening rule is a REMOVAL rule, and removals only happen on the audit
    # side. Passing --evening on an adds run used to be silently ignored, which
    # reads as "the 7pm cleanup ran and found nothing" -- so it implies --audit
    # instead of doing nothing.
    if args.evening and not args.audit:
        args.audit = True
        _log("--evening implies --audit (removals only happen on the audit pass)")
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
    if args.why_removed:
        try:
            from automations.shared import hub_autopublish as HA
            HA.nothing_to_report()
        except Exception:                                   # noqa: BLE001
            pass
        _log("=== why people were removed (READ-ONLY)")
        return why_removed(active)
    if args.unstick_removals:
        try:
            from automations.shared import hub_autopublish as HA
            HA.nothing_to_report()
        except Exception:                                   # noqa: BLE001
            pass
        _log("=== stuck removals%s" % ("" if args.write else " (DRY RUN)"))
        return unstick_removals(active, write=args.write)
    if args.check_rebuild:
        # --write IS TURNED OFF HERE, OUT LOUD. The only way to queue this on
        # Lucy 1 is `lucy rerun second_round_contacts --check-rebuild`, and
        # that handle's base_args are ['--write'], so the probe always
        # arrives as `--write --check-rebuild`. It returns before any write
        # either way; saying it rather than relying on the order of two
        # statements is the difference between safe and safe-by-accident on
        # a job that edits real people's phones.
        if args.write:
            args.write = False
            _log("--check-rebuild is read-only: --write ignored")
        # A QUESTION IS NOT A DELIVERY. A read-only probe that marks the card
        # green says the job ran when it did not -- the same class as a dry
        # run turning a card red (hub_autopublish, 2026-11-15).
        try:
            from automations.shared import hub_autopublish as HA
            HA.nothing_to_report()
        except Exception:                                   # noqa: BLE001
            pass
        _log("=== rebuild check (READ-ONLY, writes nothing)")
        return check_rebuild(active)
    _log("=== 2nd rounds -> reception contacts%s: %d active owner(s) on '%s' ===" % (
        " [AUDIT]" if args.audit else "", len(active), C.ROSTER_TAB))
    for o in owners:
        _log("  %s%s%s" % (o.label, "" if o.active else "  (inactive)",
                            "" if K.has_token(o.account) else "  (no token yet)"))
    if not active:
        _log("nothing to do")
        return 0
    if args.audit:
        failed = run_audit(active, write=args.write,
                           ownerville=not args.no_ownerville,
                           evening=args.evening, ws=ws)
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
