"""Harvester — pull each unique Tableau view+filter-set ONCE over one login,
write to the dated cache with full provenance.

SHADOW-ONLY. Nothing on the live 4am path imports this. See README.md.

    from automations.harvest.harvester import harvest
    harvest(dt.date.today(), scheduled_data_needs(dt.date.today()))

Layout written:
    output/harvest/<YYYY-MM-DD>/
        <cache_key>.tsv       raw crosstab, BYTE-IDENTICAL to what the report
                              would have pulled (churn parsers hardcode utf-16-le,
                              so the cache must be byte-transparent)
        manifest.json         provenance for every key (pull_ts, target_date,
                              row_count, sha256, ready_probe)
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from automations.harvest import config
from automations.harvest.needs import DataNeed, cache_key, dedupe_by_cache_key
from automations.harvest.readiness import ReadinessTracker

# The one integration seam (see design §0). Imported lazily-safe at module top
# because the harvester genuinely needs the browser stack.
from automations.shared.tableau_patchright import (
    tableau_session, download_crosstab_patchright,
)
# Reuse the canonical format-sniffing parser for row counting only.
from automations.alphalete_org_report.opt_nds import _read_tab_csv


_DATE_DIR = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class HarvestEntry:
    cache_key: str
    view_url: str
    crosstab_sheet: str
    filters: dict
    pull_mode: str
    path: Path
    pull_ts: str
    target_date: str
    row_count: int
    sha256: str
    ready_probe: dict = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class HarvestResult:
    target_date: dt.date
    day_dir: Path
    entries: List[HarvestEntry]
    deferred: List[DataNeed]
    pruned: List[str]

    @property
    def ok(self) -> bool:
        return not self.deferred and all(e.error is None for e in self.entries)


def _now_iso() -> str:
    """Local, timezone-aware ISO timestamp (cross-platform; no %-directives)."""
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _row_count(path: Path) -> int:
    try:
        return len(_read_tab_csv(path))
    except Exception:
        return 0


def hook_for(need: DataNeed):
    """Rebuild the pre_export closure for a need from its declared filters.
    saved_view / url_params carry their identity in the URL, so no hook.
    A pre_export need would register a builder here (none in the churn cluster).
    """
    if need.pull_mode == "pre_export":
        raise NotImplementedError(
            f"pre_export need {need.label!r} has no registered hook builder yet")
    return None


def prune_old(target_date: dt.date, retention_days: int,
              cache_root: Path, logfn: Callable[[str], None]) -> List[str]:
    """Delete dated folders outside the rolling window. Run at the START of a
    harvest. NEVER deletes today's folder, a future folder, or one mid-write
    (marked by a .writing sentinel). Logs and returns what was deleted."""
    keep = {(target_date - dt.timedelta(days=i)).isoformat()
            for i in range(max(1, retention_days))}
    pruned: List[str] = []
    if not cache_root.exists():
        return pruned
    today_iso = target_date.isoformat()
    for d in sorted(cache_root.iterdir()):
        if not d.is_dir() or not _DATE_DIR.match(d.name):
            continue
        if d.name in keep or d.name >= today_iso:   # never today or future
            continue
        if (d / ".writing").exists():               # never a mid-write folder
            logfn(f"[prune] skip {d.name} (mid-write sentinel present)")
            continue
        shutil.rmtree(d)
        pruned.append(d.name)
        logfn(f"[prune] deleted {d.name} (outside {retention_days}-day window)")
    return pruned


def _isolation_groups(needs: List[DataNeed]) -> List[List[DataNeed]]:
    """Split needs so no two that share a crosstab_sheet land in the same group.

    Group N holds the Nth need for each worksheet: worksheets seen once all sit
    in group 1 (one login for the common case), and only a worksheet pulled
    twice forces a second group. That is exactly the boundary the session proofs
    established — different worksheet = safe to share, same worksheet with
    different URL params = leaks."""
    by_sheet: Dict[str, int] = {}
    groups: List[List[DataNeed]] = []
    for n in needs:
        sheet = (n.crosstab_sheet or "").strip().lower()
        idx = by_sheet.get(sheet, 0)
        by_sheet[sheet] = idx + 1
        while len(groups) <= idx:
            groups.append([])
        groups[idx].append(n)
    return [g for g in groups if g]


def harvest(target_date: dt.date,
            needs: List[DataNeed],
            *,
            retention_days: Optional[int] = None,
            cache_root: Optional[Path] = None,
            probe: bool = True,
            logfn: Callable[[str], None] = print,
            _session_factory=tableau_session,
            _download: Callable = download_crosstab_patchright) -> HarvestResult:
    """Pull every unique need once under ONE Tableau login into the dated cache.

    _session_factory / _download are injectable so the proof harness can drive
    the SAME code with the same live session (§10). Defaults hit real Tableau.
    """
    retention_days = (retention_days if retention_days is not None
                      else int(config.RETENTION_DAYS))
    cache_root = cache_root or config.CACHE_ROOT
    unique = dedupe_by_cache_key(needs)
    day_dir = cache_root / target_date.isoformat()

    logfn(f"=== harvest {target_date.isoformat()} — {len(unique)} unique "
          f"pull(s) (from {len(needs)} declared) ===")

    # Prune BEFORE we create today's folder, so a mid-write today folder can
    # never be a prune target and older folders are cleared first.
    pruned = prune_old(target_date, retention_days, cache_root, logfn)

    day_dir.mkdir(parents=True, exist_ok=True)
    writing = day_dir / ".writing"
    writing.write_text(_now_iso())

    tracker = ReadinessTracker(target_date=target_date)
    entries: List[HarvestEntry] = []
    deferred: List[DataNeed] = []

    # ISOLATION (Megan 2026-08-18). This loop used to hand the SAME page to every
    # need. That is WEAKER than the fresh-page-per-pull shared session that
    # FAILED on fiber's two PSS pulls (2026-08-17): the second inherited the
    # first's Product Type filter and returned 52,186 B instead of its real size
    # — wrong number, no error.
    #
    # Safe so far only by luck of contents: the churn cluster is all saved views
    # differing by GUID/worksheet, and the order-log need is alone on its
    # worksheet. Adding any second param-filtered need on a worksheet already in
    # the list would silently corrupt it. So group first, and never let two needs
    # that share a worksheet ride the same context.
    groups = _isolation_groups(unique)
    if len(groups) > 1:
        logfn(f"  ({len(groups)} isolation group(s) — needs sharing a worksheet "
              f"are pulled on separate logins)")

    try:
        for group in groups:
            with _session_factory(verbose=False) as page:
                for need in group:
                    key = cache_key(need)
                    out = day_dir / f"{key}.tsv"
                    label = need.label or key
                    if probe:
                        verdict = tracker.ready(need, page, download=_download)
                        if not verdict.ready:
                            logfn(f"  [defer] {label}: {verdict.reason}")
                            deferred.append(need)
                            continue
                    logfn(f"  -> pull {label}  [{key}]")
                    try:
                        _download(need.view_url, need.crosstab_sheet, out,
                                  verbose=False, page=page, pre_export=hook_for(need))
                    except Exception as e:  # noqa: BLE001
                        logfn(f"     x FAILED: {type(e).__name__}: {e}")
                        entries.append(HarvestEntry(
                            cache_key=key, view_url=need.view_url,
                            crosstab_sheet=need.crosstab_sheet, filters=dict(need.filters),
                            pull_mode=need.pull_mode, path=out, pull_ts=_now_iso(),
                            target_date=target_date.isoformat(), row_count=0,
                            sha256="", error=f"{type(e).__name__}: {e}"))
                        continue
                    rc = _row_count(out)
                    sha = _sha256(out)
                    logfn(f"     ok  rows={rc}  sha={sha[:12]}…  ({out.stat().st_size} B)")
                    entries.append(HarvestEntry(
                        cache_key=key, view_url=need.view_url,
                        crosstab_sheet=need.crosstab_sheet, filters=dict(need.filters),
                        pull_mode=need.pull_mode, path=out, pull_ts=_now_iso(),
                        target_date=target_date.isoformat(), row_count=rc, sha256=sha,
                        ready_probe=tracker.last_probe(need)))
    finally:
        _write_manifest(day_dir, target_date, entries)
        writing.unlink(missing_ok=True)

    logfn(f"=== harvested {sum(1 for e in entries if e.error is None)}/"
          f"{len(unique)} ok, {len(deferred)} deferred, {len(pruned)} pruned ===")
    return HarvestResult(target_date, day_dir, entries, deferred, pruned)


def _write_manifest(day_dir: Path, target_date: dt.date,
                    entries: List[HarvestEntry]) -> None:
    manifest = {
        "target_date": target_date.isoformat(),
        "written_ts": _now_iso(),
        "entries": {
            e.cache_key: {
                "view_url": e.view_url,
                "crosstab_sheet": e.crosstab_sheet,
                "filters": e.filters,
                "pull_mode": e.pull_mode,
                "pull_ts": e.pull_ts,
                "target_date": e.target_date,
                "row_count": e.row_count,
                "sha256": e.sha256,
                "ready_probe": e.ready_probe,
                "error": e.error,
            }
            for e in entries
        },
    }
    tmp = day_dir / "manifest.json.tmp"
    tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    tmp.replace(day_dir / "manifest.json")   # atomic finalize
