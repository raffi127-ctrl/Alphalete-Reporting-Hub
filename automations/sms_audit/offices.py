"""Which offices the recruiting auditor checks, and what "correct" is for each.

Megan 2026-10-01: "Need to be able to enter in the office info like address
and phone and links to make sure they are correct."

WHY A SHEET AND NOT A FILE. The auditor can only catch a wrong address if
somebody has told it the right one. That is a fact about the business, it
changes when an office moves, and the person who knows it should not have to
edit JSON — so it lives in a tab anyone can type into. The repo keeps a
cache so a run still works when Sheets is slow or rate-limited, and says
which it used.

The tab is created with its headers and the four known offices the first
time this runs, so there is never a blank page to guess at.

Columns, one row per office:
    office        AppStream office id, e.g. 11280
    icd_name      the ICD's name EXACTLY as OwnerVille spells it. Not a
                  friendly label: it is what joins this audit to every other
                  report, and a spelling that differs from OV silently fails
                  to match (Megan 2026-10-01). A genuine variant belongs in
                  the shared ICD alias sheet, not retyped differently here.
    owner         whose office
    address       where interviews are actually conducted, suite included
    phone         the recruiting number applicants should see
    r1_mode       "In person" or "Zoom" — how 1st rounds are run
    zoom          the 1st-round Zoom room, when r1_mode is Zoom
    zoom_id       its meeting id
    r2_mode       "In person" or "Zoom" — how 2nd rounds are run
    zoom2         the 2nd-round Zoom room, when r2_mode is Zoom
    zoom2_id      its meeting id
    job_ad_cities cities that legitimately appear in job ads, comma separated
    active        yes/no — no keeps the row without auditing it
    email         where to send their copy of the audit
    slack_user    who filled it in, so /ACA knows them next time
    updated       when they last confirmed it
"""
from __future__ import annotations  # Lucy runs Python 3.9 — keep lazy

import datetime as dt
import json
import sys
from pathlib import Path

CONTROL_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
TAB = "Recruiting Audit Offices"
CACHE = Path(__file__).resolve().parents[2] / "output" / "audit_offices.json"
COLUMNS = ["office", "icd_name", "owner", "address", "phone",
           "r1_mode", "zoom", "zoom_id",
           "r2_mode", "zoom2", "zoom2_id",
           "job_ad_cities", "active", "email", "slack_user", "updated"]

# What we already know, from six weeks of their own traffic. Seeded so the
# tab is never an empty form; every one of these is editable in the sheet.
SEED = [
    {"office": "11280", "icd_name": "Rafael Hidalgo", "owner": "Rafael Hidalgo",
     "address": "3100 Premier Drive, Suite 207, Irving, Texas 75063",
     "phone": "", "zoom": "https://us02web.zoom.us/j/2935077152",
     "zoom_id": "2935077152",
     "job_ad_cities": "Irving, Arlington, Garland, Carrollton, Denton, "
                      "Fort Worth, Frisco, Grand Prairie, Plano, Dallas",
     "active": "yes"},
    {"office": "23965", "icd_name": "Rafael 2nd Funnel", "owner": "Rafael Hidalgo",
     "address": "3100 Premier Drive, Suite 207, Irving, Texas 75063",
     "phone": "", "zoom": "https://us05web.zoom.us/j/3106023771",
     "zoom_id": "3106023771", "job_ad_cities": "", "active": "yes"},
    {"office": "24065", "icd_name": "Raf New Recruiter", "owner": "Rafael Hidalgo",
     "address": "3100 Premier Drive, Suite 207, Irving, Texas 75063",
     "phone": "", "zoom": "https://us06web.zoom.us/j/7946102046",
     "zoom_id": "", "job_ad_cities": "", "active": "yes"},
    {"office": "11580", "icd_name": "Carlos Hidalgo", "owner": "Carlos Hidalgo",
     "address": "1901 N Highway 360, Suite 610, Grand Prairie, Texas 75050",
     "phone": "", "zoom": "https://us02web.zoom.us/j/6224221431",
     "zoom_id": "6224221431", "job_ad_cities": "", "active": "yes"},
]


def _ws():
    from automations.recruiting_report import fill as _fill
    sh = _fill._client().open_by_key(CONTROL_SHEET_ID)
    try:
        return sh.worksheet(TAB)
    except Exception:  # noqa: BLE001 — first run: build it, seeded
        ws = sh.add_worksheet(TAB, rows=60, cols=len(COLUMNS) + 1)
        rows = [COLUMNS] + [[o.get(c, "") for c in COLUMNS] for o in SEED]
        ws.update(values=rows, range_name="A1", raw=True)
        return ws


