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
        reqs = core.cf_requests(ws.id, lay, s["last_row"], existing)
        if reqs:
            sh.batch_update({"requests": reqs})
        print("      wrote %d cells + colors on rows %d-%d" % (len(writes), s["first_row"] + 1,
                                                              s["last_row"] + 1))
    return ok


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
        with tempfile.TemporaryDirectory(prefix="fiber_zip_") as tmp:
            p = pull.fetch_crosstab(Path(tmp) / "fiber_by_zip.csv")
            text = core.decode(p)
    by_owner = core.parse_zips(text)
    print("  crosstab: %d owners" % len(by_owner))

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

    if bad:
        print("\nNOT filled: %s" % ", ".join(bad))
        return 1
    if not args.dry_run:
        _manifest(True)
    print("\n=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
