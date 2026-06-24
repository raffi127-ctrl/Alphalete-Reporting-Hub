"""Self-service scheduler onboarding (standing feature).

When someone (Mod/Eve) pushes a NEW automation to the hub, this:
  1. DETECTS it — an automations/<module>/run.py with no schedule_config entry,
     and/or a new row in uploaded_reports.json.
  2. AUTO-ANALYZES its source type by static scan (Tableau / AppStream / upload /
     API), so we can tell the user whether the readiness gate + circle-back
     ("redo until the data's ready") applies.
  3. PROMPTS for the human-only decisions — run on a scheduler? cadence?
     priority tier? freshness target? — via the hub UI or an email prompt.
  4. WRITES one entry into schedule_config.json (the editable knobs).

This module owns detection + analysis + config-write (pure, testable). The
prompt delivery (Streamlit form vs email) calls in here. Detection is automatic;
the schedule/priority calls are human input.

  python -m automations.day_orchestrator.onboarding --scan          # list unregistered
  python -m automations.day_orchestrator.onboarding --analyze MODULE # show detected type
  python -m automations.day_orchestrator.onboarding --register MODULE --cadence ... --priority P2 [...]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from automations.day_orchestrator.registry import CONFIG_PATH

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTOMATIONS_DIR = REPO_ROOT / "automations"
UPLOADED_REPORTS = REPO_ROOT / "uploaded_reports.json"

# Don't treat these as schedulable report modules.
_SKIP_MODULES = {"day_orchestrator", "shared", "dashboard", "uploaded", "__pycache__"}


@dataclass
class Analysis:
    module: str
    source_type: str          # tableau | appstream | api | upload | unknown
    readiness_applies: bool
    signals: List[str]
    has_dry_run: bool


# ---------------- detection ----------------

def registered_ids() -> set:
    try:
        raw = json.loads(CONFIG_PATH.read_text())
    except Exception:
        return set()
    ids = set(raw.get("reports", {}).keys())
    # A report can be registered under a different id than its module; also map
    # by command module so we don't re-flag an already-wired one.
    for r in raw.get("reports", {}).values():
        cmd = r.get("command", [])
        if cmd:
            ids.add(cmd[0].split(".")[1] if cmd[0].startswith("automations.") else cmd[0])
    for section in ("read_only_standalone", "excluded"):
        ids |= set(raw.get(section, {}).keys())
    return ids


def candidate_modules() -> List[str]:
    """automations/<module>/ dirs that have a run.py (a runnable report)."""
    out = []
    for child in sorted(AUTOMATIONS_DIR.iterdir()):
        if not child.is_dir() or child.name in _SKIP_MODULES:
            continue
        if (child / "run.py").exists():
            out.append(child.name)
    return out


def unregistered_modules() -> List[str]:
    reg = registered_ids()
    return [m for m in candidate_modules() if m not in reg]


# ---------------- static source-type analysis ----------------

_TABLEAU_PAT = re.compile(
    r"tableau_patchright|download_crosstab|drive_crosstab|tableau_session|"
    r"scrape_view_data|crosstab_sheet|ownerville_session|public\.tableau|"
    r"tableau\.com", re.I)
_APPSTREAM_PAT = re.compile(r"appstream|applicantstream|appstream_session|rcaptain", re.I)
_UPLOAD_PAT = re.compile(r"automations[\\/]uploaded|uploaded[\\/].*\.(xlsx|pdf|csv)|--dir\b", re.I)
_API_PAT = re.compile(r"open-meteo|open_meteo|serpapi|places\.googleapis|requests\.(get|post)", re.I)


def analyze(module: str) -> Analysis:
    """Scan a module's .py files for source-type signals. Tableau wins if present
    (it's the one that needs the readiness/redo machinery)."""
    pkg = AUTOMATIONS_DIR / module
    text = []
    for py in pkg.rglob("*.py"):
        try:
            text.append(py.read_text(errors="ignore"))
        except Exception:
            continue
    blob = "\n".join(text)
    signals: List[str] = []

    is_tableau = bool(_TABLEAU_PAT.search(blob))
    is_appstream = bool(_APPSTREAM_PAT.search(blob))
    is_upload = bool(_UPLOAD_PAT.search(blob))
    is_api = bool(_API_PAT.search(blob))
    has_dry_run = "--dry-run" in blob or "dry_run" in blob

    if is_tableau:
        signals.append("Tableau pull (patchright crosstab / ownerville SSO)")
    if is_appstream:
        signals.append("AppStream session")
    if is_upload:
        signals.append("reads an uploaded file")
    if is_api:
        signals.append("external HTTP/API calls")

    # Priority of classification: Tableau (needs gate) > upload > appstream > api.
    if is_tableau:
        stype, readiness = "tableau", True
    elif is_upload:
        stype, readiness = "upload", False
    elif is_appstream:
        stype, readiness = "appstream", False
    elif is_api:
        stype, readiness = "api", False
    else:
        stype, readiness = "unknown", False

    return Analysis(module=module, source_type=stype, readiness_applies=readiness,
                    signals=signals or ["no clear source signals found"],
                    has_dry_run=has_dry_run)


def explain(a: Analysis) -> str:
    """Human sentence telling the user what was detected + whether redo applies."""
    if a.source_type == "tableau":
        return ("Detected a TABLEAU report → the readiness gate + circle-back "
                "(\"redo until the data's ready\") WILL apply. Signals: "
                + "; ".join(a.signals))
    if a.source_type == "appstream":
        return ("Detected an APPSTREAM report → no readiness probe (AppStream is "
                "always current); runs immediately when scheduled. Signals: "
                + "; ".join(a.signals))
    if a.source_type == "upload":
        return ("Detected an UPLOAD-gated report → stays MANUAL (never auto-run; "
                "only noted as pending upload). Signals: " + "; ".join(a.signals))
    if a.source_type == "api":
        return ("Detected a pure-API report → always ready, runs at its slot. "
                "Signals: " + "; ".join(a.signals))
    return ("Could not classify the source type from the code — set source_type "
            "by hand in schedule_config.json. Signals: " + "; ".join(a.signals))


# ---------------- config registration ----------------

def register(module: str, *, on_scheduler: bool, weekdays: List[int],
             not_before: Optional[str], priority: str,
             freshness_target: Optional[str], display_name: Optional[str] = None,
             command: Optional[List[str]] = None,
             report_id: Optional[str] = None) -> dict:
    """Append/overwrite one entry in schedule_config.json. Returns the entry.
    source_type + data_sources come from analysis (data_sources left empty for a
    human to map to a known source id, or a NEW source stub is added)."""
    a = analyze(module)
    rid = report_id or module
    raw = json.loads(CONFIG_PATH.read_text())

    entry = {
        "on_scheduler": on_scheduler,
        "display_name": display_name or module.replace("_", " ").title(),
        "source_type": a.source_type if a.source_type != "unknown" else "tableau",
        "data_sources": [],
        "command": command or [f"automations.{module}.run"],
        "base_args": [],
        "cadence": {"weekdays": weekdays, **({"not_before": not_before} if not_before else {})},
        "priority": priority,
        "freshness_target": freshness_target,
        "depends_on": [],
        "verify": {"type": "not_configured", "_todo": "set sheet/tab/anchor_label or manifest"},
        "_onboarded": True,
        "_detected": {"source_type": a.source_type, "signals": a.signals,
                      "readiness_applies": a.readiness_applies},
    }
    raw.setdefault("reports", {})[rid] = entry
    _atomic_write_json(CONFIG_PATH, raw)
    return entry


def _atomic_write_json(path: Path, obj: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(obj, indent=2))
    tmp.replace(path)


# ---------------- CLI ----------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Scheduler onboarding for new automations.")
    ap.add_argument("--scan", action="store_true", help="list unregistered runnable modules")
    ap.add_argument("--analyze", metavar="MODULE", help="show detected source type")
    ap.add_argument("--register", metavar="MODULE", help="write a schedule_config entry")
    ap.add_argument("--no-scheduler", action="store_true", help="register but on_scheduler=false")
    ap.add_argument("--weekdays", default="0,1,2,3,4,5,6", help="Mon=0..Sun=6 (default daily)")
    ap.add_argument("--not-before")
    ap.add_argument("--priority", default="P2", choices=["P1", "P2", "P3"])
    ap.add_argument("--freshness-target", default=None)
    ap.add_argument("--display-name")
    args = ap.parse_args(argv)

    if args.scan:
        un = unregistered_modules()
        if not un:
            print("All runnable modules are registered (or excluded).")
        else:
            print("Unregistered runnable automations:")
            for m in un:
                a = analyze(m)
                print(f"  {m:24s} → {a.source_type} (readiness "
                      f"{'applies' if a.readiness_applies else 'n/a'})")
        return 0

    if args.analyze:
        a = analyze(args.analyze)
        print(f"Module: {a.module}")
        print(explain(a))
        print(f"Accepts --dry-run: {'yes' if a.has_dry_run else 'no (check before scheduling)'}")
        return 0

    if args.register:
        weekdays = [int(x) for x in args.weekdays.split(",") if x.strip() != ""]
        a = analyze(args.register)
        print(explain(a))
        entry = register(
            args.register,
            on_scheduler=not args.no_scheduler,
            weekdays=weekdays,
            not_before=args.not_before,
            priority=args.priority,
            freshness_target=args.freshness_target,
            display_name=args.display_name,
        )
        print(f"\nRegistered {args.register} in schedule_config.json:")
        print(json.dumps(entry, indent=2))
        print("\nNEXT: map data_sources to a source id (or add a new source + probe), "
              "and wire `verify`, before live cutover.")
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
