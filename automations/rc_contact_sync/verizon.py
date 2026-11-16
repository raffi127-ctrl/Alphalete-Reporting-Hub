"""Verizon customers -> Taylor's RingCentral address book, "(VZ)" on the last
name. RUNS ON LUCY 2 (where the RingCentral creds live).

Carlos 2026-11-15: "the same way that we sync contacts on Taylor's
RingCentral for NDS, can we sync the Verizon customer contact info on
RingCentral? if it's a Verizon customer, can we put (VZ) next to their last
name so that we know it's a Verizon customer?" ... "Go ahead and add in the
customers you see on there."

SOURCE: the 'VZ Credico Lines' tab on the control sheet, written on Lucy 1 by
verizon_office.credico_lines off Credico ARC's Commissions workbooks -- one
row per line with the customer's full 10-digit line number (Credico's daily
file masks it). Credico pays two weeks behind, so a line reaches the tab about
two weeks after it activates; the tab is the only Verizon source with a
number today.

ONE CONTACT PER LINE, like the NDS extra-line rule (Carlos 2026-11-02): the
customer's first line is "<First> <Initial> (VZ)", the others on the same
order "<First> <Initial> - Line 2 (VZ)" ... Company "Verizon", Mobile = the
line, Notes "Rep Name: <rep> | Verizon line of order <#> | signed <date>".
Credico gives first name + last initial only, so that is the name.

SAFETY RAILS, the NDS pipeline's: DRY RUN by default (--live creates); the
address book is indexed by phone first so a re-run adds nothing twice; a
state file (rc_contact_sync_verizon_state.json) remembers every line done,
written per contact; cancelled lines (ClientStatus / ARCStatus cancel) are
skipped -- no contact for a customer who never activated.

    python -m automations.rc_contact_sync.verizon            # dry run
    python -m automations.rc_contact_sync.verizon --live
    python -m automations.rc_contact_sync.verizon --live --limit 5
    lucy rerun rc_contact_sync_verizon -- --live

Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

from automations.rc_contact_sync import config as C
from automations.rc_contact_sync import ringcentral as RC

CONTROL_SHEET = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
# The schedule_config key, so shared/delivery_check finds the proof under the
# id it asks about (it also tries the dashed spelling). Its NDS siblings
# rc_contact_sync and rc_contact_sync_raf have written a manifest all along;
# this entry point was the one that didn't, which is why a clean re-run on
# 11-15 still left failure-rc_contact_sync_verizon open all day on "ran clean,
# but nothing can confirm it DELIVERED".
REPORT_ID = "rc_contact_sync_verizon"
TAB = "VZ Credico Lines"
STATE_PATH = C.CONFIG_DIR / "rc_contact_sync_verizon_state.json"
TAG = "(VZ)"
COMPANY = "Verizon"
CANCEL_WORDS = ("cancel", "reject", "disconnect")


def load_state() -> Dict[str, dict]:
    try:
        return json.loads(STATE_PATH.read_text())
    except (OSError, ValueError):
        return {}


def save_state(state: Dict[str, dict]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=1))
    tmp.replace(STATE_PATH)


def read_tab() -> List[dict]:
    from automations.recruiting_report.fill import _retry, open_by_key
    ws = open_by_key(CONTROL_SHEET).worksheet(TAB)
    rows = _retry(ws.get_all_values)
    if not rows:
        return []
    hdr = [h.strip() for h in rows[0]]
    return [dict(zip(hdr, r)) for r in rows[1:] if any(c.strip() for c in r)]


def is_cancelled(line: dict) -> bool:
    s = ("%s %s" % (line.get("Client Status", ""), line.get("ARC Status", ""))).lower()
    return any(w in s for w in CANCEL_WORDS) or bool(line.get("Cancel Date", "").strip())


def contacts_for(lines: List[dict]) -> List[dict]:
    """Tab rows -> contact specs, one per live line, order by order, the first
    line plain and the rest "- Line N". Lines sorted by phone inside an order
    so the numbering is stable run to run."""
    by_order: Dict[str, List[dict]] = collections.defaultdict(list)
    for l in lines:
        if not l.get("Phone", "").strip().isdigit() or is_cancelled(l):
            continue
        by_order[l.get("Order #", "")].append(l)
    out = []
    for order, ls in by_order.items():
        ls.sort(key=lambda x: x["Phone"])
        for n, l in enumerate(ls, 1):
            cust = " ".join(l.get("Customer", "").split())
            parts = cust.split()
            first, last = (parts[0], " ".join(parts[1:])) if parts else ("Customer", "")
            suffix = "" if n == 1 else " - Line %d" % n
            out.append({
                "key": "vz:%s:%s" % (order, l["Phone"]),
                "first": first.title(), "last": ("%s%s %s" % (last.title(), suffix, TAG)).strip(),
                "phone": l["Phone"], "company": COMPANY,
                "notes": "Rep Name: %s | Verizon line%s of order %s | signed %s"
                         % (l.get("Rep", "?"), suffix.replace(" - ", " ").lower(), order, l.get("Signed Date", "?")),
                "label": "%s %s (%s)" % (cust, suffix.strip(" -"), l.get("Rep", "?")),
            })
    return out


def _manifest(failed: List[str], *, dry_run: bool, note: str = "") -> None:
    """Publish the run so a clean one can close its own ticket.

    Same helper as the NDS sibling (run.py::_manifest), for the same reason:
    a LaunchAgent report that doesn't publish is a report nobody can see fail
    [[feedback_launchd_reports_must_publish]].

    A DRY RUN WRITES NOTHING AT ALL, and the guard is this `return`, not the
    `dry_run=` flag. That flag only silences the Slack side — run_manifest's
    own comment is explicit: "A dry run may write its manifest; it may not
    speak in the channel." So passing it through still drops a file that
    delivery_check reads as DELIVERED. This module is DRY RUN BY DEFAULT
    (`--live` is opt-in), so relying on the flag would have marked every
    preview delivered while creating zero contacts — the false green this
    whole mechanism is under orders not to build.

    Never raises: the contacts are in the address book either way."""
    if dry_run:
        return
    try:
        from automations.shared import run_manifest as _rm
        _rm.write_manifest(REPORT_ID, failed=failed, kind="part", note=note,
                           dry_run=dry_run)
    except Exception as e:                                 # noqa: BLE001
        print("  (manifest not written: %s: %s)" % (type(e).__name__, str(e)[:120]))


def run(*, live: bool, limit: Optional[int] = None, log=print) -> int:
    lines = read_tab()
    specs = contacts_for(lines)
    log("[vz-rc] %d line(s) on '%s', %d live line(s) -> contact(s)" % (len(lines), TAB, len(specs)))
    if not specs:
        # A day with no live line is a real zero, not a miss — Credico pays two
        # weeks behind, so quiet days are normal and the tab being empty IS the
        # answer. Still publish, or every such day holds the ticket open.
        _manifest([], dry_run=not live,
                  note="no live Verizon line on %r — nothing to sync" % TAB)
        return 0
    creds = C.rc_creds()
    info = RC.token_info(creds)
    token = info["access_token"]
    me = RC.identity(info)
    RC.assert_identity(me, creds.get("expected_owner_id") or C.RC_OWNER_ID)
    contacts_ext = str(creds["contacts_extension_id"])
    book = RC.address_book(token, contacts_ext)
    by_phone = RC.index_by_phone(book)
    log("[vz-rc] address book: %d existing contact(s)" % len(book))
    state = load_state()
    added = skipped = failed = 0
    # NAMES, not just a count: the manifest (and the alert built from it) says
    # which customers did not make it, so a re-run is targeted instead of a
    # guess at which of N lines broke.
    failed_labels: List[str] = []
    for s in specs:
        if limit is not None and added >= limit:
            break
        phone = RC.norm_phone(s["phone"])
        if s["key"] in state:
            skipped += 1
            continue
        if phone in by_phone:
            skipped += 1
            state[s["key"]] = {"phone": phone, "existing": True, "when": dt.date.today().isoformat()}
            if live:
                save_state(state)
            log("  – %s: %s already in the address book" % (s["label"], RC.e164(s["phone"])))
            continue
        if not live:
            log("  [dry-run] would create: name=%r company=%r phone=%s notes=%r"
                % ("%s %s" % (s["first"], s["last"]), s["company"], RC.e164(s["phone"]), s["notes"]))
            added += 1
            continue
        try:
            RC.create_contact(token, contacts_ext, first=s["first"], last=s["last"],
                              company=s["company"], phone=s["phone"], notes=s["notes"])
        except RC.RCError as e:
            failed += 1
            failed_labels.append(s["label"])
            log("  ✗ %s: %s" % (s["label"], str(e)[:200]))
            continue
        state[s["key"]] = {"phone": phone, "existing": False, "when": dt.date.today().isoformat()}
        save_state(state)
        by_phone[phone] = {"company": s["company"]}
        added += 1
        log("  + %s %s — %s" % (s["first"], s["last"], RC.e164(s["phone"])))
    log("[vz-rc] %s: %d added, %d already there, %d failed" % ("LIVE" if live else "DRY RUN", added, skipped, failed))
    _manifest(failed_labels, dry_run=not live,
              note="%d added, %d already in the address book%s"
                   % (added, skipped,
                      (", %d failed" % failed) if failed else ""))
    return 1 if failed else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="create the contacts (default: dry run)")
    ap.add_argument("--limit", type=int, help="create at most N contacts this run")
    a = ap.parse_args(argv)
    return run(live=a.live, limit=a.limit)


if __name__ == "__main__":
    sys.exit(main())
