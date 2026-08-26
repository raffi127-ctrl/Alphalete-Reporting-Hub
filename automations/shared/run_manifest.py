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
                   run_ts: Optional[_dt.datetime] = None,
                   alert: bool = True,
                   alert_after: Optional[str] = None,
                   dry_run: bool = False) -> Path:
    """Record this run's outcome for `report_id`:
      - `failed` + `retry_args`: the parts that failed and the CLI args that
        re-run ONLY those (powers the Hub's 'Retry failed only' button).
      - `succeeded`: the parts that DID land. Optional, but passing it is what
        lets `outcome()` tell a PARTIAL run (some parts landed) from a total
        failure — the Hub colours those differently (orange vs red).
      - `remediation`: an optional {reason, fix, link, message} block explaining
        WHY it failed + how to fix it (powers the Hub's failure-help callout).
      - `alert=False`: write the manifest WITHOUT the loud Slack ping. The one
        legitimate use is a START-OF-RUN SEED (see below) — never a real failure.
      - `alert_after`: ISO local datetime. "A SCHEDULED later pass is expected to
        fix this — stay quiet until then." The manifest still records the miss
        (orange Hub card, retry button, auto-retry) but nobody is pinged before
        that clock. For a report whose own design defers work — b2b_metrics holds
        the order-log sections until the ORDERLOG extract lands and its 8:30 floor
        pass posts them — the early miss is EXPECTED, and alerting on it sends Eve
        to re-check something that fixes itself an hour later (Eve 2026-08-13).
        Past the clock the miss is real and alerts exactly as before.
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
        "alert_after": alert_after,
    }
    p = _path(report_id)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # LOUD Slack alert on a silent drop. A 4am-flow report exits 0 "with a note"
    # so the orchestrator never fires its own failure alert — on 2026-08-07 every
    # office quietly dropped its ABP card and nobody knew for hours. Ping
    # #claudecorrections (@Megan) straight from here so ANY recorded failure is
    # heard immediately, not found on an orange Hub card later. run_ts is set only
    # by tests / deterministic callers, so they never alert; dedup + try/except so
    # it can neither spam nor break the manifest write.
    #
    # alert=False is for a START-OF-RUN SEED: several reports (captainship
    # activations, financial, int wow, recruiter retention) write an ok=false
    # manifest BEFORE doing any work, purely so a mid-run crash can't leave a
    # stale clean state that re-verifies to DONE. That seed names a fake failed
    # part, so it fired this alarm on every single healthy run — a 6am "it did
    # NOT post" ping for a report that then finished fine (2026-08-09). A crash
    # after the seed still exits non-zero, so the orchestrator's own failure
    # alert covers it; the loud ping stays for REAL recorded failures only.
    if failed and run_ts is None and alert and not alert_held(data):
        try:
            from automations.shared import section_drop_alert as _sda
            # Forward `kind` so a caller can pick the wording (see _KINDS).
            # The manifest vocabulary ('part', 'step', …) and the alert's
            # ('section', 'day', 'source') overlap only where a caller means
            # them to: _KINDS falls back to 'section' for anything it doesn't
            # recognise, so every existing caller reads exactly as before.
            _sda.alert(report_id=report_id, failed=failed,
                       remediation=remediation, note=note, kind=kind,
                       dry_run=dry_run)
        except Exception:  # noqa: BLE001 — the alarm must never break the writer
            pass
    # The mirror image: a run with nothing failed CLOSES whatever alert thread
    # this report left open, with a "resolved" note in that same thread (Eve
    # 2026-08-14). Costs a local index read when there's nothing open, which is
    # the normal case. Seed writes (alert=False) and tests (run_ts) stay silent.
    #
    # dry_run stays silent too (Megan 2026-08-26). This function had no dry_run
    # at all, so a REHEARSAL that wrote a manifest posted a live "RESOLVED — it
    # just ran clean" into a real incident thread and closed a ticket nobody had
    # fixed. A dry run may write its manifest; it may not speak in the channel.
    elif not failed and run_ts is None and alert and ok is not False:
        try:
            from automations.shared import section_drop_alert as _sda
            _sda.resolved(report_id, dry_run=dry_run)
        except Exception:  # noqa: BLE001
            pass
    return p


def alert_held(manifest: Optional[dict],
               now: Optional[_dt.datetime] = None) -> bool:
    """True while this manifest's `alert_after` clock hasn't passed — i.e. the
    report itself says "a scheduled later pass is expected to fix this, don't
    page anyone yet".

    Deliberately fails OPEN: a missing/unparseable/past clock means alert as
    normal, so a typo can never silence a real failure. Shared by write_manifest
    (the loud section-drop ping) and the orchestrator's failure alert, so BOTH
    voices honour the same hold — otherwise silencing one just moves the noise."""
    if not isinstance(manifest, dict):
        return False
    raw = manifest.get("alert_after")
    if not raw:
        return False
    try:
        return (now or _dt.datetime.now()) < _dt.datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return False


def alert_held_for(report_id: str, now: Optional[_dt.datetime] = None) -> bool:
    """alert_held() for a report's CURRENT manifest (the orchestrator's entry
    point — it holds a ReportState, not the manifest dict)."""
    return alert_held(read_manifest(report_id), now)


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


def retry_whole_spec(report_id: str) -> Optional[dict]:
    """Sibling of retry_spec for a WHOLE-PHASE drop that carries no scoped
    retry_args because the report takes no CLI args and can only be recovered by
    re-running the ENTIRE report — e.g. daily_rep_breakdown's Phase 2 (ownerville
    scrape) or Phase 3 (Tableau) collapsing on a session drop / timeout. A full
    re-run is CHEAP here: the report resumes from its own checkpoint, so finished
    units aren't redone (base_args=[] → args_override=[] reproduces the normal run).

    Returns a spec (retry_args=[], whole=True) ONLY for a not-ok manifest whose
    kind=='phase' with named failed part(s). Deliberately returns None for
    kind=='owner' — those are named-owner stragglers that daily.py already retried
    internally and that want the surgical `lucy focus_owner "A" "B"`, NOT a whole
    ~90m re-run. This is the auto-retry path retry_spec can't offer: retry_spec
    needs non-empty retry_args, so a phase collapse (retry_args=[]) fell through
    and the report never got the orchestrator's 2× auto-retry (Megan 2026-08-10)."""
    m = read_manifest(report_id)
    if not m or m.get("ok"):
        return None
    failed = m.get("failed") or []
    if not failed or m.get("kind") != "phase":
        return None
    return {"failed": failed, "retry_args": [], "kind": "phase",
            "run_ts": m.get("run_ts"), "whole": True}


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
