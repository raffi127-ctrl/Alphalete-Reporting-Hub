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
    extra["reps_extra"]): this week's apps over the reps listed.
  * (11/15 pm) the "N orders · M apps" badge after the name (orders = the
    Sun-Sat tier count, apps = port phones + BYODs + Airs sold this Mon-Sun
    week) and a WHAT SOLD column on the far right, two lines -- new phones /
    BYOD / Air, then Next Up / Premium / Extra / Value -- the payout
    variables; the OFFICE TOTAL row carries the sums. Each sold line is
    priced like the deposit (board_line_price).
  * (11/15 night, the Verizon board's look, Carlos: "make those changes with
    our version equivalent") single-line names (the stacked cell made
    everything too small), reps + sales/rep inside the week-total card, the
    week-ending rates as coloured boxes, the churn % coloured by the SOW
    chart, an APP MIX card (share of the week's apps by BYOD / Air /
    Premium / Extra / Next Up).

Every extra is best-effort: a source that cannot be read logs a NOTE and
leaves its column / card blank -- the board itself never waits on it.
Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional, Sequence, Tuple

from automations.nds_metrics.run import (OUT_DIR, _c, _parse_date, load_soh,
                                         tier_bands, tier_cells)

ACTIVATED_HEADER = 'LINES ACTIVATED<br><span class="dd">this week ($)</span>'
NOTE = ("Orders = this Sun–Sat bonus week (double-tier days count twice); apps = port lines + BYODs + "
        "Airs sold this Mon–Sun week, what sold on the right (Next Up shows once the line's installment "
        "plan posts). Tier T1 4 · T2 5–6 · T3 7–8 · T4 9+ orders. Lines activated = wireless lines that "
        "went active this week on SaraPlus, ($) = all $ that activated with them. Tier columns: green ✓ = "
        "your tier; yellow = one order away; +N = orders still needed; $ = that tier's rate × your port "
        "lines (+1 per order still needed). DNQ not applied.")
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


# ------------------------------------------------- what sold (apps) ----
# Carlos 2026-11-15 pm, on the first version's "40 sales this week" (orders):
# "That 40 sales is 100% wrong. We did 130-something ... Apps include the
# port lines, the BYODs, and the AERS that were sold ... For Stephanie,
# you're saying 23 port lines: just call it 23 apps, and then there should
# be a breakdown of how many were new phones and how many were BYODs ...
# only if it affects payout. For us, ported new phones, BYODs, and AERS all
# have a slightly different payout ... How many had next up? ... Unlimited
# premium versus unlimited extra". All of it off the Tableau order-log rows
# the board prices (sold Mon..today); the office total row sums them.

OFFICE = "__OFFICE__"
APP_KINDS = ("new phone", "byod", "air")
PHONE_KINDS = ("new phone", "byod", "new number")


def column_index(cols) -> dict:
    """The export columns the breakdown and the pricing read, by role
    (None when the export lacks one -- the reader treats it as blank)."""
    return {"prod": cols.find("product type (broken out)", "product type"),
            "tn": cols.find("spe.tn type", "tn type"),
            "device": cols.find("device description", "spe.phone", "device"),
            "package": cols.find("package"),
            "wt": cols.find("spe.wireless type", "wireless type"),
            "wip": cols.find("wireless installment plan"),
            "ifoof": cols.find("if/oof"),
            "abp": cols.find("auto bill pay"),
            "rep": cols.find("rep"),
            "spm": cols.find("sp.spm number", "spm number")}


def line_rec(cols, r, idx: dict) -> dict:
    """One Tableau row as the fields line_kind / board_line_price read (the
    NDS CHURN tab's record shape, so its BYOD and tablet rules apply)."""
    from automations.nds_churn import compute as NC

    def g(k):
        return _c(cols, r, idx.get(k)) if idx.get(k) is not None else ""
    prod = NC.product_of(g("prod")) if idx.get("prod") is not None else "Wireless"
    return {"prod": prod, "tn_type": g("tn"), "device": g("device"), "package": g("package"),
            "wireless_type": g("wt"), "wireless_ip": g("wip"), "if_oof": g("ifoof"),
            "abp": g("abp")}


