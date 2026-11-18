"""Spectrum knocks: pull one day's doors from Charter OpenDoor ("Realtime
Results", charter.opendoorsystem.com/external) and sum them up per rep.

Asked for by Maud 2026-11-18 (#lucy-projects, Tiffani's Loom). The Loom looked
at the Bulk Lead Creator map, which has no times. The data with times is the
**Dispositions** tab: one row per door with rep, result ("Not Home", "Sold"…),
date + time, address. That's what this reads.

No browser: the site is plain HTML frames behind a plain login form, so this
uses requests. The three calls are the same ones the page's own frames make
(see `baseUrls` in /ibis/js/ibis.js on the site):
  login            POST /ibis/ctl?command=login…
  reps             GET  vo=dsp  command=getDrivers                 (sf_drivers frame)
  doors for a day  GET  vo=sf   command=getDispatchSmartFormInstances (sf_forms frame)
                   100 rows a page, `offset` pages through.

Login: `spectrum_username` / `spectrum_password` in ownerville-creds.json.

PREVIEW ONLY — writes CSVs to output/, never a Sheet, never Slack:
    python -m automations.spectrum_knocks.pull              # yesterday
    python -m automations.spectrum_knocks.pull 2026-11-17   # a date
"""
from __future__ import annotations

import csv
import datetime as dt
import html
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

import requests

from automations.shared import creds

BASE = "https://charter.opendoorsystem.com"
# The login form's own hidden fields (Charter External).
COMPANY_ID = "1923002"
COMPANY_SHORT_NAME = "external"
# Raf's office in the org tree: Charter External > Credico > "CRE RH 714986".
BUS_UNIT_ID = "1005689"
PAGE_SIZE = 100
# A gap this long between two doors counts as a break.
BREAK_MINUTES = 20

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"

_COMMON = {
    "work_order_id": "0",
    "bus_unit_id": BUS_UNIT_ID,
    "fleet_id": "0",
    "otj": "false",
    "drv_filter": "act=true,wrn=true,nhf=true,unk=true",
}

# Result name -> sheet column. Anything not listed lands in "Other".
CATEGORY = {
    "Not Home": "Not Home",
    "Not Home 2nd Attempt": "Not Home",
    "Not Home - Continue": "Not Home",
    "Not Home - Previous Contact": "Not Home",
    "Not Interested": "Not Interested",
    "Not Interested - Previous Contact": "Not Interested",
    "Presentation - No Sale": "Presentation (No Sale)",
    "Presentation - Previous Contact - No Sale": "Presentation (No Sale)",
    "Presentation - Previous Contact - Follow-Up": "Follow Up",
    "Follow Up": "Follow Up",
    "Sold": "Sold",
    "Mobile Sold": "Mobile Sold",
}
COLUMNS = ["Not Home", "Not Interested", "Presentation (No Sale)", "Follow Up",
           "Sold", "Mobile Sold", "Other"]


class SpectrumError(RuntimeError):
    pass


def login() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0"
    s.get(BASE + "/external", timeout=60)
    r = s.post(
        BASE + "/ibis/ctl?command=login&next_vo=dsp&next_command=getHomePage"
        "&next_template=dispatch/home.vm",
        data={
            "company_id": COMPANY_ID,
            "anonymize": "",
            "company_short_name": COMPANY_SHORT_NAME,
            "username": creds.spectrum_username(),
            "password": creds.spectrum_password(),
        },
        timeout=60,
    )
    if "Login Success" not in r.text:
        raise SpectrumError("Spectrum login failed — check spectrum_username / "
                            "spectrum_password in ownerville-creds.json")
    return s


def reps(s: requests.Session) -> Dict[str, str]:
    """{rep id: 'Last, First'} for every rep in the office."""
    r = s.get(BASE + "/ibis/ctl", params={
        "vo": "dsp", "command": "getDrivers", "template": "dispatch/drivers.vm",
        **_COMMON}, timeout=120)
    found = re.findall(r'id="(\d+)_DRIVER_NAME"[^>]*>([^<]+)<', r.text)
    if not found:
        raise SpectrumError("Spectrum rep list came back empty (session or page changed)")
    return {rid: html.unescape(name).strip() for rid, name in found}


def _cells(row_html: str) -> List[str]:
    return [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", c))).strip()
            for c in re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.S)]


