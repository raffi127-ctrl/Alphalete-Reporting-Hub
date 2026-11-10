"""📆 Activations Scheduled Today for the B2B Metrics threads.

Raf 2026-11-10 ("sure", to Eve's "Do we also want this built for B2B fiber
sales?"): the same board the D2D offices get, in each B2B office's thread.

Source path: Tableau -> ATT TRACKER B2B -> ORDERLOG -> the all-reps export the
B2B thread already pulls ONCE per morning (b2b_metrics.capture._order_lines),
sliced to the office owner. Then: spe.Install Date = today (Central), no
posted date, status not canceled / disconnected.

B2B sells mostly wireless, which has no install date, so most days only fiber
lines show; a day with none still posts the board with "No installs scheduled
today" (the export is proven loaded by _order_lines, which raises when empty).
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Dict, List

from automations.activations_today import pull

# B2B ORDERLOG column -> the D2D names pull/build already read.
_MAP = {
    pull.REP: ("Rep",),
    pull.CUSTOMER: ("Customer Name",),
    pull.PHONE: ("spe.Phone", "sp.Customer Phone"),
    pull.SALE_DATE: ("sp.Order Date (copy)",),
    pull.INSTALL_DATE: ("spe.Install Date",),
    pull.STATUS: ("DTR Status (enriched)", "spe.Status"),
    pull.PRODUCT: ("Product Type (Broken Out)",),
    pull.PACKAGE: ("Package",),
    pull.TECH: ("Tech Install",),
    pull.ACTIVATION: ("spe.dtr Posted Date (copy)",),
}


def to_pull_rows(lines: List[Dict], owner: str) -> List[Dict[str, str]]:
    out = []
    for ln in lines:
        row = {pull.OWNER: owner}
        for key, cols in _MAP.items():
            row[key] = next((str(ln.get(c) or "").strip() for c in cols
                             if str(ln.get(c) or "").strip()), "")
        out.append(row)
    return out


def image(o, out_dir: Path, log=print, today: dt.date = None) -> Path:
    """The board PNG for one B2B office (zero rows -> the 'none today' board)."""
    from automations.activations_today import run
    from automations.b2b_metrics import capture
    day = today or pull.central_today()
    lines = capture._order_lines(o, out_dir, log=log)
    rows = pull.scheduled_on(to_pull_rows(lines, o.owner), day)
    log("   activations today [{}]: {} line(s) in the log, {} installing {}".format(
        o.key, len(lines), len(rows), day))
    work = run.build(rows, getattr(o, "label", None) or o.owner, day)
    out = Path(out_dir) / "activations_today.png"
    return run.render(work, out)[0]
