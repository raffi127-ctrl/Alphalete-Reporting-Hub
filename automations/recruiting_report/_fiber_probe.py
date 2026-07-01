"""One-off probe: does the Fiber BULK pull still work, or is it silently
falling back to the ~25-min legacy per-ICD loop?

download_fiber() catches a bulk failure and runs the slow legacy path, so a
broken bulk view is invisible in a normal run except for a mid-log line the
mini's 3-line status tail drops. This probe calls the BULK path DIRECTLY (never
the legacy fallback), so it's fast either way (~10s if OK, quick fail if the
AUTOMATIONPULL-NICHURNVIEW view is gone), and prints a decisive LAST line the
tail will capture.

    lucy rerun fiber_probe    # verdict lands in `lucy status`

Temporary — safe to delete after confirming.
"""
from __future__ import annotations

from pathlib import Path

from automations.recruiting_report import opt_phase


def main() -> int:
    # A couple of real ICD tabs is plenty — the bulk path downloads the whole
    # crosstab regardless; icd_names only drives post-download owner matching.
    try:
        from automations.recruiting_report import fill
        confirmed = fill.load_mapping().get("confirmed", [])
        icds = [c["sheet_tab"] for c in confirmed[:3]] or ["Marcellus Butler"]
    except Exception:
        icds = ["Marcellus Butler"]

    out = Path("output") / "_fiber_probe.csv"
    try:
        opt_phase._download_fiber_bulk(icds, out, logfn=print)
    except Exception as e:  # noqa: BLE001 — the whole point is to report failure
        print(f"FIBER PROBE VERDICT: ❌ BULK path BROKEN — {type(e).__name__}: "
              f"{str(e)[:160]} (a normal run would silently fall back to the "
              f"~25-min legacy loop)")
        return 1

    rows = 0
    if out.exists():
        with open(out, encoding="utf-8") as f:
            rows = max(0, sum(1 for _ in f) - 1)  # minus header
    print(f"FIBER PROBE VERDICT: ✓ BULK path OK (fast) — wrote {rows} ICD row(s) "
          f"from {opt_phase.FIBER_BULK_CROSSTAB_SHEET!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
