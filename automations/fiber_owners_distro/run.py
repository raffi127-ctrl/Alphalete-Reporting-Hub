"""AT&T Fiber Owners distribution-list sync (Kelly's weekly roster → Contacts group).

Every week Kelly Pavone emails the AT&T ICD Owner Roster. This resets the
"AT&T Fiber Owners" Google Contacts group to the current Fiber + Hybrid owners
(Hybrid rolls up under Fiber — Raf 2026-07-26), minus a persistent exclude list
(excludes.json — e.g. Tevin Sterling).

Removals go through a Slack safety net (Megan 2026-07-27): adds apply immediately,
but owners who dropped off the roster are ANNOUNCED to #l10-alphalete with a 24h
objection window before removal — a `Name - not terminated` reply keeps them.

    # preview only (no writes, no Slack):
    python -m automations.fiber_owners_distro.run
    # phase 1 — apply adds + stale-dup cleanup, announce departures (add --send to go live):
    python -m automations.fiber_owners_distro.run --phase post --send
    # phase 2 (+24h) — remove the un-vouched departures:
    python -m automations.fiber_owners_distro.run --phase finalize --send

Person-centric throughout (Google Contacts groups are per-person, not per-email) and
Gmail dot/+tag-insensitive. Protects every address on ANY roster tab from removal, so
a current Wireless/B2B owner already on the list is never dropped. Writing needs a
read-write Contacts token (contacts_write.authorize); raffi127 is authorized.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from automations.fiber_owners_distro import roster

OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "fiber_owners_distro"
EXCLUDES_PATH = Path(__file__).resolve().parent / "excludes.json"
KEEP_PATH = Path(__file__).resolve().parent / "keep_in_group.json"

# Defaults for Raf's personal list. The group is 'ATT Fiber Owners' (no ampersand —
# that's how it's named in raffi127's contacts). The Alphalete Reporting target is
# deliberately NOT defaulted — its population differs from the roster (pending Raf).
DEFAULT_ACCOUNT = "raffi127@gmail.com"
DEFAULT_GROUP = "ATT Fiber Owners"


def _load_json_map(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k.strip().lower(): v for k, v in data.items() if not k.startswith("_")}


def load_excludes() -> Dict[str, str]:
    return _load_json_map(EXCLUDES_PATH)


def load_keep() -> Dict[str, str]:
    return _load_json_map(KEEP_PATH)


def build_target(xlsx_path: Path) -> Tuple[List[roster.Owner], List[roster.Owner], Dict[str, str]]:
    """Return (kept_owners, excluded_owners, excludes_map)."""
    excludes = load_excludes()
    owners = roster.fiber_owners(xlsx_path)
    owners.sort(key=lambda o: (o.name or o.email).lower())
    kept = [o for o in owners if o.email not in excludes]
    dropped = [o for o in owners if o.email in excludes]
    return kept, dropped, excludes


def _current_group_emails(account: str, group: str) -> Optional[List[str]]:
    """Live membership of `group` in `account`, or None if we can't read it yet.

    Prefer the read-WRITE token (works for any account that's been authorized);
    fall back to the shared read-only token (alphaletereporting only). Returns None
    (not an error) when no token is available for the account.
    """
    # 1) read-write token (contacts_write) — any authorized account
    try:
        from automations.fiber_owners_distro import contacts_write
        if contacts_write.token_path(account).exists():
            svc = contacts_write._service(account)
            grp = contacts_write.find_group(svc, group)
            if grp is None:
                return []                   # group doesn't exist yet → everything is an add
            return sorted(contacts_write.group_member_emails(svc, grp))
    except Exception:
        pass
    # 2) shared read-only token (alphaletereporting only)
    try:
        from automations.shared import contacts_auth
        if account == contacts_auth.CONTACTS_ACCOUNT:
            emails, missing = contacts_auth.expand_groups([group])
            if not missing:
                return [e.strip().lower() for e in emails]
    except Exception:
        pass
    return None


def preview(xlsx_path: Path, edate: dt.datetime, account: str, group: str) -> Path:
    kept, dropped, excludes = build_target(xlsx_path)
    target_emails = [o.email for o in kept]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = edate.strftime("%Y-%m-%d")
    csv_path = OUT_DIR / f"target-{account.split('@')[0]}-{stamp}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["email", "owner", "company", "tab", "phone", "headcount"])
        for o in kept:
            w.writerow([o.email, o.name, o.company, o.tab, o.phone, o.headcount])

    print(f"\n=== AT&T Fiber Owners — target for {account} / group {group!r} ===")
    print(f"roster date: {stamp}")
    print(f"Fiber+Hybrid owners on roster: {len(kept) + len(dropped)}")
    print(f"excluded (excludes.json):      {len(dropped)}")
    for o in dropped:
        print(f"    - {o.name} <{o.email}>  — {excludes.get(o.email, '')}")
    print(f"TARGET recipients:             {len(kept)}")
    print(f"preview CSV → {csv_path}")

    # Protect = manual keep list + EVERY address on any roster tab (never drop a
    # still-active owner, incl. Wireless/B2B already on the list).
    protect = list(load_keep().keys()) + roster.all_roster_emails(xlsx_path)

    # Prefer the accurate PERSON-CENTRIC dry-run (needs a write token for the account).
    try:
        from automations.fiber_owners_distro import contacts_write
        if contacts_write.token_path(account).exists():
            rep = contacts_write.sync_group(
                account, group, [(o.email, o.name) for o in kept],
                dry_run=True, protect=protect)
            print(f"\nlive group has {rep['current']} people")
            print(f"  + would ADD    {len(rep['add'])}")
            for e in rep['add']:
                print(f"      + {e}")
            print(f"  = PROTECTED (kept, still a current owner or internal): "
                  f"{len(rep['protected_kept'])}")
            print(f"  - would REMOVE {len(rep['remove'])}  (people with NO roster address)")
            for e in rep['remove']:
                print(f"      - {e}")
            return csv_path
    except Exception as exc:  # noqa: BLE001
        print(f"(person-centric diff unavailable: {type(exc).__name__}: {exc})")

    print("\n(No writable Contacts token for this account/group yet, so no live "
          "diff. Authorize — see contacts_write — to enable the diff + --send.)")
    return csv_path


def _state_path(account: str, group: str) -> Path:
    slug = "".join(c if c.isalnum() else "-" for c in group).strip("-").lower()
    return OUT_DIR / f"pending-{account.split('@')[0]}-{slug}.json"


# Both distros mirror the same national Fiber+Hybrid roster (Eve 2026-07-27):
# Raf's personal list + a matching group in the reporting account. A target only
# becomes active once its account has a read-write Contacts token, so alphalete-
# reporting auto-joins the moment its token is installed — no code change.
ALL_TARGETS = [
    ("raffi127@gmail.com", "ATT Fiber Owners"),
    ("alphaletereporting@gmail.com", "ATT Fiber Owners"),
]
COMBINED_STATE = OUT_DIR / "pending-fiber-owners.json"


def active_targets() -> List[Tuple[str, str]]:
    from automations.fiber_owners_distro import contacts_write
    return [(a, g) for a, g in ALL_TARGETS if contacts_write.token_path(a).exists()]


def phase_post_all(xlsx: Path, edate: dt.datetime, dry_run: bool = True,
                   create_group: bool = False) -> int:
    """Sync EVERY active target (Raf + reporting) off one roster, apply adds +
    stale-dup cleanup per account, then post ONE combined ✅/❌ thread whose lines
    remove the person from every list they're on."""
    from automations.fiber_owners_distro import contacts_write, notify
    targets = active_targets()
    if not targets:
        print("no target has a read-write Contacts token yet — authorize first.")
        return 2
    kept, _d, _e = build_target(xlsx)
    target = [(o.email, o.name) for o in kept]
    protect = list(load_keep().keys()) + roster.all_roster_emails(xlsx)
    stamp = edate.strftime("%Y-%m-%d")
    print(f"phase POST ({'dry-run' if dry_run else 'LIVE'}) — roster {stamp} — "
          f"targets: {', '.join(a for a, _ in targets)}")

    dep_index: Dict[str, dict] = {}          # canonical email -> combined departure
    for account, group in targets:
        svc = contacts_write._service(account)
        grp = contacts_write.find_group(svc, group)
        if grp is None:
            if create_group and not dry_run:
                grp = svc.contactGroups().create(
                    body={"contactGroup": {"name": group}}).execute()
                print(f"  {account}: created group {group!r}")
            else:
                print(f"  {account}: group {group!r} not found — pass --create-group "
                      "to create it. Skipping this target.")
                continue
        plan = contacts_write.plan_sync(svc, grp, target, protect)
        print(f"  {account}: +{len(plan['add'])} add, "
              f"{len(plan['stale_duplicates'])} stale-dup, "
              f"{len(plan['true_departures'])} departure(s)")
        if not dry_run:
            contacts_write.apply_adds(svc, grp, plan["add"])
            contacts_write.remove_members(svc, grp, plan["stale_duplicates"])
        for m in plan["true_departures"]:
            canons = {roster.canonical(e) for e in m["emails"]}
            hit = next((dep_index[c] for c in canons if c in dep_index), None)
            if hit is None:
                hit = {"name": m["name"], "emails": list(m["emails"]), "removals": []}
            for e in m["emails"]:
                if e not in hit["emails"]:
                    hit["emails"].append(e)
            for c in canons:
                dep_index[c] = hit
            hit["removals"].append({"account": account, "group": group,
                                    "resourceName": m["resourceName"]})

    departures, seen = [], set()
    for d in dep_index.values():
        if id(d) not in seen:
            seen.add(id(d))
            departures.append(d)

    posted = notify.post_departures(departures, stamp, dry_run=dry_run)
    if not dry_run and posted:
        COMBINED_STATE.write_text(json.dumps({
            "channel": notify.CHANNEL_ID, "parent_ts": posted["parent_ts"],
            "roster_date": stamp, "posted_at": dt.datetime.now().isoformat(),
            "candidates": posted["candidates"]}, indent=2), encoding="utf-8")
        print(f"  posted {len(posted['candidates'])} ICD line(s) w/ ✅/❌ across "
              f"{len(targets)} list(s); window open 24h.")
    return 0


def phase_finalize_all(dry_run: bool = True, force: bool = False) -> int:
    """+24h: remove each un-vouched departure from EVERY list it's on."""
    from automations.fiber_owners_distro import contacts_write, notify
    if not COMBINED_STATE.exists():
        print("no pending departures thread — nothing to finalize.")
        return 0
    state = json.loads(COMBINED_STATE.read_text(encoding="utf-8"))
    hrs = (dt.datetime.now() - dt.datetime.fromisoformat(state["posted_at"])).total_seconds() / 3600
    if hrs < 24 and not force:
        print(f"objection window not elapsed ({hrs:.1f}h of 24h). Re-run later or --force.")
        return 0
    to_remove, kept = notify.read_decisions(state["parent_ts"], state["candidates"],
                                            state["channel"])
    n_lists = sum(len(c.get("removals", [])) for c in to_remove)
    print(f"phase FINALIZE ({'dry-run' if dry_run else 'LIVE'}): remove "
          f"{len(to_remove)} ICD(s) across {n_lists} list-entries, {len(kept)} kept (✅).")
    for m in to_remove:
        print(f"   - {m['name']} from {[r['account'] for r in m.get('removals', [])]}")
    if not dry_run:
        for m in to_remove:
            for rem in m.get("removals", []):
                svc = contacts_write._service(rem["account"])
                grp = contacts_write.find_group(svc, rem["group"])
                if grp:
                    contacts_write.remove_members(
                        svc, grp, [{"resourceName": rem["resourceName"]}])
        notify.post_summary(state["parent_ts"], to_remove, kept,
                            channel=state["channel"], dry_run=False)
        COMBINED_STATE.unlink()
        print("  removed from all lists + posted summary; state cleared.")
    return 0


def phase_post(account: str, group: str, xlsx: Path, edate: dt.datetime,
               dry_run: bool = True) -> int:
    """Phase 1: apply ADDs + stale-dup cleanup now; post true departures to Slack
    with a 24h objection window; save pending state for phase_finalize."""
    from automations.fiber_owners_distro import contacts_write, notify
    if not contacts_write.token_path(account).exists():
        print(f"needs a read-write Contacts token for {account} — authorize first.")
        return 2
    svc = contacts_write._service(account)
    grp = contacts_write.find_group(svc, group)
    if grp is None:
        print(f"group {group!r} not found in {account}.")
        return 2
    kept, _d, _e = build_target(xlsx)
    target = [(o.email, o.name) for o in kept]
    protect = list(load_keep().keys()) + roster.all_roster_emails(xlsx)
    plan = contacts_write.plan_sync(svc, grp, target, protect)
    stamp = edate.strftime("%Y-%m-%d")
    print(f"phase POST ({'dry-run' if dry_run else 'LIVE'}) — roster {stamp}: "
          f"+{len(plan['add'])} add, {len(plan['stale_duplicates'])} stale-dup cleanup, "
          f"{len(plan['true_departures'])} departure(s) to announce.")

    if not dry_run:
        created = contacts_write.apply_adds(svc, grp, plan["add"])
        contacts_write.remove_members(svc, grp, plan["stale_duplicates"])
        print(f"  applied: +{len(plan['add'])} ({len(created)} new contacts), "
              f"-{len(plan['stale_duplicates'])} stale dups.")

    posted = notify.post_departures(plan["true_departures"], stamp, dry_run=dry_run)
    if not dry_run and posted:
        state = {"account": account, "group": group, "channel": notify.CHANNEL_ID,
                 "parent_ts": posted["parent_ts"], "roster_date": stamp,
                 "posted_at": dt.datetime.now().isoformat(),
                 "candidates": posted["candidates"]}
        _state_path(account, group).write_text(json.dumps(state, indent=2), encoding="utf-8")
        print(f"  posted {len(posted['candidates'])} ICD line(s) w/ ✅/❌; window open "
              f"24h. state → {_state_path(account, group).name}")
    return 0


def phase_finalize(account: str, group: str, dry_run: bool = True,
                   force: bool = False) -> int:
    """Phase 2 (+24h): remove departures nobody vouched for; keep the vouched."""
    from automations.fiber_owners_distro import contacts_write, notify
    sp = _state_path(account, group)
    if not sp.exists():
        print("no pending departures thread — nothing to finalize.")
        return 0
    state = json.loads(sp.read_text(encoding="utf-8"))
    posted = dt.datetime.fromisoformat(state["posted_at"])
    hrs = (dt.datetime.now() - posted).total_seconds() / 3600
    if hrs < 24 and not force:
        print(f"objection window not elapsed ({hrs:.1f}h of 24h). Re-run later "
              "or pass --force.")
        return 0
    candidates = state["candidates"]
    to_remove, kept = notify.read_decisions(state["parent_ts"], candidates, state["channel"])
    print(f"phase FINALIZE ({'dry-run' if dry_run else 'LIVE'}): "
          f"{len(to_remove)} to remove, {len(kept)} kept (✅ by an approver).")
    for m in to_remove:
        print(f"   - {m['name']} <{', '.join(m['emails'])}>")
    if not dry_run:
        svc = contacts_write._service(account)
        grp = contacts_write.find_group(svc, group)
        contacts_write.remove_members(svc, grp, to_remove)
        notify.post_summary(state["parent_ts"], to_remove, kept,
                            channel=state["channel"], dry_run=False)
        sp.unlink()
        print("  removed + posted summary; pending state cleared.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Sync AT&T Fiber Owners distro from "
                                             "Kelly's weekly roster.")
    ap.add_argument("--account", default=None,
                    help="Single account to sync. Omit to sync ALL active targets "
                         "(Raf + reporting) in one combined run — the scheduled path.")
    ap.add_argument("--group", default=DEFAULT_GROUP,
                    help="Contact group (distribution list) name.")
    ap.add_argument("--roster", help="Path to a roster .xlsx (skip IMAP fetch).")
    ap.add_argument("--phase", choices=["preview", "post", "finalize"],
                    default="preview",
                    help="preview (default, no writes) | post (apply adds + announce "
                         "departures) | finalize (+24h: remove un-vouched).")
    ap.add_argument("--send", action="store_true",
                    help="Actually write (default is a dry-run). Applies to --phase "
                         "post/finalize.")
    ap.add_argument("--create-group", action="store_true",
                    help="With --send post, create the group if it doesn't exist yet.")
    ap.add_argument("--force", action="store_true",
                    help="With --phase finalize, skip the 24h window check.")
    args = ap.parse_args(argv)

    if args.phase == "finalize":
        if args.account:
            return phase_finalize(args.account, args.group, dry_run=not args.send,
                                  force=args.force)
        return phase_finalize_all(dry_run=not args.send, force=args.force)

    if args.roster:
        xlsx = Path(args.roster)
        edate = dt.datetime.fromtimestamp(xlsx.stat().st_mtime)
    else:
        xlsx, edate = roster.fetch_latest_roster()

    if args.phase == "post":
        if args.account:
            return phase_post(args.account, args.group, xlsx, edate,
                              dry_run=not args.send)
        return phase_post_all(xlsx, edate, dry_run=not args.send,
                              create_group=args.create_group)

    preview(xlsx, edate, args.account or DEFAULT_ACCOUNT, args.group)
    return 0


if __name__ == "__main__":
    sys.exit(main())