def doors(s: requests.Session, day: dt.date, rep_ids: List[str]) -> List[dict]:
    """Every disposition captured on `day` by any of `rep_ids`."""
    out: List[dict] = []
    offset, total = 0, None
    while True:
        r = s.get(BASE + "/ibis/ctl", params={
            "vo": "sf", "command": "getDispatchSmartFormInstances",
            "template": "smartforms/dispatch_instances.vm", **_COMMON,
            "driver_id_filter": ",".join(rep_ids),
            "instance_date": day.strftime("%m/%d/%Y") + " 12:00 AM",
            "offset": str(offset)}, timeout=300)
        m = re.search(r"Dispositions \((\d+) Total\)", r.text)
        if not m:
            raise SpectrumError("Spectrum dispositions page didn't load (no total)")
        total = int(m.group(1))
        rows = re.findall(r'<tr id="sfi_(\d+)"(.*?)</tr>', r.text, re.S)
        for fid, body in rows:
            c = _cells(body)
            if len(c) < 9:
                continue
            out.append({"rep": c[0], "result": c[1], "time": c[2], "id": fid,
                        "address": c[5], "city": c[7], "wo_status": c[8]})
        offset += PAGE_SIZE
        if not rows or offset >= total:
            break
    if total is not None and len(out) != total:
        raise SpectrumError(f"Got {len(out)} doors but the page says {total}")
    want = day.strftime("%m/%d/%Y")
    stray = [d for d in out if not d["time"].startswith(want)]
    if stray:
        raise SpectrumError(f"{len(stray)} doors aren't from {want} (date filter ignored?)")
    return out


def _t(stamp: str) -> dt.datetime:
    return dt.datetime.strptime(stamp, "%m/%d/%Y %I:%M %p")


def summarize(rows: List[dict], all_reps: Dict[str, str]) -> List[dict]:
    """One line per rep (reps with 0 doors included, at the bottom)."""
    by_rep: Dict[str, List[dict]] = {}
    for d in rows:
        by_rep.setdefault(d["rep"], []).append(d)
    out = []
    for name in sorted(set(all_reps.values()) | set(by_rep)):
        mine = sorted(by_rep.get(name, []), key=lambda d: _t(d["time"]))
        line = {"Rep": name, "Doors": len(mine)}
        for col in COLUMNS:
            line[col] = 0
        for d in mine:
            line[CATEGORY.get(d["result"], "Other")] += 1
        times = [_t(d["time"]) for d in mine]
        gaps = [(b - a).total_seconds() / 60 for a, b in zip(times, times[1:])]
        breaks = [g for g in gaps if g >= BREAK_MINUTES]
        line["First Door"] = times[0].strftime("%I:%M %p").lstrip("0") if times else ""
        line["Last Door"] = times[-1].strftime("%I:%M %p").lstrip("0") if times else ""
        line["Hours Knocking"] = round((times[-1] - times[0]).total_seconds() / 3600, 1) if times else 0
        line[f"Breaks ({BREAK_MINUTES}+ min)"] = len(breaks)
        line["Longest Break (min)"] = int(max(breaks)) if breaks else 0
        out.append(line)
    out.sort(key=lambda l: (-l["Doors"], l["Rep"]))
    return out


def _write_csv(path: Path, rows: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def run(day: dt.date) -> List[dict]:
    s = login()
    all_reps = reps(s)
    rows = doors(s, day, list(all_reps))
    summary = summarize(rows, all_reps)
    stamp = day.isoformat()
    if rows:
        _write_csv(OUTPUT_DIR / f"spectrum_knocks_{stamp}_doors.csv", rows)
    _write_csv(OUTPUT_DIR / f"spectrum_knocks_{stamp}_by_rep.csv", summary)
    return summary


def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    day = (dt.date.fromisoformat(argv[0]) if argv
           else dt.date.today() - dt.timedelta(days=1))
    summary = run(day)
    total = sum(l["Doors"] for l in summary)
    print(f"Spectrum knocks {day}: {total} doors, "
          f"{sum(1 for l in summary if l['Doors'])} reps knocked")
    for l in summary:
        print(f"  {l['Rep']:<22} {l['Doors']:>4} doors  sold {l['Sold']:>2}  "
              f"{l['First Door']:>8} - {l['Last Door']:<8}  "
              f"breaks {l[f'Breaks ({BREAK_MINUTES}+ min)']} "
              f"(longest {l['Longest Break (min)']} min)")
    print(f"CSVs in {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
