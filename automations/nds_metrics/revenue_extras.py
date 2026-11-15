# -*- coding: utf-8 -*-
"""NDS Revenue Board extras (Carlos 2026-11-15, after seeing the Verizon board:
"I like how the Verizon one shows what tier they're on right next to the
rep's week total ... checkmarks ... shows the rep how many lines they have
activated this week"):

  * TIER chip next to the week total: the rep's tier this Sun-Sat tier week
    by orders with a port line (T1 4 / T2 5-6 / T3 7-8 / T4 9+, sow_rates
    rep_tier bands; "—" below 4) -- the same count the "N orders" badge and
    the tier columns use.
  * LINES ACTIVATED this week ($ activated): the first right-side column.
    Wireless lines that went Active this Mon-Sun board week on SaraPlus's
    wireless report (line_revenue's ledger, the Activation Revenue
    Overview's "this week"), with the $ that activated in parentheses --
    every dollar the Activation Revenue Overview posts for that rep this
    week (lines, add-ons, tier bonus, Air, Protect).
  * the PORT LINES count moved beside the order count after the name
    ("5 orders · 23 port lines").
  * two stat cards top right: the crew activation rate for the last four
    week endings (the SaraPlus Activation Rate by Week Ending board's rate,
    activated lines / lines sold, oldest first) and the 0-30 day churn of
    wireless NON-BYOD phone lines (the NDS CHURN tab's "All Wireless" box
    row: lines activated in the last 30 days that have disconnected --
    no Air, no BYOD, no tablets / watches / upgrades).
  * "sales per rep" after the REPS ON THE BOARD count (renderer
    extra["reps_extra"]): the board week's orders (distinct SPM numbers on
    his owner, Mon..today) over the reps listed.

Every extra is best-effort: a source that cannot be read logs a NOTE and
leaves its column / card blank -- the board itself never waits on it.
Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional, Sequence, Tuple

from automations.nds_metrics.run import (OUT_DIR, _c, _parse_date, load_soh,
                                         tier_bands, tier_cells)

ACTIVATED_HEADER = 'LINES ACTIVATED<br><span class="dd">this week ($ activated)</span>'
NOTE = ("Tier = orders with a port line this Sun–Sat week (T1 4 · T2 5–6 · T3 7–8 · T4 9+). "
        "Lines activated = wireless lines that went active this Mon–Sun week on SaraPlus, "
        "($) = all $ that activated with them. Tier columns: green ✓ = your tier; yellow = one "
        "order away; +N = orders still needed; $ = that tier's rate × your port lines (+1 per "
        "order still needed), paid as they activate. DNQ not applied.")
WEEKS = 4
_SMALL = '<span style="font-size:14px;color:#5b6770;font-weight:500">%s</span>'


# ------------------------------------------------------------- pure ----

def tier_name(n_orders: int, bands=None) -> str:
    """'T1'..'T4' for the band the order count reaches, '—' below the first."""
    bands = bands or tier_bands()
    name = "—"
    for i, (thr, _rate) in enumerate(bands):
        if n_orders >= thr:
            name = "T%d" % (i + 1)
    return name


def rep_badge(n_orders: int, port_lines: int) -> str:
    return "%d order%s · %d port line%s" % (n_orders, "" if n_orders == 1 else "s",
                                                port_lines, "" if port_lines == 1 else "s")


def activated_cell(act: Optional[Tuple[int, float]]) -> dict:
    """'12 ($2,556)'; '0' when nothing activated; blank when the source was
    unreadable (act None)."""
    if act is None:
        return {"text": "", "cls": "ct"}
    n, dollars = act
    if not n and not dollars:
        return {"text": "0", "cls": "ct"}
    return {"text": "%d ($%s)" % (n, format(int(round(dollars)), ",")), "cls": "ct"}


def row_extras(n_orders: int, port_lines: int, act: Optional[Tuple[int, float]],
               bands=None) -> Tuple[List[dict], str, str]:
    """-> (right-side cells, name badge, tier chip text) for one rep row:
    the LINES ACTIVATED cell replaces tier_cells' port-lines count (that count
    now rides the badge), the band cells follow unchanged."""
    cells = tier_cells(n_orders, port_lines, bands)
    return ([activated_cell(act)] + cells[1:], rep_badge(n_orders, port_lines),
            tier_name(n_orders, bands))


def _norm(name: str) -> str:
    return " ".join(str(name or "").lower().split())


def match_rep(name: str, candidates: Sequence[str]) -> Optional[str]:
    """The SaraPlus rep name for a Tableau rep name: the same name first,
    else the one whose words are a subsequence (first name anchored, middle
    names free) either way -- load_crew's crew rule."""
    from automations.total_knocks import guests
    want = _norm(name)
    for c in candidates:
        if _norm(c) == want:
            return c
    t = guests._tokens(name)
    for c in candidates:
        ct = guests._tokens(c)
        if guests._subseq(t, ct) or guests._subseq(ct, t):
            return c
    return None


