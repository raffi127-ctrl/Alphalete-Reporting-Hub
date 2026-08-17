"""Pull one rep's Due Diligence numbers from Tableau.

Reuses the views the other reports already maintain (no new scraping code):
  * new INT / wireless weekly  -> Product Sales weekly view, 1 pull per week
  * NI / wireless churn         -> the all-team churn views, sliced to the rep
  * 0-30 / 30-60 cancel rate    -> the Metrics workbook (rep row)

All pulls run over ONE tableau_session page so a request is a single login.
Every source is wrapped so a partial failure still returns what we have and
records the gap (Megan's flag-unfilled-cells rule) instead of crashing.

Heavy deps (opt_phase -> patchright) are imported lazily so this module loads
without a browser stack; only the actual pull needs it.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from . import config as C

PERIODS = ("0-30", "30", "60", "90")

# --- lazy handles to the maintained Tableau helpers -------------------------
_OPT = None


def _opt():
    global _OPT
    if _OPT is None:
        from automations.recruiting_report import opt_phase as _o
        _OPT = _o
    return _OPT


def _norm(s) -> str:
    return _opt()._norm(s)


# --------------------------------------------------------------------------
@dataclass
class TableDD:
    """One product side of the report (New Internet OR Wireless)."""
    weekly: Dict[dt.date, Optional[int]] = field(default_factory=dict)
    avg_8wk: Optional[float] = None
    avg_recent: Optional[float] = None
    cancel_0_30: str = ""
    cancel_30_60: str = ""
    churn: Dict[str, str] = field(default_factory=dict)   # "0-30"/"30"/"60"/"90" -> "1.47%"


@dataclass
class RepDD:
    rep: str
    icd: str = ""                  # ICD the requester named (routes the tab)
    matched_rep: str = ""
    owner: str = ""                # ICD owner as it appears in the sales data
    weeks: List[dt.date] = field(default_factory=list)    # newest-first
    new_int: TableDD = field(default_factory=TableDD)
    wireless: TableDD = field(default_factory=TableDD)
    start_date: str = ""
    gaps: List[str] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return bool(self.matched_rep)


# --------------------------------------------------------------------------
def _most_recent_sunday(today: Optional[dt.date] = None) -> dt.date:
    today = today or dt.date.today()
    return today - dt.timedelta(days=(today.weekday() + 1) % 7)


def recent_sundays(n: int, anchor: Optional[dt.date] = None) -> List[dt.date]:
    """The n most-recent week-ending Sundays, newest first."""
    end = _most_recent_sunday(anchor)
    return [end - dt.timedelta(days=7 * i) for i in range(n)]


def _avg(vals: List[Optional[int]]) -> Optional[float]:
    """Mean of the non-blank weekly counts (blanks skipped, matching the
    Sheet's AVERAGE() which ignores empty cells). None if nothing to average."""
    nums = [v for v in vals if v is not None]
    if not nums:
        return None
    return round(sum(nums) / len(nums), 2)


def _read_utf16_tsv(path: Path) -> List[List[str]]:
    raw = Path(path).read_text(encoding="utf-16")
    return [ln.split("\t") for ln in raw.splitlines() if ln.strip()]


def _pct_to_float(s: str) -> Optional[float]:
    s = (s or "").strip().replace("%", "").replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _owner_for_rep(path: Path, rep_norm: str) -> str:
    """The ICD 'Owner Name' (col 0) for the rep (col 1) in a product crosstab —
    used to route the rep to their ICD tab. '' if not found."""
    rows = _read_utf16_tsv(path)
    for r in rows[1:]:
        if len(r) > 1 and _norm(r[1]) == rep_norm:
            return (r[0] or "").strip()
    return ""


def _sum_products(values: Dict[str, int], match: str) -> int:
    """Sum every product-type whose name contains `match` (case-insensitive)."""
    total = 0
    for ptype, count in values.items():
        if match in str(ptype).lower():
            try:
                total += int(count)
            except (TypeError, ValueError):
                continue
    return total


def _week(view_url: str, sun: dt.date) -> str:
    """Week-filter a view URL — the ONLY place DD appends a week filter.

    opt_phase._week_url() joins its filter with a literal '?', so a URL that
    already carries a query (Tableau's UI copies them with '?:iid=1') yields two
    '?' and Tableau silently drops the filter. Strip the query here rather than
    at each source, so this stays impossible even if another view is
    week-filtered later. Only the product view is filtered today — the metrics
    and churn views are deliberately pulled bare (opt_phase.py: their multi-week
    measures get truncated by a week filter), so they never come through here.
    """
    return _opt()._week_url(C._bare_view(view_url), sun)


def _dl(view_url: str, sheet: str, out: Path, page, verbose: bool,
        gaps: List[str], label: str) -> bool:
    """Download a crosstab; on failure record a gap and return False so the
    rest of the report still assembles."""
    from automations.shared.tableau_patchright import download_crosstab_patchright
    try:
        download_crosstab_patchright(view_url, sheet, out, verbose=verbose, page=page)
        return out.exists()
    except Exception as e:   # noqa: BLE001 — a bad source must not sink the report
        gaps.append(f"{label}: pull failed ({type(e).__name__}: {str(e)[:120]})")
        return False


def _parse_metrics_rep(path: Path, rep_norm: str,
                       cancel_field: str, activation_field: str) -> Optional[dict]:
    """Read the rep's row from a Metrics crosstab -> {"0-30": cancel,
    "30-60": 100 - activation}. None if the view has no 'Rep Name' column
    (not broken out by rep) or the rep isn't in it — caller flags the gap."""
    rows = _read_utf16_tsv(path)
    if not rows:
        return None
    headers = [_norm(h) for h in rows[0]]
    rep_col = next((i for i, h in enumerate(headers) if h == "rep name"), None)
    if rep_col is None:
        return None
    cancel_i = next((i for i, h in enumerate(headers) if h == _norm(cancel_field)), None)
    act_i = next((i for i, h in enumerate(headers) if h == _norm(activation_field)), None)
    for r in rows[1:]:
        if len(r) <= rep_col:
            continue
        if _norm(r[rep_col]) != rep_norm:
            continue
        cancel = (r[cancel_i].strip() if cancel_i is not None and cancel_i < len(r) else "")
        act = (r[act_i].strip() if act_i is not None and act_i < len(r) else "")
        out = {"0-30": cancel, "30-60": ""}
        act_f = _pct_to_float(act)
        if act_f is not None:
            out["30-60"] = f"{round(100 - act_f, 1)}%"
        return out
    return None


def _has_rep_column(path: Path) -> bool:
    """True when the crosstab is actually broken out by rep.

    A source view can silently COLLAPSE to ICD level — the base Metrics view did
    around WE 8.09 2026, dropping 'Rep Name' — and then `_parse_metrics_rep`
    returns None for every rep alike. Read per-rep that looks identical to "this
    rep had no sales", so a whole column of the report goes blank with nobody
    told. Checking the header once separates "the view broke" (loud) from "this
    rep isn't in it" (normal). [[project_metrics-internet-needs-expanded-custom-view]]
    """
    try:
        rows = _read_utf16_tsv(Path(path))
    except Exception:
        return False
    return bool(rows) and any(_norm(h) == "rep name" for h in rows[0])


def _rep_churn(path: Path, rep_norm: str) -> Dict[str, str]:
    """Per-period churn % for the rep from an all-team churn crosstab."""
    from automations.new_internet_churn import pull as churn_pull
    parsed = churn_pull.parse(path)          # {"reps": {Rep Name: {period: {pct,...}}}}
    for name, periods in parsed.get("reps", {}).items():
        if _norm(name) != rep_norm:
            continue
        return {p: periods[p].get("pct", "") for p in PERIODS if p in periods}
    return {}


# --------------------------------------------------------------------------
def gather_rep_dd(rep_name: str, *, icd: str = "", weeks: int = None,
                  recent: int = None, anchor: Optional[dt.date] = None, page=None,
                  verbose: bool = False) -> RepDD:
    """Assemble one rep's Due Diligence numbers. Opens its own tableau_session
    unless `page` is supplied (the watcher reuses one page across requests).
    `icd` is the ICD/owner the requester named — used to route the Sheet tab
    and to cross-check the owner the sales data reports."""
    weeks = weeks or C.WEEKS
    recent = recent or C.RECENT_WEEKS
    rep_norm = _norm(rep_name)
    dd = RepDD(rep=rep_name.strip(), icd=icd.strip())
    dd.weeks = recent_sundays(weeks, anchor)
    C.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if page is None:
        from automations.shared.tableau_patchright import tableau_session
        with tableau_session(headless=True, verbose=verbose) as p:
            _gather_over_page(dd, rep_name, rep_norm, weeks, recent, p, verbose)
    else:
        _gather_over_page(dd, rep_name, rep_norm, weeks, recent, page, verbose)
    return dd


def _gather_over_page(dd: RepDD, rep_name: str, rep_norm: str, weeks: int,
                      recent: int, page, verbose: bool) -> None:
    opt = _opt()
    tmp = C.OUTPUT_DIR
    product_url, product_sheet = C.product_source()

    # 1) Weekly new INT + wireless — one product-sales pull per week ----------
    ni_weekly: Dict[dt.date, Optional[int]] = {}
    wl_weekly: Dict[dt.date, Optional[int]] = {}
    for sun in dd.weeks:
        out = tmp / f"product_{sun.isoformat()}.csv"
        url = _week(product_url, sun)
        if not _dl(url, product_sheet, out, page, verbose, dd.gaps,
                   f"product sales {sun.isoformat()}"):
            ni_weekly[sun] = None
            wl_weekly[sun] = None
            continue
        reps = opt.parse_personal_production(out)      # {norm rep: {owner, values}}
        rep_entry = reps.get(rep_norm)
        if rep_entry is None:
            ni_weekly[sun] = 0                          # absent = no qualifying sales
            wl_weekly[sun] = 0
            continue
        if not dd.matched_rep:
            dd.matched_rep = rep_entry.get("owner", rep_name)
            if not dd.owner:
                dd.owner = _owner_for_rep(out, rep_norm)
        vals = rep_entry.get("values", {})
        ni_weekly[sun] = _sum_products(vals, C.NI_PRODUCT_MATCH)
        wl_weekly[sun] = _sum_products(vals, C.WL_PRODUCT_MATCH)

    dd.new_int.weekly = ni_weekly
    dd.wireless.weekly = wl_weekly
    ordered = dd.weeks
    recent_set = set(ordered[:recent])
    dd.new_int.avg_8wk = _avg([ni_weekly[s] for s in ordered])
    dd.new_int.avg_recent = _avg([ni_weekly[s] for s in ordered if s in recent_set])
    dd.wireless.avg_8wk = _avg([wl_weekly[s] for s in ordered])
    dd.wireless.avg_recent = _avg([wl_weekly[s] for s in ordered if s in recent_set])

    if not dd.matched_rep:
        dd.gaps.append(f"rep '{rep_name}' not found in the last {weeks} weeks of "
                       f"Product Sales — check spelling / alias")
    elif dd.icd and dd.owner and _norm(dd.icd) not in _norm(dd.owner) \
            and _norm(dd.owner) not in _norm(dd.icd):
        dd.gaps.append(f"heads up: you named ICD '{dd.icd}' but the sales data "
                       f"lists this rep under '{dd.owner}'")

    # 2) Cancel rates (Metrics workbook, rep row) ----------------------------
    ni_url, ni_sheet = C.metrics_ni_source()
    ni_metrics = tmp / "metrics_ni.csv"
    if _dl(ni_url, ni_sheet, ni_metrics, page, verbose, dd.gaps, "NI metrics"):
        m = _parse_metrics_rep(ni_metrics, rep_norm,
                               C.METRIC_NI_CANCEL_0_30, C.METRIC_NI_ACT_30_60)
        if m:
            dd.new_int.cancel_0_30 = m["0-30"]
            dd.new_int.cancel_30_60 = m["30-60"]
        elif dd.matched_rep:
            dd.gaps.append("NI cancel rate: rep not found in the Metrics view")

    wl_url, wl_sheet = C.metrics_wl_source()
    wl_metrics = tmp / "metrics_wl.csv"
    if _dl(wl_url, wl_sheet, wl_metrics, page, verbose, dd.gaps, "wireless metrics"):
        m = _parse_metrics_rep(wl_metrics, rep_norm,
                               C.METRIC_WL_CANCEL_0_30, C.METRIC_WL_ACT_30_60)
        if m:
            dd.wireless.cancel_0_30 = m["0-30"]
            dd.wireless.cancel_30_60 = m["30-60"]

    # 3) Churn (all-team views, sliced to the rep) ---------------------------
    cni_url, cni_sheet = C.churn_ni_source()
    ni_churn = tmp / "churn_ni.csv"
    if _dl(cni_url, cni_sheet, ni_churn, page, verbose, dd.gaps, "NI churn"):
        dd.new_int.churn = _rep_churn(ni_churn, rep_norm)
        if not dd.new_int.churn:
            dd.gaps.append("NI churn: rep not found in the all-team churn view")

    cwl_url, cwl_sheet = C.churn_wl_source()
    wl_churn = tmp / "churn_wl.csv"
    if _dl(cwl_url, cwl_sheet, wl_churn, page, verbose, dd.gaps, "wireless churn"):
        dd.wireless.churn = _rep_churn(wl_churn, rep_norm)

    # 4) Start date / first day of sales — from the '_first_sale' map (backfilled
    #    from the full order history, topped up nightly). Flag only a real miss.
    try:
        from . import first_sale as _fs
        dd.start_date = _fs.start_date_for(rep_norm, _fs.load_map())
    except Exception as e:                       # noqa: BLE001
        dd.gaps.append(f"start date: lookup failed ({type(e).__name__})")
    if not dd.start_date and dd.matched_rep:
        dd.gaps.append("start date: no logged sale found for this rep in the "
                       "order history")


# --------------------------------------------------------------------------
# TEAM MODE — pull a whole team (leader + reps) over ONE set of crosstabs.
# --------------------------------------------------------------------------
def _match_name(typed: str, roster_norm: dict):
    """Resolve a loosely-typed rep name to a roster key — SAFELY.

    Order: exact norm → token-subset (every typed word is a word of the
    candidate, e.g. 'David Becerra' -> 'David Becerra Amador') → a careful fuzzy
    step that requires the SURNAME to match and the first name to be close
    ('Ilya rezaee' -> 'Iliya Rezaee Nia', 'Bas Elhassan' -> 'Basil Elhassan').
    It will NOT match a different first name onto the same surname
    ('Corrieonna Johnson' -> 'Zoria Johnson' is rejected). Returns None (flag it)
    rather than guess a wrong rep. `roster_norm` is {normalized: display}."""
    import difflib
    tn = _norm(typed)
    if tn in roster_norm:
        return tn

    def words(s):
        return str(s).lower().replace("-", " ").split()
    tw = words(typed)
    tset = set(tw)
    # token-subset: every typed word is one of the candidate's words
    subset = [k for k in roster_norm if tset and tset.issubset(set(words(roster_norm[k])))]
    if len(subset) == 1:
        return subset[0]
    if len(subset) > 1:                              # ambiguous — don't guess
        return None
    if len(tw) < 2:                                  # a lone token is too risky to fuzzy
        return None
    t_first, t_last = tw[0], tw[-1]
    cands = []
    for k, disp in roster_norm.items():
        cw = words(disp)
        if t_last not in cw:                         # SURNAME must be present
            continue
        c_first = cw[0]
        if (t_first == c_first or t_first in c_first or c_first in t_first
                or difflib.SequenceMatcher(None, t_first, c_first).ratio() >= 0.8):
            cands.append(k)
    return cands[0] if len(cands) == 1 else None


def _cache_dir(anchor=None) -> Path:
    """Today's harvest cache dir. A nightly harvest_dd() populates it; gather_team
    reads it when complete so a /dd is instant instead of an 8-min live pull."""
    return C.OUTPUT_DIR / "cache" / dt.date.today().isoformat()


def _team_paths(d: Path, wk_order) -> dict:
    return {"product": {s: d / f"product_{s.isoformat()}.csv" for s in wk_order},
            "mni": d / "metrics_ni.csv", "mwl": d / "metrics_wl.csv",
            "cni": d / "churn_ni.csv", "cwl": d / "churn_wl.csv"}


def _cache_complete(d: Path, wk_order) -> bool:
    p = _team_paths(d, wk_order)
    files = list(p["product"].values()) + [p["mni"], p["mwl"], p["cni"], p["cwl"]]
    return all(f.exists() and f.stat().st_size > 0 for f in files)


def _download_team_files(d: Path, wk_order, page, verbose, gaps) -> dict:
    """Download the shared crosstabs (8 weekly product + metrics + churn) to `d`."""
    d.mkdir(parents=True, exist_ok=True)
    opt = _opt()
    product_url, product_sheet = C.product_source()
    p = _team_paths(d, wk_order)
    for sun in wk_order:
        _dl(_week(product_url, sun), product_sheet, p["product"][sun],
            page, verbose, gaps, f"product {sun.isoformat()}")
    _dl(*C.metrics_ni_source(), p["mni"], page, verbose, gaps, "NI metrics")
    _dl(*C.metrics_wl_source(), p["mwl"], page, verbose, gaps, "WL metrics")
    _dl(*C.churn_ni_source(), p["cni"], page, verbose, gaps, "NI churn")
    _dl(*C.churn_wl_source(), p["cwl"], page, verbose, gaps, "WL churn")
    return p


def _add_rep_names(roster: dict, path) -> None:
    """Add each rep name from a metrics/churn crosstab into the roster
    ({norm: display}). Uses the 'Rep Name' column, or the ICD-owner column."""
    try:
        rows = _read_utf16_tsv(path)
    except Exception:
        return
    if not rows:
        return
    h = [_norm(x) for x in rows[0]]
    ci = next((i for i, x in enumerate(h) if x == "rep name"), None)
    if ci is None:
        ci = next((i for i, x in enumerate(h) if "icd owner name" in x), None)
    if ci is None:
        return
    for r in rows[1:]:
        if len(r) > ci:
            name = (r[ci] or "").strip()
            if name and name.lower() not in ("total", "grand total"):
                roster.setdefault(_norm(name), name)


def _slice_team(names, icd, recent, wk_order, paths) -> tuple:
    """Build a RepDD per named rep from already-downloaded crosstab files."""
    opt = _opt()
    try:                        # first-sale dates: the '_first_sale' tab, filled
        from . import first_sale as _fs      # by the backfill + the 3am harvest
        _first = _fs.load_map()
    except Exception:           # never sink a /dd over the start-date column
        _fs, _first = None, {}
    week_reps, roster = {}, {}
    for sun in wk_order:
        f = paths["product"][sun]
        if not (f.exists() and f.stat().st_size > 0):
            week_reps[sun] = {}
            continue
        reps = opt.parse_personal_production(f)
        week_reps[sun] = reps
        for k, v in reps.items():
            roster.setdefault(k, v.get("owner", k))
    # Widen the roster with reps who appear in metrics/churn but had no product
    # sales in the window (e.g. wireless-only or newer reps) so they're findable.
    for pth in (paths["mni"], paths["mwl"], paths["cni"], paths["cwl"]):
        _add_rep_names(roster, pth)
    # A collapsed source is a REPORT-WIDE failure, not a per-rep blank — check
    # each one once, up front, so the gap is reported even when every rep misses.
    src_broken = {}
    for tag, pth, label in (("mni", paths["mni"], "NI cancel"),
                            ("mwl", paths["mwl"], "wireless cancel"),
                            ("cni", paths["cni"], "NI churn"),
                            ("cwl", paths["cwl"], "wireless churn")):
        src_broken[tag] = None if _has_rep_column(pth) else (
            f"{label}: the source view came back WITHOUT a 'Rep Name' column "
            f"(collapsed to ICD level) — no per-rep value exists for anyone")
    people, misses = [], []
    for name in names:
        key = _match_name(name, roster)
        if key is None:
            misses.append(name)
            continue
        display = roster.get(key, name)
        dd = RepDD(rep=display, matched_rep=display, icd=icd)
        dd.weeks = wk_order
        for sun in wk_order:
            e = week_reps.get(sun, {}).get(key)
            dd.new_int.weekly[sun] = _sum_products(e["values"], C.NI_PRODUCT_MATCH) if e else 0
            dd.wireless.weekly[sun] = _sum_products(e["values"], C.WL_PRODUCT_MATCH) if e else 0
        rset = set(wk_order[:recent])
        for t in (dd.new_int, dd.wireless):
            t.avg_8wk = _avg(list(t.weekly.values()))
            t.avg_recent = _avg([t.weekly[s] for s in wk_order if s in rset])
        m = _parse_metrics_rep(paths["mni"], key, C.METRIC_NI_CANCEL_0_30, C.METRIC_NI_ACT_30_60) or {}
        dd.new_int.cancel_0_30 = m.get("0-30", ""); dd.new_int.cancel_30_60 = m.get("30-60", "")
        mw = _parse_metrics_rep(paths["mwl"], key, C.METRIC_WL_CANCEL_0_30, C.METRIC_WL_ACT_30_60) or {}
        dd.wireless.cancel_0_30 = mw.get("0-30", ""); dd.wireless.cancel_30_60 = mw.get("30-60", "")
        dd.new_int.churn = _rep_churn(paths["cni"], key)
        dd.wireless.churn = _rep_churn(paths["cwl"], key)
        # Record what came back empty. Team mode used to swallow this entirely
        # ('... or {}' with no gap), which is how the New INT cancel column
        # stayed blank for weeks without a single warning.
        for tag, got in (("mni", m), ("mwl", mw),
                         ("cni", dd.new_int.churn), ("cwl", dd.wireless.churn)):
            if got:
                continue
            dd.gaps.append(src_broken[tag] or
                           f"{display} not found in the {tag} view — no sales in "
                           f"the window, or a name mismatch")
        if _fs is not None:
            dd.start_date = _fs.start_date_for(key, _first)
        people.append(dd)
    return people, misses


def _identical_weeks(d: Path, wk_order) -> bool:
    """True when every weekly product crosstab is byte-identical — the signature
    of a week filter that didn't apply (2026-07-30: a '?' already in the view URL
    made opt_phase._week_url append a second one, so Tableau ignored the filter
    and all 8 weeks came back as the same unfiltered pull, flattening the sales
    columns). Existence + non-zero size can't catch that, so check it explicitly."""
    import hashlib
    p = _team_paths(d, wk_order)["product"]
    digests = set()
    for f in p.values():
        if not (f.exists() and f.stat().st_size > 0):
            return False
        digests.add(hashlib.md5(f.read_bytes()).hexdigest())
    return len(p) > 1 and len(digests) == 1


def harvest_dd(*, weeks: int = None, anchor=None, page=None, verbose: bool = False) -> dict:
    """Nightly job: pull the shared crosstabs ONCE into today's cache dir so any
    same-day /dd request is instant (reads the cache, no live pull)."""
    weeks = weeks or C.WEEKS
    wk_order = recent_sundays(weeks, anchor)
    d = _cache_dir(anchor)
    gaps = []
    fs: dict = {}

    def _work(pg):
        _download_team_files(d, wk_order, pg, verbose, gaps)
        # Top up the first-sale map with any rep who has just started selling.
        # One extra crosstab over the SAME warm session (hence inside this
        # block); add-only, so it can never move a date the backfill set.
        try:
            from . import first_sale as _fs
            fs.update(_fs.update_recent(page=pg, verbose=verbose,
                                        log=(print if verbose else (lambda _m: None))))
        except Exception as e:                   # noqa: BLE001 — never sink the harvest
            gaps.append(f"first-sale top-up failed ({type(e).__name__}: {str(e)[:100]})")

    if page is None:
        from automations.shared.tableau_patchright import tableau_session
        with tableau_session(headless=True, verbose=verbose) as p:
            _work(p)
    else:
        _work(page)
    if _identical_weeks(d, wk_order):
        gaps.append("BROKEN: all 8 weekly product crosstabs are identical — the "
                    "week filter didn't apply (check for a '?' query string on "
                    "DD_PRODUCT_VIEW_URL). Weekly sales would render flat.")
    return {"dir": str(d), "complete": _cache_complete(d, wk_order),
            "first_sale": fs, "gaps": gaps}


def gather_team(names, *, icd: str = "", weeks: int = None, recent: int = None,
                anchor=None, page=None, verbose: bool = False) -> tuple:
    """Pull a whole team and slice each named rep. Uses today's harvest cache if
    it's complete (instant); otherwise pulls live. Returns (people, misses)."""
    weeks = weeks or C.WEEKS
    recent = recent or C.RECENT_WEEKS
    wk_order = recent_sundays(weeks, anchor)
    cache = _cache_dir(anchor)
    if _cache_complete(cache, wk_order):              # fresh harvest -> no session needed
        return _slice_team(names, icd, recent, wk_order, _team_paths(cache, wk_order))
    live = C.OUTPUT_DIR / "live"
    gaps = []
    if page is None:
        from automations.shared.tableau_patchright import tableau_session
        with tableau_session(headless=True, verbose=verbose) as p:
            paths = _download_team_files(live, wk_order, p, verbose, gaps)
    else:
        paths = _download_team_files(live, wk_order, page, verbose, gaps)
    return _slice_team(names, icd, recent, wk_order, paths)
