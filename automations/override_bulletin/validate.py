"""Lucy-1 validation for the confirmed pulls (DD + NETSUITE).

Downloads ORG DD Detail + Transaction Details, parses, and writes the results to
a `_validate_out` tab so the fetch + parse + column-name matching can be checked
against real data (and cross-checked to the override sheet). Read-only w.r.t. any
real report tab. RUN ON LUCY 1.
"""
from __future__ import annotations

import sys
from pathlib import Path

WORKBOOK_ID = "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E"
OUT = Path("output/override_bulletin/validate")
TAB = "_validate_out"


def main(argv=None) -> int:
    from automations.shared.tableau_patchright import tableau_session
    from automations.override_bulletin.pulls import dd_captain_overrides, ledger_amounts
    from automations.recruiting_report import fill as _fill
    OUT.mkdir(parents=True, exist_ok=True)
    dump = []

    def section(title, d, n=20):
        dump.append([title, ""])
        for k, v in sorted(d.items(), key=lambda kv: -abs(kv[1]))[:n]:
            dump.append([str(k)[:40], v])
        dump.append(["", ""])

    with tableau_session(headless=True, verbose=True) as page:
        # DD captain overrides — sheet week 7.12 == DD week 7/11
        try:
            dd = dd_captain_overrides("7/11/2026", OUT / "dd.csv", page=page, verbose=True)
            print(f"DD captain overrides (7/11): {dd}", flush=True)
            section("DD CAPTAIN OVERRIDES 7/11 (expect Carlos~10875, Colten~10236, "
                    "Khalil~4865, Jairo~6534, Eveliz~3116)", dd)
        except Exception as e:  # noqa: BLE001
            print(f"DD FAILED: {type(e).__name__}: {e}", flush=True)
            dump.append(["DD FAILED", f"{type(e).__name__}: {str(e)[:80]}"])
        # Ledger — special + credico (broad needles to confirm the parse works)
        for needle in ("Special Override", "Credico"):
            try:
                led = ledger_amounts(needle, OUT / f"led_{needle}.csv", page=page, verbose=True)
                print(f"LEDGER {needle}: {len(led)} owners", flush=True)
                section(f"LEDGER '{needle}' ({len(led)} owners)", led, 15)
            except Exception as e:  # noqa: BLE001
                print(f"LEDGER {needle} FAILED: {type(e).__name__}: {e}", flush=True)
                dump.append([f"LEDGER {needle} FAILED", f"{type(e).__name__}: {str(e)[:80]}"])

    try:
        wb = _fill._client().open_by_key(WORKBOOK_ID)
        try:
            ws = wb.worksheet(TAB)
            ws.clear()
        except Exception:  # noqa: BLE001
            ws = wb.add_worksheet(title=TAB, rows=max(200, len(dump) + 10), cols=4)
        ws.update([[str(c) for c in row] for row in dump], "A1", value_input_option="RAW")
        print(f"wrote {len(dump)} rows to {TAB!r}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"couldn't write {TAB}: {type(e).__name__}: {e}", flush=True)
    print("validate done.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