def activated_this_week(res: dict) -> Dict[str, Tuple[int, float]]:
    """line_revenue result -> {SaraPlus rep: (wireless lines activated this
    Mon-Sun week, $ posted this week)}. Lines = the wireless report's lines
    whose bucket is posted_this (a line that died later still activated);
    $ = the Activation Revenue Overview's this-week posted total."""
    out: Dict[str, List] = {}
    for d in res.get("detail") or []:
        if d.get("line") in ("PROTECT", "AIR", "(order)"):
            continue
        if not str(d.get("bucket") or "").startswith("posted_this"):
            continue
        out.setdefault(d["rep"], [0, 0.0])[0] += 1
    for row in (res.get("tables") or {}).get("this", {}).get("rows") or []:
        out.setdefault(row["rep"], [0, 0.0])[1] = float(row.get("posted") or 0)
    return {rep: (n, dollars) for rep, (n, dollars) in out.items()}


def activated_for(rep: str, activated: Optional[Dict[str, Tuple[int, float]]]
                  ) -> Optional[Tuple[int, float]]:
    """The board rep's (lines, $) off activated_this_week, matched by name;
    (0, 0) when the rep activated nothing; None when the source is missing."""
    if activated is None:
        return None
    key = match_rep(rep, list(activated))
    return activated.get(key, (0, 0.0)) if key else (0, 0.0)


def board_sales(cols, lines, monday: dt.date, today: dt.date, i_od, i_rep, i_spm) -> int:
    """Orders on the board week (Mon..today): distinct sp.SPM Numbers among
    the lines priced on the board, any line type."""
    seen = set()
    for r in lines:
        od = _parse_date(_c(cols, r, i_od))
        rep = _c(cols, r, i_rep)
        if not rep or od is None or not (monday <= od <= today):
            continue
        spm = (_c(cols, r, i_spm) if i_spm is not None else "") or "%s|%s|%s" % (rep, od, id(r))
        seen.add(spm)
    return len(seen)


def reps_extra(n_reps: int, n_sales: int) -> str:
    """The REPS ON THE BOARD card's suffix (renderer extra["reps_extra"]):
    sales per rep = the board week's orders over the reps listed."""
    per = ("%.1f" % (n_sales / n_reps)) if n_reps else "—"
    return " " + _SMALL % ("· %s sales per rep (%d sale%s this week)"
                           % (per, n_sales, "" if n_sales == 1 else "s"))


def weeks_card(rows: Optional[Sequence[dict]]) -> str:
    """'WE 10/25 77% · WE 11/1 71% · ...' oldest first off
    activation_by_week.rows_from; '—' when the source is missing."""
    if not rows:
        return "—"
    parts = []
    for r in rows[-WEEKS:]:
        pct = ("%.0f%%" % (100 * r["rate"])) if r.get("lines") else "—"
        parts.append('<span style="white-space:nowrap">WE %d/%d <b>%s</b></span>'
                     % (r["we"].month, r["we"].day, pct))
    return ('<span style="font-size:17px;font-weight:600">'
            + " &nbsp;·&nbsp; ".join(parts) + "</span>")


