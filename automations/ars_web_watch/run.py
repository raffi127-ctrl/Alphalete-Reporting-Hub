"""ARS -> web watch: tells Eve the day an office starts logging interviews ONLY
in Camila's web (ARS Interview Tracker) and stops filling its ARS REPORT tab.

WHY (Eve 2026-11-20): the ARS REPORT workbooks are being phased out in favour
of Camila's Apps Script web. Several Hub reports still read ARS (Sales Board
stars, Below the Mark, Call List to 2nd, ad scorecards, Raf's All in One). On
11/20 every office was still filling ARS (7 were filling BOTH), so nothing was
missing yet. The day one office goes web-only, those reports quietly lose its
rows — this is the alarm for that day.

READ-ONLY. Reads the five ARS REPORT workbooks (tab per office, column
"Date 1st Rd") and the web's data Sheet (tab Interviews, columns "office" +
"Date 1st Rd"). Writes nothing to either.

RULE: an office is "web-only" when, over the last WINDOW_DAYS days, the web has
at least MIN_WEB rows for it and its ARS tab has zero. Offices with no ARS tab
in the five workbooks are listed apart (they come from other sheets), never
alerted.

Posts ONLY when the web-only set changes, to Eve's DM (in Spanish — it is for
her, not a channel). `--dry-run` prints and posts nothing.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import unicodedata
from pathlib import Path

WEB_SHEET = "1hdsOTlu-HLVjybwOzDPVg07EgvXTHZfQhgsTTu7q8mY"   # ARS Interview Tracker - data
WEB_TAB = "Interviews"
WINDOW_DAYS = 5
MIN_WEB = 3
EVE = "U088E2KJEV8"   # resources/owner-slack-ids.md
STATE = Path(__file__).resolve().parents[2] / "output" / "ars_web_watch" / "last.json"


def slug(name: str) -> str:
    """'Nicolás Luján' and the web id 'nicolas-lujan' -> 'nicolas-lujan'."""
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def parse_date(value):
    raw = str(value or "").strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%m-%d-%Y", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(raw[:10] if fmt == "%Y-%m-%d" else raw, fmt).date()
        except ValueError:
            continue
    return None


def count_recent(grid: list, office_col, date_col: str, start: dt.date, end: dt.date) -> dict:
    """{office_slug: rows dated start..end}. `office_col` is a header name, or
    a fixed office slug when the whole grid is one office's ARS tab."""
    if not grid:
        return {}
    head = [str(h).strip().lower() for h in grid[0]]
    if date_col.lower() not in head:
        return {}
    di = head.index(date_col.lower())
    oi = head.index(office_col.lower()) if office_col.lower() in head else None
    out: dict = {}
    if oi is None:
        out[slug(office_col)] = 0
    for row in grid[1:]:
        d = parse_date(row[di]) if len(row) > di else None
        if not d or not (start <= d <= end):
            continue
        key = slug(row[oi]) if oi is not None and len(row) > oi else slug(office_col)
        if key:
            out[key] = out.get(key, 0) + 1
    return out


def classify(web: dict, ars: dict, min_web: int = MIN_WEB) -> tuple:
    """-> (web_only, no_ars_tab). `ars` holds every ARS tab (0 = tab exists,
    nothing recent)."""
    web_only, no_tab = [], []
    for office, n in sorted(web.items()):
        if n < min_web:
            continue
        if office not in ars:
            no_tab.append(office)
        elif ars[office] == 0:
            web_only.append(office)
    return web_only, no_tab


def read_all(start: dt.date, end: dt.date) -> tuple:
    from automations.recruiting_report.fill import open_by_key
    from automations.icd_sales_board.ars import WORKBOOKS

    ars: dict = {}
    for sid, _label, _letters in WORKBOOKS:
        sh = open_by_key(sid)
        tabs = [w.title for w in sh.worksheets()]
        got = sh.values_batch_get([f"'{t}'!A1:Z4000" for t in tabs]).get("valueRanges", [])
        for t, vr in zip(tabs, got):
            ars.update(count_recent(vr.get("values", []), t, "Date 1st Rd", start, end))
    grid = open_by_key(WEB_SHEET).worksheet(WEB_TAB).get_all_values()
    web = count_recent(grid, "office", "Date 1st Rd", start, end)
    return web, ars


def message(web_only: list, web: dict, start: dt.date, end: dt.date) -> str:
    rng = f"{start:%m/%d}–{end:%m/%d}"
    if not web_only:
        return f"✅ ARS → web: todas las oficinas volvieron a anotar en los ARS ({rng})."
    lines = [f"⚠️ ARS → web: estas oficinas anotan SOLO en la web de Camila ({rng}). "
             "Los reportes del Hub que leen ARS (estrellas del Sales Board, Below the Mark, "
             "Call List, scorecards de anuncios) ya no tienen sus entrevistas:"]
    lines += [f"• {o} — {web[o]} en la web, 0 en ARS" for o in web_only]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="print only, post nothing")
    ap.add_argument("--post-to", default=EVE, help="Slack channel/DM id (default: Eve)")
    a = ap.parse_args(argv)

    end = dt.date.today() - dt.timedelta(days=1)
    start = end - dt.timedelta(days=WINDOW_DAYS - 1)
    web, ars = read_all(start, end)
    web_only, no_tab = classify(web, ars)

    print(f"window {start}..{end}  web offices {len(web)}  ars tabs {len(ars)}")
    print("both:", sorted(o for o in web if web[o] >= MIN_WEB and ars.get(o, 0) > 0))
    print("WEB-ONLY:", web_only)
    print("no ARS tab (not alerted):", no_tab)

    last = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"web_only": []}
    if sorted(web_only) == sorted(last.get("web_only", [])):
        print("no change since last run -> no post")
        return 0
    text = message(web_only, web, start, end)
    if a.dry_run:
        print("[dry-run] would post:\n" + text)
        return 0
    from automations.shared import slack_metrics_post as smp
    smp._client().chat_postMessage(channel=a.post_to, text=text)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"web_only": web_only, "on": str(dt.date.today())}), encoding="utf-8")
    print("posted to", a.post_to)
    return 0


if __name__ == "__main__":
    sys.exit(main())
