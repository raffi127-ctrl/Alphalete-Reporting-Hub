"""Per-office metrics-thread PLANS — which sections post, and in what order.

One committed file, `thread_plans.json`, keyed campaign -> office_key -> ordered
list of section ids. It is the single source the "Thread Builder" Hub panel writes
and BOTH metrics runners read:

  - B2B  (b2b_metrics.runner)   section ids = the ITEMS ids
         (sales_metrics, activation_rate, churn_wireless, ..., out_of_bounds)
  - D2D  (office_metrics.runner) section ids = the metrics_for slugs
         (order_log, sales_6plus, cancels, ..., tableau_shot)

DESIGN — additive with EXACT fallback. An office with NO entry here behaves
byte-for-byte as it does today (the runner's own hardcoded order + skip_views).
An entry OVERRIDES: it lists exactly the included section ids in the order they
should post (a selection IS its order, same contract as tracker_ids_for). A plan
may RE-ADD a section the runner's default drops (it is validated against the full
catalog, not the post-skip default), so the panel can turn churn back on for an
office that skips it.

SAFETY — a missing, empty, or MALFORMED file must NEVER break a live thread:
every read is best-effort and falls back to the runner's default. resolve_sections
also refuses to return an empty list (a typo'd plan that matches nothing falls back
rather than posting a blank thread).

Shape:
    {
      "b2b": {"carlos": ["sales_metrics", "activation_rate", ...]},
      "d2d": {"rashad": ["order_log", "churn", ...]}
    }
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

CAMPAIGNS = ("d2d", "b2b")

_PATH = Path(__file__).with_name("thread_plans.json")


def _path() -> Path:
    # Env override lets a test/sandbox point at a scratch file without touching
    # the committed one. Absent -> the committed sibling file.
    return Path(os.environ.get("THREAD_PLANS_PATH") or _PATH)


def load() -> dict:
    """The whole plans map. {} when the file is absent, empty, or unreadable —
    a broken file can never crash a runner (it just means 'no overrides')."""
    p = _path()
    try:
        if not p.exists():
            return {}
        raw = json.loads(p.read_text(encoding="utf-8") or "{}")
    except Exception as e:  # noqa: BLE001 — never let a bad file break a thread
        print("[thread_plans] ignoring unreadable {} ({})".format(
            p.name, type(e).__name__), file=sys.stderr)
        return {}
    if not isinstance(raw, dict):
        return {}
    # Normalize: only keep campaign -> {office -> [str, ...]} shapes.
    out: dict = {}
    for campaign, offices in raw.items():
        if campaign not in CAMPAIGNS or not isinstance(offices, dict):
            continue
        clean = {}
        for key, ids in offices.items():
            if isinstance(ids, list) and all(isinstance(x, str) for x in ids):
                clean[key] = ids
        out[campaign] = clean
    return out


def plan_for(campaign: str, office_key: str) -> Optional[List[str]]:
    """The configured ordered section-id list for one office, or None if this
    office has no plan (-> the runner uses its own default)."""
    return load().get(campaign, {}).get(office_key)


def resolve_sections(campaign: str, office_key: str, full_sections: list,
                     default_sections: list, *, id_key: str) -> list:
    """Resolve the ordered section list for one office.

    full_sections   — every section the campaign CAN post (the catalog), each a
                      dict carrying `id_key`. A plan is validated against this, so
                      it may re-add a section the default drops.
    default_sections — what the runner posts today (catalog minus hardcoded
                      skips). Returned unchanged when the office has no plan.
    id_key          — "id" for B2B ITEMS, "slug" for D2D metrics_for.

    A plan reorders/filters to exactly its listed ids (unknown/stale ids dropped).
    If a plan matches nothing (all stale), fall back to default rather than post a
    blank thread.
    """
    plan = plan_for(campaign, office_key)
    if not plan:
        return default_sections
    by_id = {s[id_key]: s for s in full_sections}
    picked = [by_id[i] for i in plan if i in by_id]
    return picked or default_sections


def save_plan(campaign: str, office_key: str, section_ids: List[str]) -> None:
    """Write/replace one office's plan (used by the Thread Builder panel). Atomic
    tmp-replace so a concurrent runner read never sees a half-written file."""
    if campaign not in CAMPAIGNS:
        raise ValueError("unknown campaign {!r} (expected one of {})".format(
            campaign, CAMPAIGNS))
    data = load()
    data.setdefault(campaign, {})[office_key] = list(section_ids)
    _write(data)


def clear_plan(campaign: str, office_key: str) -> bool:
    """Drop one office's plan so it reverts to the runner default. True if a plan
    was present."""
    data = load()
    if data.get(campaign, {}).pop(office_key, None) is None:
        return False
    _write(data)
    return True


def replace_all(mapping: dict) -> None:
    """Overwrite the ENTIRE plans file with `mapping` (campaign -> office -> ids).
    Used by thread_builder.sync to materialize the Sheet each morning. Normalized
    + atomically written; an empty mapping writes an empty (all-defaults) file."""
    clean: dict = {}
    for campaign, offices in (mapping or {}).items():
        if campaign not in CAMPAIGNS or not isinstance(offices, dict):
            continue
        clean[campaign] = {k: [str(x) for x in ids]
                           for k, ids in offices.items()
                           if isinstance(ids, list)}
    _write(clean)


def _write(data: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".thread_plans_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, p)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
