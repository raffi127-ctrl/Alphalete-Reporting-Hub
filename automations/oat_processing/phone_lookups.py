"""Numbers a person found by hand, handed to the One App at a time walk.

WHAT THIS IS FOR. The walk flags an applicant whose record and resume both
carry no phone number, and the noon/4pm to-do list asks a person to find it
(Indeed's "Call" pop-up on the candidate page has it). Until now the number
they found went nowhere: the office's computer re-read the same resume, found
nothing again, and the applicant stayed on the list. Carlos, 2026-11-16, with
thirty of his own looked up: "make sure the Lucy that gets the relay machine
to push all the resumes for me gets all the phone numbers so that they can
get sent to the call list."

HOW A NUMBER TRAVELS. The office's computer holds no Google access, so the
list cannot be a Sheet it reads. It is the relay's 'Phone Lookups' tab, and
the computer asks the relay for its own office's rows -- office key, like
every relay call -- the first time a walk meets an applicant with no number:

    our side  -> relay   rows: office, office id, name, account, phone
                         (phone_lookups_add.py: the office's own key, Lucy's
                          admin key, or a person typing into the tab)
    the walk  -> relay   "my office's unsent rows?"            (office key)
              <- relay   that office's rows, nobody else's
    the walk             types the number in, Send to AI
              -> relay   "row N: sent"                          (office key)

A hand-run with no relay enrollment (a laptop) reads output/phone-lookups.csv
instead -- the columns the lookup session writes -- and the last relay pull
is cached in output/ so a relay outage does not lose the list mid-day. A relay
that has not been redeployed yet answers 'bad day'; that reads as "no list",
and the walk goes on exactly as before.

WHAT IT NEVER DOES. It never removes anyone: a number that cannot be typed
(a Mexico number, say) leaves the applicant on the to-do list with the row
marked for a person. It never clicks past a verify box. It never texts: the
send is the same Send to AI the walk already clicks, under the office's own
texting rule.

OFF SWITCH. OAT_NO_PHONE_LOOKUPS=1 in the environment reads as an empty
list, for a walk that must not type anything a person wrote.

MATCHING. The name as the walk reads it, folded (case, accents, punctuation),
AND the Indeed account it came in under (domain match) -- two applicants can
share a name across accounts. A row with no account matches on the name alone.
"""
from __future__ import annotations  # Lucy 2 / the office machines run Python 3.9

import csv
import datetime as dt
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional

from . import config

TAB = "Phone Lookups"
MANUAL_CSV = "phone-lookups.csv"        # output/phone-lookups.csv: a hand-run's own list
SENT = ("sent", "sent_override")        # the outcomes that finish a row
BAD_NUMBER = "bad_number"               # not ten digits: the row waits for a person
CACHE_MAX_AGE_DAYS = 3                  # an older pull is not a list, it is history
RELOAD_AFTER_MIN = 20                   # one process walking several offices, or all day

_LOADED: Optional[Dict] = None          # this walk's list: {"rows": [...], "source": str}
_MARKED: set = set()                    # (row, name, status) already reported this walk
_log = print


class RelayUnsupported(RuntimeError):
    """The relay answered, but does not know the call (not redeployed yet)."""


def set_logger(fn) -> None:
    global _log
    _log = fn


# --- shapes ---------------------------------------------------------------
def fold(name) -> str:
    """'Genesis Lee-Chin' and 'genesis lee chin' are one person: lower-case,
    accents and punctuation off, one space between words (run._norm_name)."""
    t = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-z0-9 ]+", " ", t.lower())
    return " ".join(t.split())


def domain(account) -> str:
    """The account's domain ('team@x.com' and 'x.com' both give 'x.com'), or
    '' for anything that is not one ('Indeed', a display name, blank)."""
    a = str(account or "").strip().lower()
    a = a.split("@", 1)[1].strip() if "@" in a else a
    if not a or "." not in a or " " in a:
        return ""
    return a


def digits10(phone) -> Optional[str]:
    """The ten digits the record's phone fields take, or None. A leading 1 is
    dropped; anything else (a Mexico number, a partial) is not a US number
    and is never typed in -- run._fill_phone_field would refuse it anyway."""
    d = re.sub(r"\D", "", str(phone or ""))
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    return d if len(d) == 10 else None


def _row(name, phone, account="", office_id="", row=None, note="") -> Dict:
    return {"name": str(name or "").strip(), "fold": fold(name),
            "account": domain(account), "office_id": str(office_id or "").strip(),
            "phone": digits10(phone), "raw_phone": str(phone or "").strip(),
            "row": row, "note": str(note or "").strip()}


