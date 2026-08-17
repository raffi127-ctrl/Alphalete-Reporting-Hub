"""Build the harvest needs registry FROM the access ledger.

Megan 2026-08-17: the target is one 3am harvest that pulls everything every
report needs, after which no report touches Tableau. That requires a COMPLETE
list of needs — and the only complete, non-guessed source of that list is what
the reports actually pulled.

`automations/shared/tableau_ledger` records every real pull (report, view,
sheet, path). This module turns those recordings into a DataNeed registry:

    python -m automations.harvest.from_ledger --days 7            # coverage report
    python -m automations.harvest.from_ledger --days 7 --write    # generate needs_generated.py

Why generated and not hand-written: there are ~92 tableau reports across four
different pull paths, several of which build their view URL at runtime from
dates or env-injected owner views. Hand-declaring those is guesswork; the
ledger is what happened.

IMPORTANT — a week of ledger data is needed for full coverage. Daily reports
show up after one night; weekly ones only appear on the day they run. The
coverage report names which scheduled tableau reports have NOT been seen yet,
so it's obvious when the registry is complete.
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
from typing import Dict, List

from automations.shared import tableau_ledger

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATED = Path(__file__).with_name("needs_generated.py")

# Pull paths the 3am harvest can serve today. Anything else is recorded in the
# coverage report as NOT harvestable so it's a visible decision, not a silent gap.
HARVESTABLE_KINDS = {"crosstab", "viewdata"}

# A pre_export pull drives the export dialog with a callback (date fields etc.),
# so its URL+sheet do NOT determine the output — it can't be keyed or reused
# until the report is changed to put those params in the URL.
UNHARVESTABLE_EXTRA = "pre_export"


def collect(days: int = 7, end=None) -> Dict[str, dict]:
    """report_id -> {key: {view, sheet, kind, extra, count, harvestable}}."""
    recs = [r for r in tableau_ledger.load(days=days, end=end)
            if r.get("cache") != "hit"]
    out: Dict[str, dict] = {}
    for r in recs:
        rep = r.get("report") or "unknown"
        slot = out.setdefault(rep, {})
        k = r["key"]
        if k not in slot:
            slot[k] = {
                "view": r.get("view", ""),
                "sheet": r.get("sheet", ""),
                "kind": r.get("kind", ""),
                "count": 0,
                "harvestable": (r.get("kind") in HARVESTABLE_KINDS),
            }
        slot[k]["count"] += 1
    return out


def _scheduled_tableau_reports(target=None) -> List[str]:
    """Every report the orchestrator would run today with source_type tableau."""
    try:
        from automations.day_orchestrator import registry
        cfg = registry.load_config()
        target = target or dt.date.today()
        return [r.report_id for r in registry.scheduled_today(cfg, target, machine=None)
                if r.source_type == "tableau"]
    except Exception:
        return []


def _all_tableau_reports() -> List[str]:
    """Every tableau report the registry knows about. registry.Config.reports is
    a {report_id: Report} dict of dataclass-ish objects, not raw JSON."""
    from automations.day_orchestrator import registry
    cfg = registry.load_config()
    return sorted(rid for rid, r in cfg.reports.items()
                  if getattr(r, "source_type", None) == "tableau")


def coverage(days: int = 7, end=None) -> str:
    seen = collect(days=days, end=end)
    all_tab = _all_tableau_reports()
    lines = []
    total_pulls = sum(e["count"] for s in seen.values() for e in s.values())
    distinct = len({k for s in seen.values() for k in s})
    harvestable = len({k for s in seen.values() for k, e in s.items() if e["harvestable"]})

    lines.append(f"HARVEST COVERAGE — ledger last {days} day(s)")
    lines.append("=" * 72)
    lines.append(f"  reports seen pulling      : {len(seen)}")
    lines.append(f"  live pulls recorded       : {total_pulls}")
    lines.append(f"  distinct needs            : {distinct}")
    lines.append(f"  …harvestable at 3am       : {harvestable}")
    lines.append(f"  …NOT harvestable yet      : {distinct - harvestable}")
    lines.append("")

    unharv = [(rep, e) for rep, s in seen.items() for e in s.values()
              if not e["harvestable"]]
    if unharv:
        lines.append("NOT HARVESTABLE — these need a code change before they can "
                     "come off the live path")
        lines.append("-" * 72)
        for rep, e in sorted(unharv, key=lambda x: -x[1]["count"])[:25]:
            lines.append(f"  {rep[:26]:28s} {e['kind']:11s} "
                         f"{e['view'].rsplit('/views/', 1)[-1][:40]}")
        lines.append("")

    if not seen:
        lines.append("NO LEDGER DATA YET — nothing has run through an "
                     "instrumented pull path in this window.")
        lines.append(f"The registry cannot be generated until reports run. "
                     f"({len(all_tab)} tableau reports are waiting to be seen.)")
        return "\n".join(lines)

    missing = [r for r in all_tab if r not in seen]
    if missing:
        lines.append(f"NOT SEEN YET ({len(missing)} of {len(all_tab)} tableau reports) — "
                     f"they haven't run inside the ledger window.")
        lines.append("Weeklies need a full 7 days before the registry is complete.")
        lines.append("-" * 72)
        for i in range(0, len(missing), 3):
            lines.append("  " + "  ".join(f"{m[:22]:24s}" for m in missing[i:i + 3]))
    else:
        lines.append("Every scheduled tableau report has been seen — registry is complete.")
    return "\n".join(lines)


def render(days: int = 7, end=None) -> str:
    """Emit needs_generated.py source."""
    seen = collect(days=days, end=end)
    stamp = (end or dt.date.today()).isoformat()
    out = [
        '"""GENERATED — do not hand-edit.',
        "",
        f"Built by `python -m automations.harvest.from_ledger --days {days} --write`",
        f"from the Tableau access ledger through {stamp}.",
        "",
        "Each entry is a pull a report ACTUALLY made, so the 3am harvest can pull it",
        "once and every consumer reads the file instead of Tableau. Regenerate after",
        "adding a report or changing a view; the coverage report names what's missing.",
        '"""',
        "from __future__ import annotations",
        "",
        "from automations.harvest.needs import DataNeed",
        "",
        "REPORT_NEEDS_GENERATED = {",
    ]
    for rep in sorted(seen):
        entries = [e for e in seen[rep].values() if e["harvestable"]]
        if not entries:
            continue
        out.append(f"    {rep!r}: [")
        for e in sorted(entries, key=lambda x: -x["count"]):
            mode = "saved_view" if e["kind"] == "crosstab" else "view_data"
            label = f"{rep} — {e['view'].rsplit('/views/', 1)[-1][:40]}"
            out.append(f"        DataNeed(workbook={''!r}, view_url={e['view']!r},")
            out.append(f"                 crosstab_sheet={e['sheet']!r},")
            out.append(f"                 pull_mode={mode!r}, label={label!r}),")
        out.append("    ],")
    out.append("}")
    out.append("")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="harvest-from-ledger")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--date", help="end date YYYY-MM-DD (default today)")
    ap.add_argument("--write", action="store_true",
                    help=f"write {GENERATED.name}")
    a = ap.parse_args(argv)
    end = dt.date.fromisoformat(a.date) if a.date else None

    print(coverage(days=a.days, end=end))
    if a.write:
        src = render(days=a.days, end=end)
        GENERATED.write_text(src, encoding="utf-8")
        print(f"\nwrote {GENERATED.relative_to(REPO_ROOT)} "
              f"({len(src.splitlines())} lines)")
    else:
        print("\n(no --write — registry not regenerated)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