def churn_card(box: Optional[dict]) -> str:
    """'4.2% 3 of 71 ...' off the NDS CHURN tab's All Wireless box row
    (compute.product_box()['wireless']); '—' with no activations / no source."""
    if not box or not box.get("act"):
        return "—"
    act, disc = int(box["act"]), int(box.get("disc") or 0)
    return "%.1f%% %s" % (100.0 * disc / act,
                          _SMALL % ("%d of %d lines activated in the last 30 days" % (disc, act)))


def cards(weeks_rows, churn_box) -> List[Tuple[str, str]]:
    return [("ACTIVATION RATE BY WEEK-ENDING", weeks_card(weeks_rows)),
            ("0–30 DAY CHURN · WIRELESS NON-BYOD", churn_card(churn_box))]


# --------------------------------------------------------------- IO ----

def gather(cols, lines, today: dt.date, log=print) -> dict:
    """-> {'activated': {rep: (lines, $)} | None, 'weeks': rows | None,
    'churn': box | None}; every part on its own, a failure logs a NOTE."""
    out = {"activated": None, "weeks": None, "churn": None}
    soh = None
    try:
        soh = load_soh(log=log)
    except Exception as e:  # noqa: BLE001
        log("[nds] revenue board: NOTE SaraPlus SOH unavailable (%s: %s)" % (type(e).__name__, str(e)[:120]))
    if soh:
        try:
            from automations.nds_metrics import line_revenue as LR
            res = LR.prepare(soh, today, log=lambda *_a, **_k: None, save=False,
                             tableau=(cols, lines))
            out["activated"] = activated_this_week(res)
            n = sum(v[0] for v in out["activated"].values())
            d = sum(v[1] for v in out["activated"].values())
            log("[nds] revenue board: lines activated this week %d line(s) / $%s across %d rep(s)"
                % (n, format(int(round(d)), ","), len(out["activated"])))
        except Exception as e:  # noqa: BLE001
            log("[nds] revenue board: NOTE lines activated column blank (%s: %s)"
                % (type(e).__name__, str(e)[:120]))
        try:
            from automations.nds_metrics import activation_by_week as AW
            from automations.nds_metrics import line_revenue as LR
            ix, orders, _pulled = soh
            soh_active, _ = LR.soh_dates(ix, orders)
            state, _fd, feed_lines = LR.replay(LR.cached_feeds(), soh_active,
                                               log=lambda *_a, **_k: None, save=False)
            all_weeks, data = AW.aggregate(soh, feed_lines, state, today, weeks=WEEKS)
            out["weeks"] = AW.rows_from(all_weeks, data, today)
            log("[nds] revenue board: activation rate card "
                + ", ".join("WE %d/%d %.0f%%" % (r["we"].month, r["we"].day, 100 * r["rate"])
                            for r in out["weeks"]))
        except Exception as e:  # noqa: BLE001
            log("[nds] revenue board: NOTE activation rate card blank (%s: %s)"
                % (type(e).__name__, str(e)[:120]))
    else:
        log("[nds] revenue board: NOTE no SaraPlus SOH -- lines activated column + "
            "activation rate card blank")
    try:
        from automations.nds_churn import compute as NC
        path = OUT_DIR / ("nds_orderlog_%s.csv" % today.isoformat())
        _h, _ix, churn_lines = NC.load_owner_lines(path, log=lambda *_a, **_k: None)
        out["churn"] = NC.product_box(churn_lines, today)["wireless"]
        b = out["churn"]
        log("[nds] revenue board: churn card %d of %d non-BYOD phone lines disconnected (0-30)"
            % (b.get("disc", 0), b.get("act", 0)))
    except Exception as e:  # noqa: BLE001
        log("[nds] revenue board: NOTE churn card blank (%s: %s)" % (type(e).__name__, str(e)[:120]))
    return out
