"""Cache loader — what reports call INSTEAD of scraping Tableau. Hard-fails
(raises, never serves stale) if the requested date's cache is missing or its
provenance doesn't match.

SHADOW-ONLY. Nothing on the live 4am path imports this. See README.md.

    from automations.harvest.loader import load_harvest, load_harvest_rows
    path = load_harvest(need, target_date)          # verified byte-identical file
    rows = load_harvest_rows(need, target_date)      # parsed via canonical reader

`load_harvest` returns the raw cached file path so a report's OWN parser
(the churn parsers hardcode utf-16-le) reads byte-identical bytes — the cache
is byte-transparent. `load_harvest_rows` is a convenience for reports that want
rows and are happy with the canonical format-sniffing parser.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import List, Optional

from automations.harvest import config
from automations.harvest.needs import DataNeed, cache_key
from automations.alphalete_org_report.opt_nds import _read_tab_csv


class StaleCacheError(RuntimeError):
    """Raised when the requested date's cache is missing, stale, or corrupt.
    Callers must treat this as 'no data' — NEVER fall back to yesterday."""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_harvest(need: DataNeed, target_date: dt.date,
                 *, cache_root: Optional[Path] = None) -> Path:
    """Return the verified cached crosstab file for `need` on `target_date`,
    or raise StaleCacheError. Every provenance check the manifest supports is
    enforced here — the guard, not the caller, decides trust."""
    cache_root = cache_root or config.CACHE_ROOT
    day_dir = cache_root / target_date.isoformat()
    key = cache_key(need)
    label = need.label or key

    manifest_path = day_dir / "manifest.json"
    if not manifest_path.exists():
        raise StaleCacheError(
            f"{label}: no harvest manifest for {target_date.isoformat()} "
            f"({manifest_path})")
    manifest = json.loads(manifest_path.read_text())

    # target_date on the manifest must match what we asked for.
    if manifest.get("target_date") != target_date.isoformat():
        raise StaleCacheError(
            f"{label}: manifest target_date {manifest.get('target_date')!r} "
            f"!= requested {target_date.isoformat()!r}")

    entry = manifest.get("entries", {}).get(key)
    if entry is None:
        raise StaleCacheError(
            f"{label}: cache key {key} not in {target_date.isoformat()} manifest")
    if entry.get("error"):
        raise StaleCacheError(f"{label}: harvest recorded an error — {entry['error']}")

    # pull_ts date must not predate the requested date (never serve an older harvest).
    try:
        pull_date = dt.datetime.fromisoformat(entry["pull_ts"]).date()
    except Exception:
        raise StaleCacheError(f"{label}: unparseable pull_ts {entry.get('pull_ts')!r}")
    if pull_date < target_date:
        raise StaleCacheError(
            f"{label}: harvest pulled {pull_date.isoformat()} < requested "
            f"{target_date.isoformat()} (stale)")
    if entry.get("target_date") != target_date.isoformat():
        raise StaleCacheError(
            f"{label}: entry target_date {entry.get('target_date')!r} mismatch")

    path = day_dir / f"{key}.tsv"
    if not path.exists():
        raise StaleCacheError(f"{label}: cache file missing ({path})")
    if entry.get("row_count", 0) <= 0:
        raise StaleCacheError(f"{label}: harvest row_count == 0 (empty extract)")

    actual = _sha256(path)
    if actual != entry.get("sha256"):
        raise StaleCacheError(
            f"{label}: checksum mismatch (file {actual[:12]}… != manifest "
            f"{str(entry.get('sha256'))[:12]}…) — corrupt/partial download")
    return path


def load_harvest_rows(need: DataNeed, target_date: dt.date,
                      *, cache_root: Optional[Path] = None) -> List[List[str]]:
    """Verified cache rows via the canonical format-sniffing parser."""
    return _read_tab_csv(load_harvest(need, target_date, cache_root=cache_root))


def cache_available(need: DataNeed, target_date: dt.date,
                    *, cache_root: Optional[Path] = None) -> bool:
    """Non-raising probe: True iff load_harvest would succeed."""
    try:
        load_harvest(need, target_date, cache_root=cache_root)
        return True
    except StaleCacheError:
        return False
