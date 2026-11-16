"""Put a hand-found phone list on the relay's 'Phone Lookups' tab. Ours; never shipped.

    python -m automations.oat_processing.phone_lookups_add output/no-phone-lookups-2026-11-16.csv \\
        --office carlos --office-id 11580 [--by "lookups 11/16"] [--via office|admin|sheet] [--dry]

The CSV is the lookup session's own file: `name` (as the walk spells it) and
`phone` required, `account_email` (or `account`) when known, `indeed_name`
kept as a note. The office's computer picks the rows up on its next walk
(oat_processing/phone_lookups) and marks each one sent.

THREE ROADS, tried in this order unless --via picks one:
  office  ~/.config/office-admin/relay-<office>.json -- the office's OWN relay
          key, as the office admin page uses it (office_admin.relay_client
          --setup <office>). The relay files the rows under that office and no
          other, whatever the request says.
  admin   ~/.config/headshots/relay-admin-key (or HEADSHOTS_RELAY_ADMIN_KEY) --
          Lucy's key, any office.
  sheet   the workbook itself, through the Sheets token a Lucy holds. Needs no
          relay redeploy, so it is the road for the first list if the relay is
          still on the old script; the office side still needs the new one.

The relay (and the sheet road) skip a name already waiting unsent for the
office, so a list dropped twice doubles nobody. Nothing here removes a row.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

from automations.oat_processing import phone_lookups as PL

HEAD = ["Office", "Office ID", "Name", "Account", "Phone", "Added At",
        "Added By", "Note", "Fetched At", "Sent At", "Status"]
ADMIN_KEY_PATH = Path.home() / ".config" / "headshots" / "relay-admin-key"


def payload(rows: List[Dict], office_id: str) -> List[Dict]:
    """What travels: the name as typed, the account as a domain, the phone as
    typed (the office side normalises), the office id, the note."""
    out = []
    for r in rows:
        if not r.get("name") or not r.get("raw_phone"):
            continue
        out.append({"name": r["name"], "account": r.get("account") or "",
                    "phone": r.get("raw_phone") or "", "office_id": str(office_id or r.get("office_id") or ""),
                    "note": r.get("note") or ""})
    return out


# --- office key ---------------------------------------------------------------
def office_key_configured(office: str) -> bool:
    from automations.office_admin import relay_client as RC
    return RC.configured(office)


def add_via_office(office: str, rows: List[Dict]) -> Dict:
    from automations.office_admin import relay_client as RC
    out = RC._call(office, {"phone_lookups": {"add": rows}})
    return {"added": int(out.get("added") or 0), "skipped": int(out.get("skipped") or 0)}


# --- admin key ----------------------------------------------------------------
def admin_key() -> str:
    k = os.environ.get("HEADSHOTS_RELAY_ADMIN_KEY", "").strip()
    if not k and ADMIN_KEY_PATH.exists():
        k = ADMIN_KEY_PATH.read_text(encoding="utf-8-sig").strip()
    return k


def add_via_admin(office: str, rows: List[Dict], by: str) -> Dict:
    from automations.icd_alerts import offices as O
    from automations.icd_alerts import relay as R
    body = {"admin_key": admin_key(),
            "phone_lookups_add": {"office": office, "rows": rows, "by": by}}
    raw = R._post(O.RELAY_URL, json.dumps(body).encode("utf-8"))
    try:
        out = json.loads(raw)
    except ValueError:
        raise RuntimeError("the relay answered a web page, not JSON -- is the new "
                           "relay version deployed? (%s)" % " ".join(raw.split())[:120])
    if not out.get("ok"):
        raise RuntimeError("the relay refused: %s" % (out.get("error") or "no reason"))
    return {"added": int(out.get("added") or 0), "skipped": int(out.get("skipped") or 0)}


# --- the sheet itself ---------------------------------------------------------
def _key(s) -> str:
    return "".join(ch for ch in str(s or "").lower() if ch.isalnum())


def add_via_sheet(office: str, rows: List[Dict], by: str) -> Dict:
    from automations.icd_alerts import post as P
    from automations.recruiting_report.fill import open_by_key
    book = open_by_key(P.RELAY_SPREADSHEET_ID)
    try:
        ws = book.worksheet(PL.TAB)
    except Exception:  # noqa: BLE001 -- first list ever: the relay would make it too
        ws = book.add_worksheet(title=PL.TAB, rows=500, cols=len(HEAD))
        ws.update([HEAD], "A1", value_input_option="RAW")
    have = ws.get_all_values()
    waiting = set()
    for r in have[1:]:
        r = list(r) + [""] * (len(HEAD) - len(r))
        if r[0].strip().lower() != office or r[9].strip():
            continue
        waiting.add(_key(r[1]) + "|" + _key(r[2]))
    now = dt.datetime.now().isoformat(timespec="seconds")
    new, skipped = [], 0
    for r in rows:
        k = _key(r.get("office_id")) + "|" + _key(r.get("name"))
        if k in waiting:
            skipped += 1
            continue
        waiting.add(k)
        new.append([office, r.get("office_id") or "", r["name"], r.get("account") or "",
                    r.get("phone") or "", now, by, r.get("note") or "", "", "", ""])
    if new:
        ws.append_rows(new, value_input_option="RAW")
    return {"added": len(new), "skipped": skipped}


def add(office: str, rows: List[Dict], *, by: str = "lucy", via: str = "auto",
        log=print) -> Dict:
    office = office.strip().lower()
    roads = ["office", "admin", "sheet"] if via == "auto" else [via]
    last: Optional[Exception] = None
    for road in roads:
        try:
            if road == "office":
                if not office_key_configured(office):
                    continue
                out = add_via_office(office, rows)
            elif road == "admin":
                if not admin_key():
                    continue
                out = add_via_admin(office, rows, by)
            else:
                out = add_via_sheet(office, rows, by)
        except Exception as e:  # noqa: BLE001 -- try the next road
            last = e
            log("%s road failed: %s: %s" % (road, type(e).__name__, str(e)[:160]))
            continue
        out["via"] = road
        return out
    raise RuntimeError("no road to the relay from this computer%s" % (
        " (last: %s)" % last if last else " -- see the module docstring"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Hand a looked-up phone list to an office's push.")
    ap.add_argument("csv")
    ap.add_argument("--office", required=True, help="relay office key, e.g. carlos")
    ap.add_argument("--office-id", default="", help="ApplicantStream office id, e.g. 11580")
    ap.add_argument("--by", default="", help="who found them (goes in Added By)")
    ap.add_argument("--via", choices=("auto", "office", "admin", "sheet"), default="auto")
    ap.add_argument("--dry", action="store_true", help="show what would be added, send nothing")
    args = ap.parse_args(argv)
    rows = payload(PL.rows_from_csv(args.csv), args.office_id)
    bad = [r["name"] for r in rows if not PL.digits10(r["phone"])]
    print("%d row(s) in %s for office %s%s" % (
        len(rows), args.csv, args.office, " (id %s)" % args.office_id if args.office_id else ""))
    if bad:
        print("  not ten digits (will wait for a person on the tab): %s" % ", ".join(bad))
    if args.dry:
        for r in rows:
            print("  %-28s %-32s %s" % (r["name"], r["account"], r["phone"]))
        return 0
    out = add(args.office, rows, by=args.by or "lookups %s" % dt.date.today().isoformat(),
              via=args.via)
    print("added %d, skipped %d (already waiting) via the %s road"
          % (out["added"], out["skipped"], out["via"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