def rows_from_csv(path) -> List[Dict]:
    """The lookup session's CSV: `name` and `phone` required; `account_email`
    (or `account`) and `office_id` when known; `indeed_name` kept as a note."""
    out = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            name = (r.get("name") or "").strip()
            phone = (r.get("phone") or "").strip()
            if not name or not phone:
                continue
            shown = (r.get("indeed_name") or "").strip()
            out.append(_row(name, phone,
                            r.get("account_email") or r.get("account") or "",
                            r.get("office_id") or "",
                            note=shown if fold(shown) != fold(name) else ""))
    return out


# --- where the list lives on this machine ---------------------------------
def _root() -> Path:
    # REPO-ROOT-anchored, like the walk's own caches: the office push and a
    # hand-run start from different working directories.
    return Path(__file__).resolve().parents[2]


def _cache_path() -> Path:
    return _root() / "output" / ("phone-lookups%s.json" % config.FILE_SUFFIX)


def _csv_path() -> Path:
    return _root() / "output" / MANUAL_CSV


def _sent_path() -> Path:
    return _root() / "output" / ("phone-lookups-sent%s.jsonl" % config.FILE_SUFFIX)


def _write_cache(rows: List[Dict]) -> None:
    try:
        p = _cache_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"at": dt.datetime.now().isoformat(timespec="seconds"),
                                 "rows": rows}, ensure_ascii=False), encoding="utf-8")
    except Exception as e:  # noqa: BLE001 -- the cache is a convenience
        _log("    [lookup] could not cache the list: %s" % type(e).__name__)


def _read_cache() -> List[Dict]:
    try:
        d = json.loads(_cache_path().read_text(encoding="utf-8"))
        at = dt.datetime.fromisoformat(str(d.get("at") or ""))
        if dt.datetime.now() - at > dt.timedelta(days=CACHE_MAX_AGE_DAYS):
            return []
        return [r for r in (d.get("rows") or []) if isinstance(r, dict) and r.get("fold")]
    except Exception:  # noqa: BLE001 -- no cache, or an unreadable one
        return []


# --- the relay --------------------------------------------------------------
def _enrollment() -> Dict:
    """The relay enrollment that pushes resumes on this machine, or {} (a
    Lucy, a laptop)."""
    try:
        from automations.icd_alerts import resume_push as RP
        return RP.push_record() or {}
    except Exception:  # noqa: BLE001 -- no enrollment file, no icd_alerts config
        return {}


def _call(body: Dict) -> Optional[Dict]:
    """One relay call for this office. None when this machine has no relay.
    A network failure raises -- the caller decides what the list is then."""
    rec = _enrollment()
    if not rec.get("office_key"):
        return None
    from automations.icd_alerts import relay as R
    ep = R._endpoint(str(rec.get("office_key") or ""))
    req = {"office_key": ep["office_key"], "key": ep["relay_key"]}
    req.update(body)
    out = json.loads(R._post(ep["relay_url"], json.dumps(req).encode("utf-8")))
    return out if isinstance(out, dict) else {}


def fetch(office_id="") -> Optional[List[Dict]]:
    """This office's unsent rows off the relay. None = no relay on this
    machine. RelayUnsupported = a relay that has not been redeployed."""
    out = _call({"phone_lookups": {"office_id": str(office_id or "")}})
    if out is None:
        return None
    if not out.get("ok"):
        raise RelayUnsupported(str(out.get("error") or "no reason")[:80])
    rows = []
    for r in out.get("lookups") or []:
        if isinstance(r, dict) and r.get("name"):
            rows.append(_row(r.get("name"), r.get("phone"), r.get("account"),
                             r.get("office_id"), row=r.get("row")))
    return rows


