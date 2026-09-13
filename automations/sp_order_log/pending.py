"""The AT&T pending-orders worklist image — every line still in flight.

Carlos 2026-09-13: "kind of like how we do on the Box Metrics thread, can we
get a screenshot of the pending orders on B2B AT&T posted in that thread?
right after the activation rate by rep screenshot." Same look as the Box
Pending Orders board on purpose — box_order_log.pending_png draws this one
too (per-rep bands, black grid, status-tinted rows), fed AT&T columns and
rows via its pre-baked-cells path.

"Pending" is exactly the Activation Revenue Overview's "Still Open": the
line has no DTR posted date yet and its status is not a terminal cancel.
Same 31-day window as everything else SaraPlus (WINDOW_DAYS — hard rule,
never look back further).
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from automations.att_order_log import colors, payout as ap

# Carlos 2026-09-13 (trimming the first draft): "way less info. The SPM
# number, we won't need. Status, date, CRU/IRU, wireless installment plan,
# footprint, out of footprint... if it's empty [on the order log file], then
# we don't need it in the screenshot." Business Name stays as the row's
# identity; the rep lives in the gray band. Any candidate column that comes
# out blank on EVERY pending row is dropped from that day's image.
COLUMNS: Tuple[str, ...] = ("Business Name", "Sale Date", "CRU/IRU",
                            "Installment Plan", "IF/OOF", "Status")

# pending_png._rgb wants hex; STATUS_COLORS speaks in words. Same soft fills
# the workbooks use.
_HEX = {colors.GREEN: "C6EFCE", colors.YELLOW: "FFF2CC", colors.RED: "FFC7CE"}


def _color_fn(status: str, _history=()) -> str:
    word = colors.STATUS_COLORS.get(str(status or "").strip().lower(), "")
    return _HEX.get(word, "")


class _Row:
    """One pending line dressed for box_order_log.pending_png: pre-baked
    cells plus the attrs its layout helpers read."""
    def __init__(self, cells, status, rep, sale_date, business):
        self.cells = cells
        self.status = str(status or "").strip().lower()
        self.history: tuple = ()
        self.rep = rep
        self.sale_date = sale_date
        self.fields = {"Rep Name": rep, "Business Name": business}


def _sp_date(v) -> Optional[dt.date]:
    return ap._parse_date(v)


def build(lines, today: Optional[dt.date] = None) -> Dict:
    """{"today","count","subtitle","columns","color_fn","sections"} for
    box_order_log.pending_png.render — one section, no banner (there is no
    yellow/not-yellow split here; AT&T's chase signal is the status column)."""
    from automations.box_order_log import pending as bp
    from automations.sp_order_log.run import POSTED_COL, _orderlog_attrs
    from automations.sp_order_log.wireless_lines import norm_tn

    today = today or dt.date.today()
    # CRU/IRU, Installment Plan and IF/OOF live on the ORDER LOG, not in
    # SaraPlus — same join by line number the revenue board uses.
    try:
        attrs = _orderlog_attrs()
    except Exception:  # noqa: BLE001 — a missing export never drops the board
        attrs = {}
    raw_rows: List[Tuple[dict, str, str, Optional[dt.date], str]] = []
    for ln in lines:
        rep = str(ln.get("Rep") or "").strip()
        if not rep:
            continue
        status = str(ln.get("DTR Status (enriched)") or "").strip()
        if status.lower() in ap.CANCEL_STATUSES:
            continue
        if _sp_date(ln.get(POSTED_COL)) is not None:
            continue                      # activated -> not pending
        # Carlos 2026-09-13: the screenshot is the chase list — "Port issue
        # and port approved: I want to see those. Delivered: I want to see
        # it. Pending and shipped: good to not be on the screenshot." The
        # rest stays on the Order Log workbook.
        s_low = status.lower()
        if not ("delivered" in s_low or "port" in s_low):
            continue
        row = dict(ln)
        hit = attrs.get(norm_tn(str(row.get("spe.TN") or "")))
        if hit:
            for f in ("CRU/IRU", "IF/OOF", "Wireless Installment Plan",
                      "Package"):
                if hit.get(f) and not str(row.get(f) or "").strip():
                    row[f] = hit[f]
        wip = str(row.get("Wireless Installment Plan") or "").strip()
        if not wip and "BYOD" in str(row.get("Package") or "").upper():
            wip = "BYOD"
        sale = _sp_date(row.get("sp.Order Date (copy)"))
        business = str(row.get("Customer Name") or "").strip()
        cells = {"Business Name": business,
                 "Sale Date": sale.strftime("%m/%d/%Y") if sale else "",
                 "CRU/IRU": str(row.get("CRU/IRU") or "").strip(),
                 "Installment Plan": wip,
                 "IF/OOF": str(row.get("IF/OOF") or "").strip(),
                 "Status": status or "—"}
        raw_rows.append((cells, status, rep, sale, business))

    # Carlos's empty-column rule: a candidate nobody has a value for today
    # is dropped from the image (Business Name / Sale Date / Status always
    # carry values, so the board never loses its spine).
    cols = tuple(c for c in COLUMNS
                 if any(r[0][c].strip() for r in raw_rows)) or COLUMNS
    rows = [_Row(tuple(cells[c] for c in cols), status, rep, sale, business)
            for cells, status, rep, sale, business in raw_rows]

    n = len(rows)
    subtitle = ("AT&T lines DELIVERED or in PORTING, not activated yet (last "
                "31 days of sales), by sales rep — {} as of {}. Pending / "
                "shipped lines stay on the Order Log workbook."
                .format("{} line{}".format(n, bp.plural(n)) if n
                        else "none right now",
                        today.strftime("%B %d, %Y").replace(" 0", " ")))
    return {"today": today, "count": n, "subtitle": subtitle,
            "title": "Pending orders — delivered / porting, not yet activated",
            "columns": cols, "color_fn": _color_fn,
            "sections": [{"key": "pending", "title": None, "rows": rows,
                          "reps": bp.by_rep(rows),
                          "empty_note": "Nothing pending — every line in the "
                                        "window is activated or closed."}]}


# Beyond this many rows one image needs too much zoom on a phone (Carlos
# 2026-09-13: "definitely too long... better in two screenshots").
SPLIT_AT = 20


def build_png(lines, today: Optional[dt.date] = None, log=print,
              out_path: Optional[Path] = None) -> List[Path]:
    """One or two PNGs (both halves ride ONE Slack message). The split is by
    whole rep bands, balanced by line count, A-Z order preserved across the
    pair — so part 1 ends where a rep ends and nobody's block is torn."""
    from automations.box_order_log import pending_png
    from automations.sp_order_log.run import OUT_DIR, _register_colors
    _register_colors()
    work = build(lines, today)
    out = Path(out_path) if out_path else (OUT_DIR / "pending_orders.png")
    sec = work["sections"][0]
    if work["count"] <= SPLIT_AT or len(sec["reps"]) < 2:
        pending_png.render(work, out)
        log("pending orders -> %s (%d line(s) in flight)"
            % (out.name, work["count"]))
        return [out]
    reps, total, acc, cut = sec["reps"], work["count"], 0, 1
    for i, (_rep, rrows) in enumerate(reps):
        acc += len(rrows)
        if acc >= total / 2:
            cut = i + 1
            break
    cut = min(cut, len(reps) - 1)
    outs: List[Path] = []
    for i, part in enumerate((reps[:cut], reps[cut:]), 1):
        prows = [r for _rep, rs in part for r in rs]
        w = dict(work)
        w["title"] = "{} ({} of 2)".format(work["title"], i)
        w["count"] = len(prows)
        w["subtitle"] = work["subtitle"] + "  Part {} of 2 — reps {}–{}.".format(
            i, part[0][0].split()[0], part[-1][0].split()[0])
        w["sections"] = [dict(sec, rows=prows, reps=part)]
        p = out.with_name("{}_{}{}".format(out.stem, i, out.suffix))
        pending_png.render(w, p)
        outs.append(p)
    log("pending orders -> %s + %s (%d line(s) in flight, split at %d rows)"
        % (outs[0].name, outs[1].name, total, SPLIT_AT))
    return outs
