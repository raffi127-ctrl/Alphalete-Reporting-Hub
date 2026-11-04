"""OwnerVille -> Onboard -> View Progress: a rep's Progress % (Carlos
2026-10-31: 100% = fully onboarded). One name at a time, through the table's
own search -- the table is server-side and only ever shows one page
(digi_docs.roster_check)."""
from __future__ import annotations

import re
from typing import Dict, Optional

PCT = re.compile(r"(\d{1,3})\s*%")


def _open_progress(page, campaign: str) -> None:
    from automations.b2b_dispositions.capture import capture_rqst
    from automations.headshots.ov_upload import (VIEW_PROGRESS_P, _campaign_select,
                                                  _show_all)
    rqst = capture_rqst(page)
    page.set_default_navigation_timeout(90000)
    page.goto("https://v2.ownerville.com/index.cfm?p=%s&rqst=%s" % (VIEW_PROGRESS_P, rqst),
              wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=60000)
    except Exception:  # noqa: BLE001
        pass
    _campaign_select(page).select_option(label=campaign)
    try:
        page.wait_for_load_state("networkidle", timeout=60000)
    except Exception:  # noqa: BLE001
        pass
    _show_all(page)


def progress_for(page, name: str) -> Optional[int]:
    """The Progress % on the (single) row carrying this whole name, or None
    when the row is missing, ambiguous, or has no percentage."""
    from automations.headshots.ov_upload import _search_box, _search_probes
    parts = [p for p in name.split() if p]
    if not parts:
        return None
    pat = re.compile(r"\s+".join(re.escape(p) for p in parts), re.I)
    for probe in _search_probes(name):
        box = _search_box(page)
        box.fill("")
        box.press_sequentially(probe, delay=40)
        rows = None
        for _ in range(16):
            page.wait_for_timeout(500)
            rows = page.locator("tbody tr").filter(has_text=pat)
            if rows.count():
                page.wait_for_timeout(800)
                rows = page.locator("tbody tr").filter(has_text=pat)
                break
        if rows is None or rows.count() != 1:
            continue
        cells = [c.strip() for c in rows.first.locator("td").all_inner_texts()]
        for c in reversed(cells):           # Progress is the far-right column
            m = PCT.search(c)
            if m:
                return int(m.group(1))
        return None
    return None


def progress_many(names_by_campaign: Dict[str, list], log=print) -> Dict[str, Optional[int]]:
    """{name: progress%} for every (campaign -> [names]) in ONE OwnerVille session."""
    from automations.digi_docs import ownerville as ov
    out: Dict[str, Optional[int]] = {}
    with ov.session(headless=True, verbose=False) as page:
        for campaign, names in names_by_campaign.items():
            if not names:
                continue
            _open_progress(page, campaign)
            for n in names:
                try:
                    out[n] = progress_for(page, n)
                except Exception as e:  # noqa: BLE001
                    log("  %s: OwnerVille read failed (%s)" % (n, type(e).__name__))
                    out[n] = None
                log("  View Progress %s: %s -> %s" % (campaign, n, "%s%%" % out[n] if out[n] is not None else "not found"))
    return out
