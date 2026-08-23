"""BOX campaign block for Ryan McSpadden + Roshan Amin — Tableau pulls.

Sources (all in the B2BBOXEnergyTracker workbook on the sci site; probed
2026-08-23):

  BoxSalesMetrics → 'Sales Metrics' crosstab, week-pinned. Owner × Rep grid;
      an owner's team total is the Rep Name == 'Total' row, the national line
      is Owner Name == 'Grand Total'. Columns: Complete Sales / Selling Rep
      Count / Total Rep Count / Sales/ Rep / Sales ELE / Sales Gas /
      Avg kWH/Sale. Pulled TWICE — current week and prior week — because the
      view's saved week lags badly; the pin is '?Sale Date Weekending=<ISO
      Sunday>' (the caption verified live: cur vs prior pins return different
      Grand Totals, and the BOX daily-tracker spec documents the same caption,
      see org_sales_board/section_pull.py BOX_SPEC).
  BoxDailyTracker → 'Daily Tracker Metrics' crosstab, same week pin. Carries
      a per-owner Rank column (verified 2026-08-23: Roshan #2, Ryan #4 of 10)
      — the literal "Rank on the Tracker", no computing needed. If it ever
      disappears the rank is OMITTED, not computed: the Sales Metrics
      crosstab carries only a subset of the tracker's owners, so a position
      computed from it would be wrong rather than approximate.
  Bulletin → the "Top B2B Box Energy Reps by Sales Volume" board. Per-rep
      rows with an Owner Name column plus the 30–60-day acceptance rate and
      0–45-day drop rate; the owner's number is the sales-weighted average of
      their reps' rates. TOP-20 CAVEAT: the view only carries the org's top
      20 reps, so the average covers the manager's reps who made that list.
  BOX order log → the team ALLEXP view via box_order_log's own machinery
      (window hook releases the pinned ID filters + forces the date window;
      clean.load collapses transitions to one row per sale). Reuses today's
      shared box_order_log_all_<date>.csv when another report already pulled
      it. Gives Accepted-by-Supplier-this-week and the payout-style
      Still Open / Pending count.
  DropsTracker → 'Drops Pull' crosstab, UNPINNED. Pinning '?Dropped Date
      Weekending=<ISO>' breaks the load outright (probed 2026-08-23: the
      crosstab dialog opens empty on every attempt), while the bare view
      loads fine and is saved scoped to the current week. One row per
      dropped sale with an 'Owner & Office' column and a 'Dropped Date' we
      filter to the Mon-Sun window client-side — so a drift in the view's
      saved scope can only ever undercount, never leak another week in.

Weeks are Mon-Sun and stamped under their SUNDAY (run.week_sunday). Values
are display TEXT per layout.py: counts plain ints, Sales per Rep one decimal,
percents int + '%', kWh with thousands separator, vs-prior signed ('+18%').

A sub-pull that fails (after download_crosstab_patchright's own 3 attempts)
is logged and its tuples omitted — partial data beats none.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import List
from urllib.parse import quote

from automations.org_campaign_metrics import layout as L

BASE = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
        "B2BBOXEnergyTracker/")

# org Focus Report picker spelling -> match token. The tracker spells them
# 'RYAN MCSPADDEN [Highline Management Team, Inc. 2]' / 'Roshan Ahmad' /
# 'ROSHAN AHMAD [Sapphire Marketing, Inc]' depending on the view, so match a
# case-insensitive fragment that survives every spelling.
MANAGERS = (
    ("Ryan McSpadden", "mcspadden"),
    ("Roshan Amin", "roshan"),
)

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"

SALES_METRICS_SHEET = "Sales Metrics"
DAILY_METRICS_SHEET = "Daily Tracker Metrics"
# The Bulletin's per-rep grid (Rep Name | Owner Name | Rank | Complete Sales |
# Sales ELE | Sales Gas | Acceptance Rate (30-60 day) | Churn Rate (0-45 Days));
# its sibling 'Top 20 Reps metrics' is a single org-wide summary row.
BULLETIN_SHEET = "Top 20 Reps"
DROPS_SHEET = "Drops Pull"

WEEK_PIN_FIELD = "Sale Date Weekending"       # this workbook's own caption
# (No pin for DropsTracker — 'Dropped Date Weekending' in the URL kills the
# load; see _drops.)


# --------------------------------------------------------------- helpers

def _week_sunday(d):
    """Sunday of the Mon-Sun week containing d (mirrors run.week_sunday)."""
    return d + dt.timedelta(days=6 - d.weekday())


def _num(s):
    s = str(s or "").strip().replace(",", "").replace("%", "").replace("$", "")
    if not s or s in ("-", "—"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _int_text(v):
    return str(int(round(v)))


def _thousands_text(v):
    return "{:,}".format(int(round(v)))


def _spr_text(v):
    return "{:.1f}".format(v)


def _pct_text(v):
    return "{}%".format(int(round(v)))


def _signed_pct_text(v):
    return "{:+d}%".format(int(round(v)))


def _col_exact(header, label):
    want = " ".join(str(label).split()).lower()
    for i, h in enumerate(header):
        if " ".join(str(h or "").split()).lower() == want:
            return i
    return None


def _col_fuzzy(header, *needles):
    """First column whose header contains all needles (case-insensitive)."""
    for i, h in enumerate(header):
        low = " ".join(str(h or "").split()).lower()
        if low and all(n in low for n in needles):
            return i
    return None


def _cell(row, i):
    return row[i] if (i is not None and i < len(row)) else ""


def _match_manager(owner_raw):
    low = str(owner_raw or "").lower()
    for mgr, token in MANAGERS:
        if token in low:
            return mgr
    return None


def _pinned(view, field, sunday):
    return "%s%s?%s=%s&:refresh=yes" % (
        BASE, view, quote(field), sunday.isoformat())


def _download(page, url, sheet, dest, log):
    from automations.shared.tableau_patchright import (
        download_crosstab_patchright)
    download_crosstab_patchright(url, sheet, dest, verbose=False, page=page)
    return dest


def _read(path):
    from automations.alphalete_org_report.opt_nds import _read_tab_csv
    return _read_tab_csv(path)


# --------------------------------------------------------------- sub-pulls

def _sales_metrics(page, sunday, tag, log):
    """-> (per-manager metrics dict, national dict) for one pinned week.

    per-manager: {manager: {complete, selling, total_reps, spr, ele, gas,
    avg_kwh}} (floats/None); national: {spr, avg_kwh} off the Grand Total row.
    """
    dest = OUTPUT_DIR / ("org_campaign_box_sales_metrics_%s.csv" % tag)
    _download(page, _pinned("BoxSalesMetrics", WEEK_PIN_FIELD, sunday),
              SALES_METRICS_SHEET, dest, log)
    rows = _read(dest)
    if not rows:
        raise RuntimeError("Sales Metrics export came back empty")
    header = rows[0]
    c_owner = _col_exact(header, "Owner Name")
    c_rep = _col_exact(header, "Rep Name")
    def _first(*idxs):
        for i in idxs:
            if i is not None:
                return i
        return None

    cols = {
        "complete":   _col_exact(header, "Complete Sales"),
        "selling":    _col_exact(header, "Selling Rep Count"),
        "total_reps": _col_exact(header, "Total Rep Count"),
        "spr":        _first(_col_exact(header, "Sales/ Rep"),
                             _col_fuzzy(header, "sales", "/", "rep")),
        "ele":        _col_exact(header, "Sales ELE"),
        "gas":        _col_exact(header, "Sales Gas"),
        "avg_kwh":    _first(_col_exact(header, "Avg kWH/Sale"),
                             _col_fuzzy(header, "avg", "kwh")),
    }
    if c_owner is None or c_rep is None or cols["complete"] is None:
        raise RuntimeError("Sales Metrics header changed: %r" % (header,))
    per, national = {}, {}
    for r in rows[1:]:
        owner = _cell(r, c_owner).strip()
        rep = _cell(r, c_rep).strip()
        if not owner or rep.lower() not in ("total", "total general"):
            continue                       # team-total rows only
        vals = {k: _num(_cell(r, i)) for k, i in cols.items()}
        if owner.lower() in ("grand total", "total general", "total"):
            national = {"spr": vals["spr"], "avg_kwh": vals["avg_kwh"]}
            continue
        mgr = _match_manager(owner)
        if mgr:
            per[mgr] = vals
    log("  [box] sales metrics WE %s: %s; national spr=%s avg_kwh=%s" % (
        sunday.isoformat(),
        {m: v.get("complete") for m, v in per.items()},
        national.get("spr"), national.get("avg_kwh")))
    return per, national


def _tracker_rank(page, sunday, log):
    """{manager: rank int} off the Daily Tracker Metrics crosstab's Rank
    column; raises if the column is gone (collect logs it as a miss)."""
    dest = OUTPUT_DIR / "org_campaign_box_daily_metrics.csv"
    _download(page, _pinned("BoxDailyTracker", WEEK_PIN_FIELD, sunday),
              DAILY_METRICS_SHEET, dest, log)
    rows = _read(dest)
    if not rows:
        raise RuntimeError("Daily Tracker Metrics export came back empty")
    header = rows[0]
    c_rank = _col_exact(header, "Rank")
    c_owner = _col_exact(header, "Owner Name")
    if c_rank is None or c_owner is None:
        raise RuntimeError("Daily Tracker Metrics header changed: %r"
                           % (header,))
    out = {}
    for r in rows[1:]:
        mgr = _match_manager(_cell(r, c_owner))
        rank = _num(_cell(r, c_rank))      # 'Grand Total' chrome row -> None
        if mgr and rank is not None:
            out[mgr] = int(rank)
    log("  [box] tracker rank: %s" % out)
    return out


def _bulletin_rates(page, log):
    """{manager: (acceptance_pct, drop_pct, rep_count)} — sales-weighted
    average of the manager's reps on the Bulletin's top-20 board. The 'drop'
    column is captioned 'Churn Rate (0-45 Days) At Rep Level' on the view."""
    dest = OUTPUT_DIR / "org_campaign_box_bulletin.csv"
    _download(page, BASE + "Bulletin?:refresh=yes", BULLETIN_SHEET, dest, log)
    rows = _read(dest)
    if not rows:
        raise RuntimeError("Bulletin export came back empty")
    header = rows[0]
    c_owner = _col_fuzzy(header, "owner", "name")
    c_weight = _col_exact(header, "Complete Sales")
    c_acc = _col_fuzzy(header, "accept")
    c_drop = _col_fuzzy(header, "churn")
    if c_drop is None:
        c_drop = _col_fuzzy(header, "drop")
    if c_owner is None or c_acc is None or c_drop is None:
        raise RuntimeError("Bulletin header changed: %r" % (header,))
    agg = {}          # mgr -> [w_acc, sum_w*acc, w_drop, sum_w*drop, n]
    for r in rows[1:]:
        mgr = _match_manager(_cell(r, c_owner))
        if not mgr:
            continue
        acc = _num(_cell(r, c_acc))
        drop = _num(_cell(r, c_drop))
        if acc is None and drop is None:
            continue
        w = _num(_cell(r, c_weight)) if c_weight is not None else None
        w = w if w and w > 0 else 1.0      # no weight -> plain mean
        a = agg.setdefault(mgr, [0.0, 0.0, 0.0, 0.0, 0])
        a[4] += 1
        if acc is not None:
            a[0] += w
            a[1] += w * acc
        if drop is not None:
            a[2] += w
            a[3] += w * drop
    out = {}
    for mgr, (w_a, s_a, w_d, s_d, n) in agg.items():
        out[mgr] = ((s_a / w_a) if w_a else None,
                    (s_d / w_d) if w_d else None, n)
    log("  [box] bulletin rates (top-20 reps only): %s" % {
        m: ("%.1f%%" % v[0] if v[0] is not None else None,
            "%.1f%%" % v[1] if v[1] is not None else None,
            "%d reps" % v[2]) for m, v in out.items()})
    return out


def _order_log(page, today, monday, sunday, log):
    """{manager: (accepted_this_week, still_open)} off the cleaned team
    ALLEXP order log. Reuses today's shared export when it exists (per_office
    and run_owner write/read the same file)."""
    from automations.box_order_log import clean, payout, window
    from automations.box_order_log import per_office
    shared = OUTPUT_DIR / ("box_order_log_all_%s.csv" % today.isoformat())
    if shared.exists():
        log("  [box] reusing today's shared order-log export %s" % shared.name)
    else:
        start, end = window.default_window(today)
        hook = window.date_window_hook(start, end, verbose=False)
        _download_hooked(page, per_office.TEAM_VIEW_URL,
                         per_office.TEAM_CROSSTAB_SHEET, shared, hook)
    sales, stats = clean.load(shared)
    log("  [box] order log: %s sales after collapse (raw %s rows)"
        % (stats.get("sales"), stats.get("raw_rows")))
    out = {}
    for mgr, _tok in MANAGERS:
        accepted = still_open = 0
        for s in sales:
            if _match_manager(s.fields.get(clean.OWNER_OFFICE_COL, "")) != mgr:
                continue
            if (s.status in payout.POSTED_STATUSES and s.accepted_date
                    and monday <= s.accepted_date <= sunday):
                accepted += 1
            elif (s.status and s.status not in payout.POSTED_STATUSES
                    and s.status not in payout.CANCEL_STATUSES):
                still_open += 1            # payout.py's 'pending' notion
        out[mgr] = (accepted, still_open)
    log("  [box] order log per manager (accepted wk, still open): %s" % out)
    return out


def _download_hooked(page, url, sheet, dest, hook):
    from automations.shared.tableau_patchright import (
        download_crosstab_patchright)
    download_crosstab_patchright(url, sheet, dest, verbose=False, page=page,
                                 pre_export=hook)


def _drops(page, monday, sunday, log):
    """{manager: drop count} — DropsTracker rows whose Dropped Date falls in
    the Mon-Sun window.

    UNPINNED on purpose: '?Dropped Date Weekending=<ISO>' breaks the view
    load outright (2026-08-23: crosstab dialog empty on 3/3 attempts) while
    the bare view loads fine, saved scoped to the current week. The Dropped
    Date column is REQUIRED — without it a scope drift on the saved view
    would silently count other weeks' drops, which is worse than a logged
    miss."""
    dest = OUTPUT_DIR / "org_campaign_box_drops.csv"
    _download(page, BASE + "DropsTracker?:refresh=yes", DROPS_SHEET, dest, log)
    rows = _read(dest)
    if not rows:
        raise RuntimeError("Drops Pull export came back empty")
    header = rows[0]
    c_owner = _col_fuzzy(header, "owner")       # 'Owner & Office'
    c_date = _col_fuzzy(header, "dropped", "date")
    if c_owner is None or c_date is None:
        raise RuntimeError("Drops Pull header changed: %r" % (header,))
    out = {m: 0 for m, _t in MANAGERS}
    for r in rows[1:]:
        mgr = _match_manager(_cell(r, c_owner))
        if not mgr:
            continue
        d = _parse_date(_cell(r, c_date))
        if d is None or not (monday <= d <= sunday):
            continue
        out[mgr] += 1
    log("  [box] drops this week (%s..%s): %s"
        % (monday.isoformat(), sunday.isoformat(), out))
    return out


def _parse_date(value):
    value = str(value or "").strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return dt.datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


# --------------------------------------------------------------- collect

def collect(page, today=None, log=print):
    """-> (values, goals_seed) for the Campaign Log upsert.

    page is a live tableau_patchright session Page (the orchestrator owns the
    browser). Every sub-pull is independent: a failure is logged and its
    tuples omitted, the rest still stamp.
    """
    today = today or dt.date.today()
    wk_cur = _week_sunday(today)
    wk_prior = wk_cur - dt.timedelta(days=7)
    monday = wk_cur - dt.timedelta(days=6)
    slots = L.slots_by_label("box")
    values: List[tuple] = []
    goals_seed: List[tuple] = []
    misses: List[str] = []

    def _run(name, fn):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 — partial data beats none
            log("  [box] !! %s pull failed: %s: %s"
                % (name, type(e).__name__, str(e)[:200]))
            misses.append(name)
            return None

    def put(mgr, week, label, text):
        if text is None or text == "":
            return
        values.append((mgr, week.isoformat(), slots[label], text))

    # 1) Sales Metrics — current week
    cur = _run("sales_metrics_current",
               lambda: _sales_metrics(page, wk_cur, "cur", log))
    cur_complete = {}
    if cur:
        per, national = cur
        for mgr, v in per.items():
            if v.get("total_reps") is not None:
                put(mgr, wk_cur, "Total Rep Count on Tableau",
                    _int_text(v["total_reps"]))
            if v.get("selling") is not None:
                put(mgr, wk_cur, "Selling Rep Count", _int_text(v["selling"]))
            if v.get("complete") is not None:
                cur_complete[mgr] = v["complete"]
                put(mgr, wk_cur, "Complete Sales", _int_text(v["complete"]))
            if v.get("spr") is not None:
                put(mgr, wk_cur, "Sales per Rep", _spr_text(v["spr"]))
            if v.get("ele") is not None:
                put(mgr, wk_cur, "ELE Sales", _int_text(v["ele"]))
            if v.get("gas") is not None:
                put(mgr, wk_cur, "Gas Sales", _int_text(v["gas"]))
            if v.get("avg_kwh") is not None:
                put(mgr, wk_cur, "Avg kWh per Sale",
                    _thousands_text(v["avg_kwh"]))
        # national benchmark rows repeat per manager (each has their own zone)
        for mgr, _tok in MANAGERS:
            if national.get("spr") is not None:
                put(mgr, wk_cur, "National Sales per Rep",
                    _spr_text(national["spr"]))
                goals_seed.append((mgr, slots["Sales per Rep"],
                                   _spr_text(national["spr"])))
            if national.get("avg_kwh") is not None:
                put(mgr, wk_cur, "National Avg kWh per Sale",
                    _thousands_text(national["avg_kwh"]))

    # 2) Sales Metrics — prior week (Complete Sales + SPR under that Sunday,
    #    and the vs-Prior delta on the current week)
    prior = _run("sales_metrics_prior",
                 lambda: _sales_metrics(page, wk_prior, "prior", log))
    if prior:
        per_p, _nat_p = prior
        for mgr, v in per_p.items():
            if v.get("complete") is not None:
                put(mgr, wk_prior, "Complete Sales", _int_text(v["complete"]))
            if v.get("spr") is not None:
                put(mgr, wk_prior, "Sales per Rep", _spr_text(v["spr"]))
            pc = v.get("complete")
            cc = cur_complete.get(mgr)
            if pc and cc is not None:
                put(mgr, wk_cur, "vs Prior Week",
                    _signed_pct_text((cc / pc - 1.0) * 100.0))

    # 3) Rank on the Tracker. No compute-from-Sales-Metrics fallback on
    #    purpose: that crosstab carries only a subset of the tracker's owners
    #    (5 of 10 on 2026-08-23), so a position computed from it would be
    #    wrong, not just approximate — omitting is the honest miss.
    ranks = _run("tracker_rank", lambda: _tracker_rank(page, wk_cur, log))
    for mgr, rank in (ranks or {}).items():
        put(mgr, wk_cur, "Rank on the Tracker", str(rank))

    # 4) Bulletin — acceptance / drop rates (top-20 reps, sales-weighted)
    rates = _run("bulletin_rates", lambda: _bulletin_rates(page, log))
    for mgr, (acc, drop, _n) in (rates or {}).items():
        if acc is not None:
            put(mgr, wk_cur, "Acceptance Rate (30–60 Day)", _pct_text(acc))
        if drop is not None:
            put(mgr, wk_cur, "Drop Rate (0–45 Day)", _pct_text(drop))

    # 5) Order log — accepted this week + still open / pending
    ol = _run("order_log",
              lambda: _order_log(page, today, monday, wk_cur, log))
    for mgr, (accepted, still_open) in (ol or {}).items():
        put(mgr, wk_cur, "Accepted by Supplier (wk)", str(accepted))
        put(mgr, wk_cur, "Still Open / Pending", str(still_open))

    # 6) Drops this week
    drops = _run("drops", lambda: _drops(page, monday, wk_cur, log))
    for mgr, n in (drops or {}).items():
        put(mgr, wk_cur, "Drops This Week", str(n))

    if misses:
        log("  [box] completed with misses: %s" % ", ".join(misses))
    log("  [box] %d values, %d goal seeds (week %s)"
        % (len(values), len(goals_seed), wk_cur.isoformat()))
    return values, goals_seed
