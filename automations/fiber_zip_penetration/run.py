"""Fiber zip penetration -> each owner's Line Up tab, once a day.

Source: Tableau > ATT Tracker 2.1 - D2D > Fiber Lead Performance >
worksheet 'Office New Fiber Lead Penetration By Zip' (crosstab), one row per
owner x zip. Same download the Int WoW Penetration report uses.

  python -m automations.fiber_zip_penetration.run                 # live
  python -m automations.fiber_zip_penetration.run --dry-run
  python -m automations.fiber_zip_penetration.run --csv <file>    # no Tableau pull
  python -m automations.fiber_zip_penetration.run --owner "Rafael Hidalgo"
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

from automations.fiber_zip_penetration import config, core

MANIFEST_ID = "fiber-zip-penetration"
CENTRAL = ZoneInfo("America/Chicago")


def _manifest(clean: bool, note: str = "") -> None:
    try:
        from automations.shared import run_manifest as rm
        if clean:
            rm.mark_clean(MANIFEST_ID, kind="fiber_zip_penetration")
        else:
            rm.write_manifest(MANIFEST_ID, failed=["fiber zip penetration fill"],
                              retry_args=[], kind="fiber_zip_penetration",
                              alert=False, note=note)
    except Exception:  # noqa: BLE001 -- best-effort, never fails the run
        pass


def fill_owner(owner: str, sheet_id: str, data: dict, today: dt.date,
               dry_run: bool) -> bool:
    from automations.recruiting_report.fill import open_by_key
    sh = open_by_key(sheet_id)
    tabs = core.target_tabs([w.title for w in sh.worksheets()], today)
    if not tabs:
        print("  [%s] no 'Line Up WE m.d' tab found" % owner)
        return False
    ok = True
    for title in tabs:
        ws = sh.worksheet(title)
        values = ws.get_all_values()
        lay = core.layout(values)
        if not lay:
            print("  [%s] '%s': no 'Current Penetration Rate' + 'Zip Code' headers -- skipped"
                  % (owner, title))
            ok = False
            continue
        formulas = ws.get_all_values(value_render_option="FORMULA")
        writes, s = core.plan(values, formulas, lay, data)
        print("  [%s] '%s': %d zips on the tab, %d matched Tableau, %d not in Tableau %s"
              % (owner, title, len(s["matched"]) + len(s["missing"]), len(s["matched"]),
                 len(s["missing"]), s["missing"][:10]))
        if s["not_on_sheet"]:
            print("      Tableau zips not on the tab (%d): %s"
                  % (len(s["not_on_sheet"]), s["not_on_sheet"][:15]))
        for w in writes[:6]:
            print("      %s <- %r" % (w["range"], w["values"][0][0]))
        if dry_run:
            print("      (dry run: %d cells not written)" % len(writes))
            continue
        q = "'%s'!" % title.replace("'", "''")
        ws.spreadsheet.values_batch_update(
            {"valueInputOption": "USER_ENTERED",
             "data": [{"range": q + w["range"], "values": w["values"]} for w in writes]})
        meta = sh.fetch_sheet_metadata(params={"fields": "sheets(properties(sheetId),conditionalFormats)"})
        existing = next((x.get("conditionalFormats", []) for x in meta["sheets"]
                         if x["properties"]["sheetId"] == ws.id), [])
        color_to = s["total_row"] if s["total_row"] is not None else s["last_row"]
        reqs = core.cf_requests(ws.id, lay, color_to, existing)
        if reqs:
            sh.batch_update({"requests": reqs})
        print("      wrote %d cells + colors on rows %d-%d" % (len(writes), s["first_row"] + 1,
                                                              s["last_row"] + 1))
    return ok


def fill_block(o: dict, data: dict, dry_run: bool) -> bool:
    """Lucy's own block on an owner's Line Up (block.py). Writes ONLY inside the
    block's columns, then re-reads the tab and checks every other cell's
    formula/value is exactly what it was before."""
    from automations.recruiting_report.fill import open_by_key
    from automations.fiber_zip_penetration import block
    import re
    who = o["owner"]
    sh = open_by_key(o["sheet"])
    if o.get("tab_regex"):
        meta = sh.fetch_sheet_metadata(params={"fields": "sheets(properties(title,index,hidden))"})
        props = sorted((s["properties"] for s in meta["sheets"]), key=lambda p: p["index"])
        hits = [p["title"] for p in props
                if not p.get("hidden") and re.match(o["tab_regex"], p["title"], re.I)]
        if not hits:
            print("  [%s] no tab matching %r -- skipped" % (who, o["tab_regex"]))
            return False
        tab = hits[0]
    else:
        tab = o["tab"]
    try:
        ws = sh.worksheet(tab)
    except Exception:  # noqa: BLE001 -- gspread WorksheetNotFound
        if not o.get("create_tab"):
            print("  [%s] tab %r not found -- skipped" % (who, tab))
            return False
        if dry_run:
            print("  [%s] would copy the molde's Line Up as %r, then add %d zips"
                  % (who, tab, len(data)))
            return True
        # Same format for everyone: copy the molde's Line Up (never a blank tab).
        src = open_by_key(config.TEMPLATE_SHEET).worksheet(config.TEMPLATE_LINEUP_TAB)
        new_id = src.copy_to(o["sheet"])["sheetId"]
        sh = open_by_key(o["sheet"])
        ws = next(w for w in sh.worksheets() if w.id == new_id)
        ws.update_title(tab)
        print("  [%s] copied the molde's Line Up into %r" % (who, tab))
    values = ws.get_all_values()
    formulas = ws.get_all_values(value_render_option="FORMULA")
    spot = block.place(values, formulas, who)
    col, old = spot["col"], spot["old_col"]
    moving = old is not None and old != col
    old_cols = range(old, old + spot["old_width"]) if moving else range(0)
    old_rows = spot["old_rows"] if old == col else 0
    g, total = block.grid(who, data, col, old_rows)
    print("  [%s] '%s': block at %s, %d zips, Total on row %d%s"
          % (who, tab, block.a1(0, col), len(data), total + 1,
             " (NEW)" if old is None else
             " (moved from %s)" % block.a1(0, old) if moving else ""))
    if dry_run:
        for r in g[:4]:
            print("      ", r)
        return True
    need_cols, need_rows = col + block.WIDTH, len(g)
    if ws.col_count < need_cols:
        ws.add_cols(need_cols - ws.col_count)          # appended at the far right
    if ws.row_count < need_rows:
        ws.add_rows(need_rows - ws.row_count)          # appended at the bottom
    meta = sh.fetch_sheet_metadata(params={"fields": "sheets(properties(sheetId),conditionalFormats)"})
    existing = next((x.get("conditionalFormats", []) for x in meta["sheets"]
                     if x["properties"]["sheetId"] == ws.id), [])
    # Color rules on the old spot and the new one go first (one pass, highest
    # index first), then the old spot is wiped if the block moves.
    span = range(min(col, old if moving else col),
                 max(col + block.WIDTH, old_cols.stop if moving else 0))
    pre = block.cf_delete_requests(ws.id, existing, span)
    if moving:
        pre += block.clear_requests(ws.id, old, spot["old_width"], spot["old_rows"])
    if pre:
        sh.batch_update({"requests": pre})
    q = "'%s'!" % tab.replace("'", "''")
    sh.values_batch_update({"valueInputOption": "USER_ENTERED", "data": [
        {"range": q + block.a1(0, col), "values": g}]})
    lay = {"header_row": 1, "cols": {"pct": col + block.PCT_OFFSET}}
    reqs = (block.format_requests(ws.id, col, total, old_rows)
            + core.cf_requests(ws.id, lay, total - 1, []))
    sh.batch_update({"requests": reqs})
    # Safety check: nothing outside the block (old + new spot) moved.
    after_f = ws.get_all_values(value_render_option="FORMULA")
    after_v = ws.get_all_values()
    bad = block.outside_changed(formulas, after_f, col, old_cols)
    if bad:
        print("  [%s] !! formulas changed OUTSIDE the block: %s" % (who, bad[:10]))
        return False
    vbad = block.outside_changed(values, after_v, col, old_cols)
    print("      wrote %d rows; outside the block: formulas identical, %d value changes%s"
          % (len(g), len(vbad), (" %s" % vbad[:5]) if vbad else ""))
    return not vbad


MIN_OWNERS = 20


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="fiber_zip_penetration")
    ap.add_argument("--csv", help="Use this crosstab file instead of pulling Tableau.")
    ap.add_argument("--owner", help="Only this owner (Tableau spelling).")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--date", help="Pretend today is YYYY-MM-DD (picks the tab).")
    args = ap.parse_args(argv)

    today = dt.date.fromisoformat(args.date) if args.date else dt.datetime.now(CENTRAL).date()
    print("=== Fiber zip penetration -> Line Up -- %s -- %s ==="
          % (today, "DRY-RUN" if args.dry_run else "LIVE"))
    if not args.dry_run:
        _manifest(False, "run started but did not complete")

    if args.csv:
        text = core.decode(Path(args.csv))
    else:
        from automations.int_wow_penetration import pull
        from automations.shared.tableau_patchright import download_crosstab_patchright
        with tempfile.TemporaryDirectory(prefix="fiber_zip_") as tmp:
            p = download_crosstab_patchright(config.VIEW_URL, pull.WORKSHEET,
                                             Path(tmp) / "fiber_by_zip.csv")
            text = core.decode(p)
    by_owner = core.parse_zips(text)
    print("  crosstab: %d owners" % len(by_owner))
    if len(by_owner) < MIN_OWNERS:
        # 11/23 on Lucy 2 the download came back with ONE owner (a remembered
        # owner filter in that Tableau session). Writing from it would blank
        # nobody but skip everyone -- fail loudly instead, write nothing.
        print("  !! only %d owner(s) in the crosstab (expected ~60+) -- a Tableau "
              "filter is stuck; nothing written" % len(by_owner))
        return 1

    owners = [o for o in config.OWNERS if not args.owner or o["owner"] == args.owner]
    bad = []
    for o in owners:
        data = by_owner.get(o["owner"])
        if not data:
            print("  [%s] not in the crosstab -- skipped" % o["owner"])
            bad.append(o["owner"])
            continue
        try:
            if not fill_owner(o["owner"], o["sheet"], data, today, args.dry_run):
                bad.append(o["owner"])
        except Exception as e:  # noqa: BLE001 -- one owner never blocks the rest
            print("  [%s] FAILED: %s" % (o["owner"], e))
            bad.append(o["owner"])

    blocks = [o for o in config.BLOCKS if not args.owner or o["owner"] == args.owner]
    for o in blocks:
        data = by_owner.get(o["owner"])
        if not data:
            print("  [%s] not in the crosstab -- skipped" % o["owner"])
            bad.append(o["owner"])
            continue
        try:
            if not fill_block(o, data, args.dry_run):
                bad.append(o["owner"])
        except Exception as e:  # noqa: BLE001
            print("  [%s] FAILED: %s" % (o["owner"], e))
            bad.append(o["owner"])

    if bad:
        print("\nNOT filled: %s" % ", ".join(bad))
        return 1
    if not args.dry_run:
        _manifest(True)
    print("\n=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