def line_kind(rec: dict) -> str:
    """'new phone' = a ported, financed phone; 'byod' = the customer's own
    phone (the installment plan says BYOD, else the NDS CHURN tab's device
    rule); 'air' = Internet Air; 'device' = tablet / wearable / hotspot;
    'new number' = a financed phone on a new number; 'upgrade';
    'internet' (fiber); 'other'."""
    from automations.nds_churn import compute as NC
    p = rec.get("prod")
    if p == "Air":
        return "air"
    if p == "Internet":
        return "internet"
    if p != "Wireless":
        return "other"
    if NC.is_non_phone(rec):
        return "device"
    tn = str(rec.get("tn_type") or "").strip().lower()
    if tn == "upgrade":
        return "upgrade"
    if NC.is_byod(rec):
        return "byod"
    return "new phone" if tn == "port" else "new number"


def has_next_up(rec: dict) -> bool:
    """The Wireless Installment Plan says 'Next36 w/ Next Up Anytime' once
    the line activates ('Pending' before, 'Next36 w/o Next Up' = no)."""
    v = str(rec.get("wireless_ip") or "").lower()
    return "next up" in v and not any(w in v for w in ("w/o", "without", "no next"))


def plan_of(rec: dict) -> str:
    pk = str(rec.get("package") or "").upper()
    return ("premium" if "PREMIUM" in pk else "extra" if "EXTRA" in pk
            else "value" if "VALUE" in pk else "")


def board_line_price(rec: dict, rates: Optional[dict] = None) -> float:
    """Base comp for one SOLD line, the deposit's rates: port $213 ($193
    in-footprint), BYOD port $188 ($168 IF), BYOD on a new number / any
    new-number phone $25, upgrade $30, tablet or wearable $25, Internet Air
    $93 (+$30 with auto bill pay); fiber and unknown products $0. Before
    2026-11-15 every port priced $213 and Air / wearables $25."""
    rates = rates or sow_rates()
    sw, air = rates["wireless"], rates["internet_air"]
    kind = line_kind(rec)
    if kind == "air":
        abp = str(rec.get("abp") or "").strip().upper() == "Y"
        return float(air["activation"]) + (float(air["auto_bill_pay_bonus"]) if abp else 0.0)
    if kind in ("internet", "other"):
        return 0.0
    if kind == "device":
        return float(sw["tablet_wearable_nonbyod"])
    if kind == "upgrade":
        return float(sw["upgrade_voice"])
    if kind == "new number":
        return float(sw["new_line"])
    ported = str(rec.get("tn_type") or "").strip().lower() == "port"
    fp = "INFP" if str(rec.get("if_oof") or "").strip().upper() == "IF" else "OOF"
    if kind == "byod":
        return float(sw["port_byod"][fp]) if ported else float(sw["new_line"])
    return float(sw["port_nonbyod"][fp])


def apps_breakdown(cols, lines, idx: dict, i_od, monday: dt.date, today: dt.date) -> dict:
    """{rep | OFFICE: Counter} over the lines sold Mon..today (what the board
    prices): orders (distinct SPM numbers), apps (port phones + BYODs + Air),
    'new phone' / 'byod' / 'air' / 'device' / 'new number' / 'upgrade',
    nextup, and the phone lines' plan -- premium / extra / value."""
    import collections
    out = collections.defaultdict(collections.Counter)
    spms = collections.defaultdict(set)
    for r in lines:
        od = _parse_date(_c(cols, r, i_od))
        rep = _c(cols, r, idx.get("rep")) if idx.get("rep") is not None else ""
        if not rep or od is None or not (monday <= od <= today):
            continue
        rec = line_rec(cols, r, idx)
        kind = line_kind(rec)
        spm = (_c(cols, r, idx["spm"]) if idx.get("spm") is not None else "") or "%s|%s|%s" % (rep, od, id(r))
        for key in (rep, OFFICE):
            c = out[key]
            spms[key].add(spm)
            c[kind] += 1
            if kind in APP_KINDS:
                c["apps"] += 1
            if kind in PHONE_KINDS:
                if has_next_up(rec):
                    c["nextup"] += 1
                pl = plan_of(rec)
                if pl:
                    c[pl] += 1
    for key, c in out.items():
        c["orders"] = len(spms[key])
    return dict(out)


def name_lines(name: str) -> List[str]:
    """First name on its own line, the rest under it (Carlos: "put part of
    the last name under the first name, so we get more room")."""
    parts = str(name or "").split()
    return [parts[0], " ".join(parts[1:])] if len(parts) > 1 else [str(name or "")]


def badge(n_orders: int, c) -> str:
    apps = int(c.get("apps", 0)) if c else 0
    return "%d order%s · %d app%s" % (n_orders, "" if n_orders == 1 else "s",
                                      apps, "" if apps == 1 else "s")


