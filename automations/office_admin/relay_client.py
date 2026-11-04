"""The admin's computer -> its office's ECO computer, over the LucyEco relay.

The admin sits somewhere else than the office's ECO computer (Megan
2026-11-03), and only the ECO computer holds the Sterling login. So the page
on the admin's computer queues the job on the relay with THE OFFICE'S relay
key -- which can only ever queue and read that one office's jobs -- and the
ECO computer picks it up on its next sweep (office_jobs.py).

ONE-TIME SETUP on the admin's computer (we do it, not the admin):

    python -m automations.office_admin.relay_client --setup omar

It looks the office's key up on the relay workbook's 'Relay Keys' tab when
this computer can read it, else asks for it. Saved to
~/.config/office-admin/relay-<office>.json -- never the repo, which is public.
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path
from typing import Dict, Optional

CONFIG_DIR = Path.home() / ".config" / "office-admin"


class RelayError(RuntimeError):
    pass


def _path(office_key: str) -> Path:
    return CONFIG_DIR / ("relay-%s.json" % office_key.strip().lower())


def configured(office_key: str) -> bool:
    return _path(office_key).exists()


def _rec(office_key: str) -> Dict:
    p = _path(office_key)
    if not p.exists():
        raise RelayError("This computer isn't connected to your office's Lucy yet. "
                         "Ask Lucy's team to finish setting it up.")
    rec = json.loads(p.read_text(encoding="utf-8"))
    if not (rec.get("relay_url") and rec.get("office_key") and rec.get("relay_key")):
        raise RelayError("This computer's Lucy connection is incomplete -- ask Lucy's team.")
    return rec


def _call(office_key: str, extra: Dict) -> Dict:
    from automations.icd_alerts import relay as R
    rec = _rec(office_key)
    body = {"office_key": rec["office_key"], "key": rec["relay_key"]}
    body.update(extra)
    raw = R._post(rec["relay_url"], json.dumps(body).encode("utf-8"))
    try:
        out = json.loads(raw)
    except ValueError:
        raise RelayError("Lucy's relay answered a web page, not JSON -- is the new version deployed?")
    if not out.get("ok"):
        raise RelayError("Lucy's relay said: %s" % (out.get("error") or "no"))
    return out


def request_job(office_key: str, kind: str, payload: Dict, *, mode: str) -> str:
    out = _call(office_key, {"office_job_request": {"kind": kind, "mode": mode,
                                                    "payload": payload}})
    jid = str(out.get("job_id") or "")
    if not jid:
        raise RelayError("Lucy's relay took the job but gave no id")
    return jid


def job_status(office_key: str, job_id: str) -> Dict:
    """{'status': queued|offered|<answer>, 'answered': bool, 'result': {...},
    'offered_at': iso}."""
    return _call(office_key, {"office_job_status": {"job_id": job_id}})


def _key_from_workbook(office_key: str) -> Optional[str]:
    """The office's key off 'Relay Keys', if this computer can read it."""
    try:
        from automations.icd_alerts import post as P
        from automations.recruiting_report.fill import open_by_key
        rows = open_by_key(P.RELAY_SPREADSHEET_ID).worksheet("Relay Keys").get_all_values()
    except Exception:  # noqa: BLE001
        return None
    for r in rows[1:]:
        if len(r) >= 2 and r[0].strip().lower() == office_key and r[1].strip():
            return r[1].strip()
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Connect this computer to an office's relay.")
    ap.add_argument("--setup", metavar="OFFICE", required=True)
    args = ap.parse_args(argv)
    from automations.icd_alerts import offices as O
    office = args.setup.strip().lower()
    key = _key_from_workbook(office)
    if key:
        print("found %s's key on 'Relay Keys'" % office)
    else:
        key = getpass.getpass("Relay key for %s (from 'Relay Keys'): " % office).strip()
    if not key:
        print("no key", file=sys.stderr)
        return 2
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    p = _path(office)
    p.write_text(json.dumps({"relay_url": O.RELAY_URL, "office_key": office,
                             "relay_key": key}), encoding="utf-8")
    try:
        p.chmod(0o600)
    except OSError:  # Windows
        pass
    print("saved %s" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
