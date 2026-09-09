"""Materialize disposition sign-ups into the KNOCKS & DISPOSITIONS run.

The form writes each office to the 'Disposition Signup' tab. This reads that
tab and writes a COMMITTED onboarded_offices.json that gap_alerts.config merges
into OFFICES at import — so an enrolled office joins the existing tick with no
hand-edit to config.py, and the Hub card picks it up.

No schedule entry and no machine choice: one job already loops every office,
and it runs on Lucy 1 because that is the box with iMessage.

DRY-RUN by default; --write applies it. Nothing is committed/pushed — review
the git diff and commit (uncommitted, it survives only until the next
`lucy update` autostash).

  python -m automations.disposition_signup.apply             # show the plan
  python -m automations.disposition_signup.apply --write     # write the JSON
  python -m automations.disposition_signup.apply --only cody --write
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

from automations.disposition_signup import store
from automations.disposition_signup.schema import (
    DEFAULT_HOURS, DEFAULT_TZ as S_DEFAULT_TZ, DispositionRecord,
    campaign_live, campaign_machine, validate,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ONBOARDED_JSON = (REPO_ROOT / "automations" / "gap_alerts"
                  / "onboarded_offices.json")


def _row(rec: DispositionRecord) -> dict:
    """One gap_alerts.config office dict.

    ov is always "impersonate": the enrolling owner is never the login. The one
    "master" row in this repo is Raf, whose rhidalgo login IS office 11280, and
    that row is hardcoded — a form can't produce another one.
    """
    camp = rec.campaign() or {}
    row = {
        "key": rec.key,
        # What impersonation looks for — the OwnerVille office name when it
        # differs from the owner's own.
        "name": rec.office_name(),
        "owner": rec.owner.strip(),
        "ov": "impersonate",
        "campaign_id": rec.campaign_id(),
        "campaign_label": camp.get("label", ""),
        # Every place the board goes, each with its own cadence. The legacy
        # single-`group` field stays EMPTY for form-built offices: the runner
        # only falls back to it for the hardcoded rows that predate this.
        "destinations": [dict(d) for d in rec.destinations],
        "group": "",
        # First name on the card. Raf's own row carries "" (his room, no label
        # needed); an enrolled office always gets one — its board can land in a
        # chat that also sees another office's.
        "label": _label(rec),

        # Chan Park's comparison line is Raf's org's thing, and comparing a
        # brand-new office against it is a decision nobody made on this form.
        "compare": False,
        "enabled": bool(rec.enabled),
        "ov_account": rec.ov_account.strip(),
        "source": "disposition_signup",
        # The box that can reach this office. gap_alerts skips any office that
        # is not its own machine's, so one registry serves both runners.
        "machine": campaign_machine(rec.campaign_key),
    }
    # When and where the field is — only carried when it DIFFERS from the org
    # default, so a row stays readable and an office that never asked for
    # anything special keeps inheriting future changes to the default.
    if rec.tz and rec.tz != S_DEFAULT_TZ:
        row["tz"] = rec.tz
    for field_name in ("day_start", "day_end", "sat_start", "sat_end"):
        val = getattr(rec, field_name)
        if val and val != DEFAULT_HOURS[field_name]:
            row[field_name] = val
    if not rec.saturday:
        row["weekdays"] = [0, 1, 2, 3, 4]
    return row


def _label(rec: DispositionRecord) -> str:
    """The name this office is known by on its own board and in its subject
    lines — the FULL ICD name by default (Megan 2026-09-09).

    It used to be the first name alone. That reads fine on a board posted in the
    office's own channel, but it is also what titles the EMAIL, where "Knocks &
    Dispositions — Isaiah" in an inbox says less than the ICD's actual name and
    cannot tell two Isaiahs apart.

    The board image is unaffected: `_render_board` runs the label through
    `knocks_intraday.first_name`, which keeps the header short for the reason it
    always did — a board sitting in that office's own channel does not need to
    repeat what the channel already says.

    Megan can still override it per office in the confirm view.
    """
    if rec.label.strip():
        return rec.label.strip()
    return rec.owner.strip() or rec.key


def plan() -> "List[dict]":
    out = []
    for d in store.load_all():
        rec = store.record_from_json(d)
        # A pending row must NEVER be materialized — not even by a broad
        # `apply --write`. An unconfirmed office would start texting a room
        # nobody checked.
        if rec.status == "pending":
            print("  (skipping %r — pending, not confirmed yet)" % rec.key)
            continue
        # A campaign OwnerVille has no dispositions for cannot be pulled at
        # all. The sign-up is kept — that is the waiting list — but wiring it
        # would put an office in the run that fails every tick.
        if not campaign_live(rec.campaign_key):
            print("  (skipping %r — %s is on the WAITING LIST, no dispositions "
                  "in OwnerVille yet)"
                  % (rec.key, (rec.campaign() or {}).get("name",
                                                         rec.campaign_key)))
            continue
        reg = store.existing_registry(exclude_key=rec.key)
        problems = validate(rec, existing_keys=[k for k in reg["keys"]
                                                if k != rec.key])
        out.append({"rec": rec, "problems": problems, "row": _row(rec)})
    return out


def _merge_json(rows: "List[dict]", write: bool) -> str:
    existing: Dict[str, dict] = {}
    if ONBOARDED_JSON.exists():
        try:
            existing = {r["key"]: r
                        for r in json.loads(ONBOARDED_JSON.read_text())}
        except Exception:                            # noqa: BLE001
            existing = {}
    added: List[str] = []
    updated: List[str] = []
    for r in rows:
        (updated if r["key"] in existing else added).append(r["key"])
        existing[r["key"]] = r
    if write:
        ONBOARDED_JSON.parent.mkdir(parents=True, exist_ok=True)
        tmp = ONBOARDED_JSON.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(list(existing.values()), indent=2))
        tmp.replace(ONBOARDED_JSON)
    return "%s: +%s ~%s" % (ONBOARDED_JSON.relative_to(REPO_ROOT),
                            added or "—", updated or "—")


def remove(key: str, write: bool) -> str:
    """Drop an office from the materialized registry. -> a one-line summary.

    `_merge_json` only ever adds or updates, so a wired office cannot be taken
    out by re-applying — switching it off in the Sheet leaves a disabled row in
    the JSON forever. This is the other half.

    It removes the ROW, not the sign-up: the Sheet is the record of who asked,
    and `store.delete` is what forgets that.
    """
    if not ONBOARDED_JSON.exists():
        return "%s does not exist — nothing to remove" % ONBOARDED_JSON.name
    try:
        rows = json.loads(ONBOARDED_JSON.read_text())
    except Exception as e:                           # noqa: BLE001
        return "couldn't read %s (%s) — refusing to rewrite it" % (
            ONBOARDED_JSON.name, type(e).__name__)
    kept = [r for r in rows if r.get("key") != key]
    if len(kept) == len(rows):
        return "no office %r in %s" % (key, ONBOARDED_JSON.name)
    gone = [r for r in rows if r.get("key") == key]
    # Say it out loud rather than refusing: taking a LIVE office out is a real
    # thing to want (it is how a test office stops sending), but it is also how
    # a board silently disappears, so it must never happen quietly.
    live = [r for r in gone if r.get("enabled")]
    note = ""
    if live:
        note = ("  ** %r was SWITCHED ON — its board stops now. **"
                % key)
    if write:
        tmp = ONBOARDED_JSON.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(kept, indent=2))
        tmp.replace(ONBOARDED_JSON)
    return "removed %r from %s (%d office(s) left)%s%s" % (
        key, ONBOARDED_JSON.name, len(kept), note,
        "" if write else "   [DRY-RUN — not written]")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="disposition_signup.apply")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--only", default=None)
    ap.add_argument("--remove", default=None, metavar="KEY",
                    help="take this office OUT of the materialized registry "
                         "(applying can only add or update)")
    args = ap.parse_args(argv)

    if args.remove:
        print(remove(args.remove, args.write))
        return 0

    plans = plan()
    if args.only:
        plans = [p for p in plans if p["rec"].key == args.only]
    if not plans:
        # Distinguish "nobody has signed up" from "everyone who has is still
        # waiting on Megan" — the second is the normal state right after a
        # submission and reads as a broken apply otherwise.
        print("Nothing to apply — no confirmed sign-ups"
              + (" (see the pending rows above)." if args.only is None
                 else " for %r." % args.only))
        return 0

    blocked = [p for p in plans if p["problems"]]
    if blocked:
        print("REFUSING to apply — problems:\n")
        for p in blocked:
            print("  x %s:" % p["rec"].key)
            for pr in p["problems"]:
                print("      - %s" % pr)
        return 1

    mode = "WRITE" if args.write else "DRY-RUN"
    print("=== disposition_signup.apply — %s — %d office(s) ===\n"
          % (mode, len(plans)))
    for p in plans:
        rec, row = p["rec"], p["row"]
        print("  - %s (%s): %d destination(s), %s"
              % (rec.key, rec.owner, len(rec.destinations),
                 row.get("campaign_label") or "?"))
        print("      runs on %s" % campaign_machine(rec.campaign_key))
        print("      %s" % rec.hours_label())
        for r in rec.routes():
            print("      %s" % r)
        if not row["enabled"]:
            print("      OFF until Office Access is granted (enabled=false)")
    print()
    print("  " + _merge_json([p["row"] for p in plans], args.write))
    if not args.write:
        print("\nDRY-RUN — nothing written. Re-run with --write, then review "
              "`git diff` and commit.")
    else:
        print("\n* Written. The next gap_alerts tick picks the office up. "
              "Review `git diff`, then commit + push — uncommitted, it is "
              "autostashed away by the next `lucy update`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
