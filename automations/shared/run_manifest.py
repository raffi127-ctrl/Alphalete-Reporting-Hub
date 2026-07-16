"""Standard per-report failure manifest for the Hub's "re-run only the failed
part" feature.

Every report writes ONE manifest per run (overwrite) describing what failed and
— crucially — the EXACT CLI args that re-run only those failed parts. The Hub
stays generic: it reads the manifest and runs the card's module with
`retry_args`, with no per-report knowledge. The report owns the smarts (it
already has the partial-rerun flags: --only / --step / --retry-inaccessible /
--skip-download); the manifest just records which to use and on what.

Schema (output/manifests/<report_id>.json):
  {
    "report_id": "recruiting",
    "run_ts":    "2026-06-10T08:07:00",   # ISO, naive local
    "ok":        false,                    # run fully succeeded (nothing failed)
    "kind":      "ICD",                    # unit label: ICD/owner/section/captainship/step
    "failed":    ["Tevin Sterling", ...],  # failed unit names (for display)
    "retry_args":["--retry-inaccessible"], # args to re-run ONLY the failed parts
    "note":      "2 ICDs inaccessible"     # optional human note
  }

A fully-successful run calls mark_clean() so `ok=true, failed=[]` and the Hub
hides the retry button. Reads are tolerant — a missing/corrupt file returns None
so the Hub never crashes on it.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import List, Optional

_REPO = Path(__file__).resolve().parents[2]
MANIFEST_DIR = _REPO / "output" / "manifests"


def _path(report_id: str) -> Path:
    safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in report_id)
    return MANIFEST_DIR / f"{safe}.json"


def make_remediation(*, reason: str, fix: str, link: str = "",
                     message: str = "") -> dict:
    """Build a remediation block for write_manifest(remediation=...).
      reason  : plain-English WHY the run failed
      fix     : WHAT to do to correct it
      link    : (optional) the exact Tableau view / dashboard with the missing
                info, when it's a Tableau issue
      message : (optional) a neutral, copy-paste message describing the problem,
                ready to send to whoever can fix it (shown with a Copy button)."""
    return {"reason": reason, "fix": fix, "link": link, "message": message}


def write_manifest(report_id: str, *, failed: List[str] = (),
                   retry_args: List[str] = (), kind: str = "part",
                   note: str = "", remediation: Optional[dict] = None,
                   ok: Optional[bool] = None, succeeded: List[str] = (),
                   run_ts: Optional[_dt.datetime] = None) -> Path:
    """Record this run's outcome for `report_id`:
      - `failed` + `retry_args`: the parts that failed and the CLI args that
        re-run ONLY those (powers the Hub's 'Retry failed only' button).
      - `succeeded`: the parts that DID land. Optional, but passing it is what
        lets `outcome()` tell a PARTIAL run (some parts landed) from a total
        failure — the Hub colours those differently (orange vs red).
      - `remediation`: an optional {reason, fix, link, message} block explaining
        WHY it failed + how to fix it (powers the Hub's failure-help callout).
    `ok` defaults to True only when nothing failed AND there's no remediation.
    Pass run_ts to avoid clock calls in tests."""
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    ts = (run_ts or _dt.datetime.now()).isoformat(timespec="seconds")
    failed = list(failed)
    if ok is None:
        ok = (not failed) and (remediation is None)
    data = {
        "report_id": report_id,
        "run_ts": ts,
        "ok": ok,
        "kind": kind,
        "failed": failed,
        "succeeded": list(succeeded),
        "retry_args": list(retry_args),
        "note": note,
        "remediation": remediation,
    }
    p = _path(report_id)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


def mark_clean(report_id: str, *, kind: str = "part",
               run_ts: Optional[_dt.datetime] = None) -> Path:
    """Record a fully-successful run (nothing failed). Clears any prior failure
    manifest so the Hub's retry button disappears."""
    return write_manifest(report_id, failed=[], retry_args=[], kind=kind,
                          note="", run_ts=run_ts)


def outcome(report_id: str, *, today_only: bool = True) -> Optional[str]:
    """'success' | 'partial' | 'failed' from this report's last manifest, or None.

    PARTIAL = some parts failed but others landed (e.g. the trackers posted to 4
    of 5 Slack channels). The Hub colours that ORANGE, not red: a red pill next
    to a report that mostly worked trains people to ignore red. Needs the run to
    pass `succeeded` — without it a failed run can't be told from a partial one,
    so it reads as 'failed' (the safe direction: never green).

    today_only (default) ignores a stale manifest from an earlier day, so
    yesterday's failure can't colour today's pill."""
    m = read_manifest(report_id)
    if not m:
        return None
    if today_only:
        try:
            if (m.get("run_ts") or "")[:10] != _dt.date.today().isoformat():
                return None
        except Exception:
            return None
    if m.get("ok"):
        return "success"
    return "partial" if (m.get("succeeded") and m.get("failed")) else "failed"


def read_manifest(report_id: str) -> Optional[dict]:
    """Return the manifest dict, or None if missing/unreadable."""
    p = _path(report_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def retry_spec(report_id: str) -> Optional[dict]:
    """Hub helper: return {failed, retry_args, kind, run_ts} ONLY when there's
    something to retry (manifest exists, not ok, has failed parts + retry args).
    Returns None otherwise — so the Hub shows the 'Retry failed only' button
    exactly when it's actionable."""
    m = read_manifest(report_id)
    if not m or m.get("ok"):
        return None
    failed = m.get("failed") or []
    retry_args = m.get("retry_args") or []
    if not failed or not retry_args:
        return None
    return {"failed": failed, "retry_args": retry_args,
            "kind": m.get("kind", "part"), "run_ts": m.get("run_ts")}


def failure_remediation(report_id: str) -> Optional[dict]:
    """Hub helper: the report-provided {reason, fix, link, message} remediation
    block for the last (failed) run, or None when the run was ok or wrote no
    remediation. The Hub prefers this over its generic log-signature guess
    because the report knows its own source + the exact link."""
    m = read_manifest(report_id)
    if not m or m.get("ok"):
        return None
    rem = m.get("remediation")
    return rem if isinstance(rem, dict) and (rem.get("reason") or rem.get("fix")) else None
