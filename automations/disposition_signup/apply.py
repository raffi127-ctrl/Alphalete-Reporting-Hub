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
    if rec.label.strip():
        return rec.label.strip()
    owner = rec.owner.strip()
    return owner.split()[0] if owner else rec.key


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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="disposition_signup.apply")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--only", default=None)
    args = ap.parse_args(argv)

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
