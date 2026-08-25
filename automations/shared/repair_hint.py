"""A metric module telling the runner ABOVE it exactly which piece dropped.

WHY (Megan 2026-08-25). A runner like `daily_metrics` launches each metric as a
subprocess and only sees its exit code, so when a metric fails the only fix it
can suggest is "re-run the whole metric". For churn that means re-posting all 8
images into the Metrics thread — even when 7 of them are already there. On
2026-08-25 one flaky Slack upload dropped ONE image at 04:42; the repair
re-posted the set twice and left 16 duplicate charts in #alphalete-sales.

The module DOES know which piece dropped. This is the one-file channel for it to
say so: the module writes a hint, the runner reads it and turns it into a scoped
repair command (churn's `--only <report> --only-period <p>` hatch) instead of the
blunt whole-metric re-run.

Contract:
  * The hint is DATE-STAMPED and only ever read back on the same day — a repair
    command for yesterday's miss would re-post into yesterday's thread.
  * A module that posts CLEARS its hint at the start of every run, so the file
    always describes the run that just happened and never a stale one. A module
    that dies before it posts therefore leaves NO hint, and the runner falls back
    to the whole-metric re-run — which is right: the problem wasn't a post.
  * `module_args` is set only when the miss is expressible as ONE scoped command.
    None means "re-run the metric normally"; `missed` still names the pieces so
    the alert can say what's gone.

Every function is best-effort: a hint that can't be written or read must never
change what the run does.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Optional, Sequence

_REPO = Path(__file__).resolve().parents[2]
HINT_DIR = _REPO / "output" / "state" / "repair_hints"


def _path(slug: str) -> Path:
    safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in slug)
    return HINT_DIR / f"{safe}.json"


def write(slug: str, *, missed: Sequence[str], module_args: Optional[str] = None,
          day: Optional[dt.date] = None) -> Optional[Path]:
    """Record which pieces of `slug` did NOT land, and (when it's a single
    scoped command) the module args that re-do exactly those."""
    try:
        HINT_DIR.mkdir(parents=True, exist_ok=True)
        p = _path(slug)
        p.write_text(json.dumps({
            "slug": slug,
            "date": (day or dt.date.today()).isoformat(),
            "missed": list(missed),
            "module_args": module_args,
        }, indent=2), encoding="utf-8")
        return p
    except OSError:
        return None


def clear(slug: str) -> None:
    """Forget any hint for `slug`. Called at the START of a run that posts, so a
    hint can never outlive the run it describes."""
    try:
        _path(slug).unlink()
    except OSError:
        pass


def read(slug: str, *, day: Optional[dt.date] = None) -> Optional[dict]:
    """Today's hint for `slug`, or None (missing / unreadable / not from today)."""
    try:
        raw = json.loads(_path(slug).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    if raw.get("date") != (day or dt.date.today()).isoformat():
        return None
    return raw
