"""Place an office in the 9 PM knocks mail by itself, the day its access lands.

Eve 2026-09-24, on Shealey Miller (Angel Padilla's office 23858, not yet on
Raf's Office Access list): "pido acceso en ownerville y cuando lo tengamos
sumala automaticamente".

The boards need nothing: the morning capture impersonates her every day and
the day the grant lands her board simply appears. The 9 PM mail needs one more
thing — her office's timezone — and that can only be read (Company Information,
p=767) once access exists. So this runs daily on Lucy 3 after the capture:

  * nothing pending (every zones.AUTO_ZONE_ICDS office already has a zone)
    -> prints so and exits 0 without opening ownerville;
  * still no access -> one line, exit 0; tomorrow tries again;
  * address read -> zone written to zones.AUTO_ZONE_JSON (used from the next
    tick on) and Eve gets ONE mail saying the city and the zone.

    python -m automations.captainship_night_knocks.await_zone
    python -m automations.captainship_night_knocks.await_zone --dry-run
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from typing import Dict, List

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 — Windows console, best effort
    pass

from automations.captainship_night_knocks import zones as Z


def pending() -> List[str]:
    """AUTO_ZONE_ICDS offices that no layer can place yet."""
    return [i for i in Z.AUTO_ZONE_ICDS if Z.zone_for(i) is None]


def record(results: Dict[str, dict], path=None) -> Dict[str, dict]:
    """Merge the resolved harvest records into the auto file. Returns the ones
    newly written. Unresolved records are left out: no zone is the safe state."""
    p = path or Z.AUTO_ZONE_JSON
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        data = {}
    zones = data.setdefault("zones", {})
    new = {}
    for icd, rec in results.items():
        zone = rec.get("zone")
        if not zone or zone not in Z.ZONE_LABEL:
            continue
        if Z.normalize(icd) not in {Z.normalize(n) for n in Z.AUTO_ZONE_ICDS}:
            continue
        zones[icd] = {"zone": zone, "city": rec.get("city"),
                      "state": rec.get("state"),
                      "at": dt.datetime.now().isoformat(timespec="seconds")}
        new[icd] = zones[icd]
    if new:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2, sort_keys=True),
                     encoding="utf-8")
    return new


def notify(new: Dict[str, dict], *, dry_run: bool, logfn=print) -> None:
    from automations.captainship_night_knocks import mail
    lines = "".join(
        "<li><b>%s</b>: %s, %s &rarr; %s (%s)</li>"
        % (icd, r.get("city"), r.get("state"), Z.ZONE_LABEL.get(r["zone"]),
           r["zone"]) for icd, r in new.items())
    subject = "Night knocks: %s placed — 9 PM mail starts tonight" % (
        ", ".join(new))
    body = ("<p>Ownerville access is working now, so the office address was "
            "read and the timezone set automatically:</p><ul>%s</ul>"
            "<p>If the city is wrong, add the right zone to "
            "<code>zones.ICD_TIMEZONES</code> — that table always wins.</p>"
            % lines)
    if dry_run:
        logfn("[await-zone] DRY-RUN — would mail %s: %s"
              % (", ".join(mail.ALERT_RECIPIENTS), subject))
        return
    mail.send_plain(subject, body, list(mail.ALERT_RECIPIENTS), logfn=logfn)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="harvest and print, but write nothing and mail nobody")
    args = ap.parse_args(argv)

    todo = pending()
    if not todo:
        print("[await-zone] nothing pending — every auto office has a zone")
        return 0
    print("[await-zone] pending: %s" % ", ".join(todo), flush=True)

    from automations.knocks_request.service import wait_for_ownerville
    if not wait_for_ownerville():
        print("[await-zone] ownerville busy — tomorrow's run tries again")
        return 0

    from automations.captainship_night_knocks.harvest_zones import harvest
    results = harvest(todo)
    for icd, rec in results.items():
        if not rec.get("zone"):
            print("[await-zone] %s — not yet: %s" % (icd, rec.get("note")))
    if args.dry_run:
        for icd, rec in results.items():
            if rec.get("zone"):
                print("[await-zone] DRY-RUN — %s: %s, %s -> %s"
                      % (icd, rec.get("city"), rec.get("state"), rec["zone"]))
        return 0
    new = record(results)
    for icd, r in new.items():
        print("[await-zone] ✓ %s placed: %s, %s -> %s"
              % (icd, r["city"], r["state"], r["zone"]))
    if new:
        notify(new, dry_run=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