def _migrate(ws, hdr):
    """Rename the old 'label' header in place. The tab is edited by hand, so
    a column rename has to carry the data, not start a second column."""
    if "label" in hdr and "icd_name" not in hdr:
        ws.update(values=[[("icd_name" if h == "label" else h) for h in hdr]],
                  range_name="A1", raw=True)
        return [("icd_name" if h == "label" else h) for h in hdr]
    return hdr


def load(use_cache_on_failure=True):
    """[office dicts], active ones only. Falls back to the cached copy and
    says so, rather than auditing nothing because Sheets was busy."""
    try:
        ws = _ws()
        rows = ws.get_all_values()
        hdr = _migrate(ws, [h.strip().lower() for h in rows[0]])
        out = []
        for r in rows[1:]:
            d = dict(zip(hdr, r))
            if not (d.get("office") or "").strip():
                continue
            out.append({c: (d.get(c) or "").strip() for c in COLUMNS})
        CACHE.parent.mkdir(exist_ok=True)
        CACHE.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        src = "the '{}' tab".format(TAB)
    except Exception as e:  # noqa: BLE001
        if not use_cache_on_failure or not CACHE.exists():
            raise
        out = json.loads(CACHE.read_text(encoding="utf-8"))
        src = "the CACHED copy ({}: {})".format(type(e).__name__,
                                                str(e).splitlines()[0][:60])
    active = [o for o in out if (o.get("active") or "yes").lower() != "no"]
    return active, src


def find(office_id=None, slack_user=None):
    """The stored row for an office id or the person who filled it in.

    /ACA asks once and remembers: the second time someone runs it we show
    what we hold and ask if it is still right, rather than making them type
    an address they already gave us (Megan 2026-10-01)."""
    rows, _src = load(use_cache_on_failure=True)
    for o in rows:
        if office_id and o.get("office") == str(office_id).strip():
            return o
        if slack_user and o.get("slack_user") == slack_user:
            return o
    return None


def save(office):
    """Insert or update one office row, by office id. Returns (row, created).

    Writes the whole row every time rather than patching cells: the tab is
    edited by hand too, and a partial write against a column someone moved
    is how a config silently points at the wrong field."""
    ws = _ws()
    rows = ws.get_all_values()
    hdr = [h.strip().lower() for h in rows[0]]
    office = dict(office)
    office["updated"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    want = str(office.get("office", "")).strip()
    at = None
    for i, r in enumerate(rows[1:], start=2):
        d = dict(zip(hdr, r))
        if (d.get("office") or "").strip() == want:
            at = i
            merged = {c: (office.get(c) if office.get(c) not in (None, "")
                          else (d.get(c) or "")) for c in COLUMNS}
            office = merged
            break
    line = [[office.get(c, "") for c in COLUMNS]]
    if at is None:
        at = len(rows) + 1
        ws.update(values=line, range_name="A{}".format(at), raw=True)
        created = True
    else:
        ws.update(values=line, range_name="A{}".format(at), raw=True)
        created = False
    if CACHE.exists():
        try:
            CACHE.unlink()          # stale the cache, never serve a stale row
        except OSError:
            pass
    return office, created


def rounds(office):
    """[(label, mode, link, link_id)] for the rounds this office runs."""
    return [("1st round", (office.get("r1_mode") or "").strip(),
             (office.get("zoom") or "").strip(),
             (office.get("zoom_id") or "").strip()),
            ("2nd round", (office.get("r2_mode") or "").strip(),
             (office.get("zoom2") or "").strip(),
             (office.get("zoom2_id") or "").strip())]


def missing_fields(office):
    """What this office has not told us, so the audit can say which checks
    it is NOT running rather than passing them silently.

    A round run IN PERSON needs no Zoom link, and asking for one would make
    a correct setup look incomplete — so the link is only missing when that
    round is actually run over Zoom."""
    gaps = []
    if not office.get("address"):
        gaps.append("interview address — cannot check the address in templates")
    if not office.get("phone"):
        gaps.append("recruiting phone — cannot check the number in templates")
    for label, mode, link, _lid in rounds(office):
        if not mode:
            gaps.append("{} — not told whether it is in person or Zoom"
                        .format(label))
        elif mode.lower().startswith("zoom") and not link:
            gaps.append("{} Zoom link — {} is run over Zoom and no link is "
                        "on file, so interview links are unchecked"
                        .format(label, label))
    return gaps


def main(argv=None):
    offices, src = load()
    print("[offices] {} active, from {}".format(len(offices), src))
    for o in offices:
        gaps = missing_fields(o)
        print("  {:<7} {:<22} {}".format(
            o["office"], o.get("icd_name", "")[:22],
            "OK" if not gaps else "missing: " + "; ".join(
                g.split(" — ")[0] for g in gaps)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