def tags_html(c) -> str:
    """The WHAT SOLD cell, two lines: what sold, then the add-ons that move
    the payout."""
    c = c or {}
    n = int(c.get("new phone", 0))
    return ("%d new phone%s · %d BYOD · %d Air<br>%d Next Up · %d Premium · %d Extra · %d Value"
            % (n, "" if n == 1 else "s", c.get("byod", 0), c.get("air", 0), c.get("nextup", 0),
               c.get("premium", 0), c.get("extra", 0), c.get("value", 0)))


def reps_extra(n_reps: int, n_apps: int) -> str:
    """The REPS ON THE BOARD card's suffix (renderer extra["reps_extra"]):
    sales per rep = this week's apps over the reps listed."""
    per = ("%.1f" % (n_apps / n_reps)) if n_reps else "—"
    return " " + _SMALL % ("· %s sales per rep (%d app%s this week)"
                           % (per, n_apps, "" if n_apps == 1 else "s"))


# Card colours (the Verizon board's boxes, Carlos 2026-11-15 pm: "make those
# changes with our version equivalent").
_BOX = {"Green": ("#dff3e2", "#1e7d32"), "Yellow": ("#fff3b0", "#8a6d00"),
        "Red": ("#ffd9dc", "#b3261e"), "Grey": ("#eef0f2", "#5b6770")}


def _box(label: str, value: str, color: str = "Grey", min_w: int = 64) -> str:
    bg, fg = _BOX.get(color, _BOX["Grey"])
    return ('<div style="background:%s;color:%s;border-radius:6px;padding:4px 10px;text-align:center;'
            'min-width:%dpx"><div style="font-size:11px;font-weight:600;opacity:.8">%s</div>'
            '<div style="font-size:19px;font-weight:800">%s</div></div>' % (bg, fg, min_w, label, value))


def _boxes(items) -> str:
    return '<div style="display:flex;gap:8px;margin-top:4px">' + "".join(items) + "</div>"


def weeks_card(rows: Optional[Sequence[dict]]) -> str:
    """One coloured box per week ending, oldest first, off
    activation_by_week.rows_from -- the Activation Rate by Rep's 0-30 day
    bands (green 75%+, yellow 65%+, red under); '—' when the source is missing."""
    if not rows:
        return "\u2014"
    from automations.office_metrics.nds_orderlog import _ACT_BANDS
    boxes = []
    for r in rows[-WEEKS:]:
        if r.get("lines"):
            rate = float(r["rate"])
            color = next(c for floor, c in _ACT_BANDS["0-30 Day"] if rate >= floor)
            pct = "%.0f%%" % (100 * rate)
        else:
            color, pct = "Grey", "\u2014"
        boxes.append(_box("WE %d/%d" % (r["we"].month, r["we"].day), pct, color))
    return _boxes(boxes)


def churn_color(pct: float) -> str:
    """The NDS SOW's 0-30 day non-BYOD churn chart (nds_churn.comp
    NONBYOD_0_30): T4 / T3 green, T2 yellow, T1 red."""
    from automations.nds_churn import comp as NCOMP
    tier = NCOMP.tier_for(pct, NCOMP.NONBYOD_0_30)
    return "Green" if tier in (4, 3) else "Yellow" if tier == 2 else "Red"


def churn_card(box: Optional[dict]) -> str:
    """'4.2% 3 of 71 ...' off the NDS CHURN tab's All Wireless box row
    (compute.product_box()['wireless']), the % coloured by the SOW churn
    chart; '—' with no activations / no source."""
    if not box or not box.get("act"):
        return "\u2014"
    act, disc = int(box["act"]), int(box.get("disc") or 0)
    pct = 100.0 * disc / act
    return '<span style="color:%s">%.1f%%</span> %s' % (
        _BOX[churn_color(pct)][1], pct,
        _SMALL % ("%d of %d activated in the last 30 days" % (disc, act)))


def mix_card(off) -> str:
    """The share of this week's apps that are BYOD / Air / Premium / Extra /
    Next Up -- the payout variables (Next Up fills in as lines activate)."""
    off = off or {}
    apps = int(off.get("apps", 0))
    if not apps:
        return "\u2014"
    return _boxes([_box(lab, "%.0f%%" % (100.0 * int(off.get(k, 0)) / apps), "Grey", 72)
                   for lab, k in (("BYOD", "byod"), ("Air", "air"), ("Premium", "premium"),
                                  ("Extra", "extra"), ("Next Up", "nextup"))])


