"""Section catalog + current-plan helpers for the Thread Builder panel.

Bridges the two runners' native section models into one uniform shape the UI can
render, so the panel never hardcodes section names:

  - B2B  sections = b2b_metrics.runner.ITEMS   (id, emoji, title)
  - D2D  sections = office_metrics.runner.metrics_for(o)  (slug, label)

The id space is each runner's own (ITEMS ids / metrics_for slugs) — the SAME ids
thread_plans.json stores and the resolver consumes, so what the panel writes is
exactly what the runner reads.
"""
from __future__ import annotations

from typing import List, Tuple

CAMPAIGNS = ("d2d", "b2b")
CAMPAIGN_LABEL = {"d2d": "D2D — Office Metrics", "b2b": "B2B — Metrics"}


def offices(campaign: str) -> List[Tuple[str, str]]:
    """[(office_key, display), ...] in the runner's canonical order."""
    if campaign == "b2b":
        from automations.b2b_metrics import offices as o
        return [(k, _office_display(o.get(k))) for k in o.ORDER]
    from automations.office_metrics import offices as o
    return [(k, _office_display(o.get(k))) for k in o.ORDER]


def _office_display(off) -> str:
    chan = getattr(off, "channel_name", "") or ""
    return "{}{}".format(getattr(off, "label", getattr(off, "key", "?")),
                         "  ·  {}".format(chan) if chan else "")


def catalog(campaign: str) -> List[Tuple[str, str]]:
    """Every section the campaign CAN post, canonical order: [(id, label), ...].
    label carries the emoji, so the panel shows the same glyphs as the thread."""
    if campaign == "b2b":
        from automations.b2b_metrics.runner import ITEMS
        return [(i["id"], "{} {}".format(i["emoji"], i["title"])) for i in ITEMS]
    # D2D: labels live on the metrics_for dicts (already emoji-prefixed). They are
    # static per slug, so any office yields the same labels — use the first.
    from automations.office_metrics import offices as _off
    from automations.office_metrics.runner import metrics_for
    o = _off.get(_off.ORDER[0])
    return [(m["slug"], m["label"]) for m in metrics_for(o)]


def current_ids(campaign: str, office_key: str) -> List[str]:
    """The section ids this office posts TODAY, in order — its saved plan if one
    exists, else the runner default. This is what the editor pre-loads, so a fresh
    edit starts from the office's real current thread."""
    if campaign == "b2b":
        from automations.b2b_metrics import offices as _off
        from automations.b2b_metrics.runner import expected_ids
        return list(expected_ids(_off.get(office_key)))
    from automations.office_metrics import offices as _off
    from automations.office_metrics.runner import metrics_for
    from automations.shared import thread_plans as tp
    o = _off.get(office_key)
    base = metrics_for(o)
    resolved = tp.resolve_sections("d2d", office_key, base, base, id_key="slug")
    return [m["slug"] for m in resolved]


def default_ids(campaign: str, office_key: str) -> List[str]:
    """The section ids this office would post with NO plan — the runner's native
    default (B2B: ITEMS minus skip_views; D2D: every metrics_for slug). Lets the
    panel drop a plan that just re-states the default, so unchanged offices keep
    auto-inheriting new sections instead of freezing."""
    if campaign == "b2b":
        from automations.b2b_metrics import offices as _off
        from automations.b2b_metrics.runner import ITEMS
        o = _off.get(office_key)
        return [i["id"] for i in ITEMS if i["id"] not in o.skip_views]
    from automations.office_metrics import offices as _off
    from automations.office_metrics.runner import metrics_for
    return [m["slug"] for m in metrics_for(_off.get(office_key))]


def label_map(campaign: str) -> dict:
    """id -> display label (with emoji), for rendering + reverse lookup."""
    return dict(catalog(campaign))