def load(office_id=None, *, refresh: bool = False) -> List[Dict]:
    """This walk's list, read once: the relay (cached to output/), else the
    last cached pull, plus output/phone-lookups.csv for a hand-run. Rows for
    another office never come back."""
    global _LOADED
    office_id = str(office_id if office_id is not None
                    else getattr(config, "OFFICE_ID", "") or "")
    if (_LOADED is not None and not refresh and _LOADED.get("office_id") == office_id
            and dt.datetime.now() - _LOADED["at"] < dt.timedelta(minutes=RELOAD_AFTER_MIN)):
        return _LOADED["rows"]
    if os.environ.get("OAT_NO_PHONE_LOOKUPS"):
        _LOADED = {"rows": [], "source": "off", "office_id": office_id,
                   "at": dt.datetime.now()}
        return []
    rows: List[Dict] = []
    sources: List[str] = []
    enrolled = bool(_enrollment().get("office_key"))
    if enrolled:
        try:
            got = fetch(office_id)
            if got is not None:
                rows, sources = list(got), ["relay"]
                _write_cache(rows)
        except RelayUnsupported as e:
            _log("    [lookup] the relay does not take phone lookups yet (%s) -- "
                 "redeploy resources/icd-alerts-relay.gs; using the last pull" % e)
        except Exception as e:  # noqa: BLE001 -- offline; the cache serves
            _log("    [lookup] relay did not answer (%s) -- using the last pull"
                 % type(e).__name__)
        if "relay" not in sources:
            cached = _read_cache()
            if cached:
                rows, sources = cached, ["cache"]
    if _csv_path().exists():
        try:
            extra = rows_from_csv(_csv_path())
            rows = rows + extra
            sources.append("output/%s" % MANUAL_CSV)
        except Exception as e:  # noqa: BLE001 -- a bad CSV is not a reason to stop the walk
            _log("    [lookup] could not read output/%s: %s" % (MANUAL_CSV, type(e).__name__))
    if office_id:
        rows = [r for r in rows if not r.get("office_id") or r["office_id"] == office_id]
    _LOADED = {"rows": rows, "source": "+".join(sources) or "none",
               "office_id": office_id, "at": dt.datetime.now()}
    if rows:
        bad = sum(1 for r in rows if not r.get("phone"))
        _log("    [lookup] %d number(s) waiting for office %s (%s)%s"
             % (len(rows), office_id or "?", _LOADED["source"],
                " -- %d not ten digits, left for a person" % bad if bad else ""))
    elif sources:
        _log("    [lookup] no numbers waiting for office %s (%s)"
             % (office_id or "?", _LOADED["source"]))
    return rows


def find(name, account="", office_id=None, rows=None) -> Optional[Dict]:
    """The row for this applicant, or None.

    Same folded name AND same account domain first; then a same-name row that
    names no account. A same-name row under a DIFFERENT account is somebody
    else. With no account on the record (a thin read) the name decides, but
    only when it points at exactly one row."""
    rows = load(office_id) if rows is None else rows
    f = fold(name)
    if not f:
        return None
    same = [r for r in rows if r.get("fold") == f]
    if not same:
        return None
    dom = domain(account)
    if dom:
        for r in same:
            if r.get("account") == dom:
                return r
        for r in same:
            if not r.get("account"):
                return r
        return None
    if len(same) == 1:
        return same[0]
    _log("    [lookup] %d rows named %r and no account on the record -- "
         "not guessing" % (len(same), str(name).strip()))
    return None


def mark(hit: Dict, status: str) -> bool:
    """Tell the relay how the row went. 'sent*' finishes it; anything else
    (a refused send, a number that is not ten digits) leaves the row for a
    person with the status on it. Best effort: a lost report costs one
    re-fetch of a row that will never match again, nothing more."""
    status = str(status or "")[:60]
    key = (hit.get("row"), hit.get("fold"), status)
    if not status or key in _MARKED:
        return True
    _MARKED.add(key)
    _remember(hit, status)
    if hit.get("row") is None:
        return False            # a CSV row: nothing upstream to mark
    try:
        out = _call({"phone_lookups": {"sent": [
            {"row": hit["row"], "name": hit.get("name", ""), "status": status}]}})
    except Exception as e:  # noqa: BLE001
        _log("    [lookup] could not report %r for %s (%s)"
             % (status, hit.get("name"), type(e).__name__))
        return False
    ok = bool(out and out.get("ok") and int(out.get("marked") or 0) > 0)
    if not ok:
        _log("    [lookup] the relay did not mark %s %r (%s)"
             % (hit.get("name"), status, (out or {}).get("error") or "no row"))
    return ok


def _remember(hit: Dict, status: str) -> None:
    try:
        p = _sent_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": dt.datetime.now().isoformat(timespec="seconds"),
                                 "name": hit.get("name"), "row": hit.get("row"),
                                 "status": status}, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 -- an audit line, not the send
        pass


def reset() -> None:
    """A new walk reads the list afresh."""
    global _LOADED
    _LOADED = None
    _MARKED.clear()