def cards(weeks_rows, churn_box, off=None) -> List[Tuple[str, str]]:
    return [("ACTIVATION RATE BY WEEK-ENDING", weeks_card(weeks_rows)),
            ("0\u201330 DAY CHURN \u00b7 WIRELESS NON-BYOD", churn_card(churn_box)),
            ("APP MIX THIS WEEK", mix_card(off))]


def week_extra(n_reps: int, n_apps: int) -> str:
    """Inside the OFFICE WEEK TOTAL card (the reps card is hidden):
    '· 19 reps · 7.1 sales / rep (134 apps)'."""
    per = ("%.1f" % (n_apps / n_reps)) if n_reps else "\u2014"
    return (' <span style="font-size:15px;color:#5b6770;font-weight:600">\u00b7 %d rep%s \u00b7 %s sales / rep '
            '(%d app%s)</span>' % (n_reps, "" if n_reps == 1 else "s", per, n_apps, "" if n_apps == 1 else "s"))


BREAKDOWN_HEADER = 'WHAT SOLD<br><span class="dd">this week</span>'

# The header (Carlos 2026-11-15 night: "get rid of the NDS leaders and the
# stuff under it (the bottom section) ... call the top portion the NDS
# Revenue Sales Board. Let's maybe make it blue, add in the AT&T logo up
# there, and center it") -- the renderer's brand hook: AT&T blue band, the
# globe + wordmark top-left, the title centred, no footer and no note.
ATT_BLUE = "#00a8e0"          # the wording; the band is black (Carlos 2026-11-15: "background black and the wording blue")
# The globe, drawn inline (no logo file in the repo); sits in the title line.
ATT_GLOBE = ('<svg width="52" height="52" viewBox="0 0 100 100" aria-hidden="true" '
             'style="vertical-align:middle;margin:0 14px 8px 10px">'
             '<defs><clipPath id="attg"><circle cx="50" cy="50" r="47"/></clipPath>'
             '<linearGradient id="attb" x1="0" y1="0" x2="1" y2="1">'
             '<stop offset="0" stop-color="#9fe3ff"/><stop offset="1" stop-color="#00a8e0"/></linearGradient></defs>'
             '<circle cx="50" cy="50" r="47" fill="url(#attb)"/>'
             '<g clip-path="url(#attg)" fill="none" stroke="#fff" stroke-linecap="round">'
             '<path d="M-5 26 Q50 6 105 26" stroke-width="4"/>'
             '<path d="M-5 42 Q50 22 105 42" stroke-width="6"/>'
             '<path d="M-5 59 Q50 39 105 59" stroke-width="8"/>'
             '<path d="M-5 77 Q50 57 105 77" stroke-width="10"/>'
             '<path d="M-5 96 Q50 76 105 96" stroke-width="12"/>'
             '</g></svg>')
ATT_LOGO = ('<div style="display:flex;align-items:center;gap:10px">'
            '<svg width="54" height="54" viewBox="0 0 100 100" aria-hidden="true">'
            '<defs><clipPath id="attg"><circle cx="50" cy="50" r="47"/></clipPath>'
            '<linearGradient id="attb" x1="0" y1="0" x2="1" y2="1">'
            '<stop offset="0" stop-color="#9fe3ff"/><stop offset="1" stop-color="#00a8e0"/></linearGradient></defs>'
            '<circle cx="50" cy="50" r="47" fill="url(#attb)"/>'
            '<g clip-path="url(#attg)" fill="none" stroke="#fff" stroke-linecap="round">'
            '<path d="M-5 26 Q50 6 105 26" stroke-width="4"/>'
            '<path d="M-5 42 Q50 22 105 42" stroke-width="6"/>'
            '<path d="M-5 59 Q50 39 105 59" stroke-width="8"/>'
            '<path d="M-5 77 Q50 57 105 77" stroke-width="10"/>'
            '<path d="M-5 96 Q50 76 105 96" stroke-width="12"/>'
            '</g></svg>'
            '<span style="font-size:30px;font-weight:800;letter-spacing:.02em">AT&amp;T</span></div>')
# Carlos 2026-11-15, next pass: "get rid of the AT&T logo and the AT&T wording
# at the top left, and let's call it 'AT&T [logo] NDS Revenue Sales Board'"
# -- the title line carries the wordmark + globe, nothing top-left.
BRAND = {"title": "AT&amp;T" + ATT_GLOBE + "NDS Revenue Sales Board", "color": "#000000",
         "fg": ATT_BLUE, "logo": ""}


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
