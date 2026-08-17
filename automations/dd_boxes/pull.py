"""Sources for the DD-style boxes — the SAME ones the rest of ATT fiber uses.

  * weekly sales  -> PRODUCT SALES SUMMARY (`opt_phase.parse_personal_production`),
    the crosstab the OPT phase already downloads for every other rep
  * cancel rates  -> MetricsINTfullyEXP / MetricsWIRfullyEXP, per rep
  * churn         -> INTAllTeams / WirelessAllTeams, sliced to the rep
  * start date    -> the '_first_sale' map

All of them are resolved through `due_diligence.config`, so a view that moves
is repointed in ONE place for both this report and Jiraiya.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Dict, List, Optional

from automations.due_diligence import config as DDC
from automations.due_diligence.pull import (_has_rep_column, _parse_metrics_rep,
                                            _rep_churn, _read_utf16_tsv)

PERIODS = ("0-30", "30", "60", "90")
ZERO = "0.00%"


def most_recent_sunday(today: Optional[dt.date] = None) -> dt.date:
    from automations.recruiting_report.opt_phase import _most_recent_sunday
    return _most_recent_sunday(today)


class Sources:
    """Everything the fill needs, pulled once and shared across every box."""

    def __init__(self, product_csv: Path, out_dir: Path):
        self.product_csv = Path(product_csv)
        self.out_dir = Path(out_dir)
        self.paths: Dict[str, Path] = {}
        self.gaps: List[str] = []
        self._sales: Dict[str, dict] = {}
        self._first: dict = {}
        self._week_csv: Dict[dt.date, Path] = {}     # past weeks, for --backfill
        self._week_sales: Dict[dt.date, dict] = {}

    # -- download -----------------------------------------------------------
    def fetch(self, page=None, verbose: bool = False) -> "Sources":
        from automations.shared.tableau_patchright import (
            tableau_session, download_crosstab_patchright)
        jobs = [("mni", DDC.metrics_ni_source(), "NI cancel"),
                ("mwl", DDC.metrics_wl_source(), "wireless cancel"),
                ("cni", DDC.churn_ni_source(), "NI churn"),
                ("cwl", DDC.churn_wl_source(), "wireless churn")]
        self.out_dir.mkdir(parents=True, exist_ok=True)

        def _work(pg):
            for key, (url, sheet), label in jobs:
                out = self.out_dir / f"{key}.csv"
                try:
                    download_crosstab_patchright(url, sheet, out, verbose=verbose,
                                                 page=pg)
                    self.paths[key] = out
                except Exception as e:      # noqa: BLE001 — one bad source must
                    self.gaps.append(       # not sink the other three
                        f"{label}: pull failed ({type(e).__name__}: {str(e)[:120]})")

        if page is None:
            with tableau_session(headless=True, verbose=verbose) as pg:
                _work(pg)
        else:
            _work(page)

        # A view that comes back collapsed to ICD level has no per-rep value for
        # ANYONE — that is a report-wide failure, not a rep who didn't sell.
        for key, label in (("mni", "NI cancel"), ("mwl", "wireless cancel"),
                           ("cni", "NI churn"), ("cwl", "wireless churn")):
            p = self.paths.get(key)
            if p and not _has_rep_column(p):
                self.gaps.append(
                    f"{label}: the view came back WITHOUT a 'Rep Name' column "
                    f"(collapsed to ICD level) — blank for every rep")
        return self

    def fetch_weeks(self, weeks: List[dt.date], page=None,
                    verbose: bool = False) -> None:
        """Download one PRODUCT SALES crosstab per past week, for --backfill.

        A box added mid-quarter starts life with holes (Tony Chavez's boxes were
        created with 8/2 and 8/9 empty). The weekly fill only ever touches the
        current week, so without this those holes stay forever — and they drag
        the '8 WK Average' down, because AVERAGE just skips the blanks.
        """
        from automations.recruiting_report import opt_phase
        from automations.shared.tableau_patchright import (
            tableau_session, download_crosstab_patchright)
        url, sheet = opt_phase.PRODUCT_SALES_VIEW_URL, opt_phase.PRODUCT_SALES_SHEET
        self.out_dir.mkdir(parents=True, exist_ok=True)

        def _work(pg):
            for sun in weeks:
                out = self.out_dir / f"product_{sun.isoformat()}.csv"
                if out.exists() and out.stat().st_size:
                    self._week_csv[sun] = out
                    continue
                try:
                    download_crosstab_patchright(
                        opt_phase._week_url(url.split("?", 1)[0], sun),
                        sheet, out, verbose=verbose, page=pg)
                    self._week_csv[sun] = out
                except Exception as e:      # noqa: BLE001
                    self.gaps.append(f"product {sun}: pull failed "
                                     f"({type(e).__name__}: {str(e)[:100]})")

        if page is None:
            with tableau_session(headless=True, verbose=verbose) as pg:
                _work(pg)
        else:
            _work(page)

    def units_for_week(self, rep_key: str, side: str,
                       sun: dt.date) -> Optional[int]:
        """Units in a PAST week — needs fetch_weeks() to have run."""
        from automations.recruiting_report import opt_phase
        from automations.due_diligence.config import (NI_PRODUCT_MATCH,
                                                      WL_PRODUCT_MATCH)
        from automations.due_diligence.pull import _sum_products
        csv = self._week_csv.get(sun)
        if not csv:
            return None
        if sun not in self._week_sales:
            self._week_sales[sun] = opt_phase.parse_personal_production(csv)
        ent = self._week_sales[sun].get(rep_key)
        if ent is None:
            return None
        vals = ent.get("values", {})
        ni = _sum_products(vals, NI_PRODUCT_MATCH)
        wl = _sum_products(vals, WL_PRODUCT_MATCH)
        return {"ni": ni, "wl": wl, "ts": ni + wl}[side]

    def use_cached(self, d: Path) -> "Sources":
        """Point at an already-downloaded set (used by --skip-download)."""
        for key in ("mni", "mwl", "cni", "cwl"):
            p = Path(d) / f"{key}.csv"
            if p.exists() and p.stat().st_size:
                self.paths[key] = p
        return self

    # -- reads --------------------------------------------------------------
    def sales(self) -> Dict[str, dict]:
        """{normalized rep: {owner, values{product: count}}} for the week."""
        if not self._sales:
            from automations.recruiting_report import opt_phase
            self._sales = opt_phase.parse_personal_production(self.product_csv)
        return self._sales

    def first_sale_map(self) -> dict:
        if not self._first:
            try:
                from automations.due_diligence import first_sale as fs
                self._first = fs.load_map()
            except Exception as e:      # noqa: BLE001
                self.gaps.append(f"start date: map unavailable ({type(e).__name__})")
                self._first = {}
        return self._first

    def units(self, rep_key: str, side: str) -> Optional[int]:
        """Units sold this week. None when the rep isn't in the crosstab at all
        (the caller decides whether that's a zero or a name problem)."""
        from automations.due_diligence.config import (NI_PRODUCT_MATCH,
                                                      WL_PRODUCT_MATCH)
        from automations.due_diligence.pull import _sum_products
        ent = self.sales().get(rep_key)
        if ent is None:
            return None
        vals = ent.get("values", {})
        ni = _sum_products(vals, NI_PRODUCT_MATCH)
        wl = _sum_products(vals, WL_PRODUCT_MATCH)
        return {"ni": ni, "wl": wl, "ts": ni + wl}[side]

    def metrics(self, rep_key: str, side: str) -> dict:
        """{'c030','c3060'} for the rep, zero-filled. 'ts' boxes get no cancel
        columns, so this is only called for 'ni' / 'wl'."""
        key, c_field, a_field = (
            ("mni", DDC.METRIC_NI_CANCEL_0_30, DDC.METRIC_NI_ACT_30_60)
            if side == "ni" else
            ("mwl", DDC.METRIC_WL_CANCEL_0_30, DDC.METRIC_WL_ACT_30_60))
        p = self.paths.get(key)
        m = _parse_metrics_rep(p, rep_key, c_field, a_field) if p else None
        m = m or {}
        return {"c030": m.get("0-30") or ZERO, "c3060": m.get("30-60") or ZERO}

    def churn(self, rep_key: str, side: str) -> dict:
        p = self.paths.get("cni" if side == "ni" else "cwl")
        ch = _rep_churn(p, rep_key) if p else {}
        return {f"churn_{k}": (ch.get(k) or ZERO) for k in PERIODS}

    def start_date(self, rep_key: str) -> str:
        from automations.due_diligence import first_sale as fs
        try:
            return fs.start_date_for(rep_key, self.first_sale_map())
        except Exception:       # noqa: BLE001
            return ""

    def roster(self) -> Dict[str, str]:
        """{normalized: display} across every source, for name matching."""
        from automations.due_diligence.pull import _add_rep_names
        r = {k: v.get("owner", k) for k, v in self.sales().items()}
        for key in ("mni", "mwl", "cni", "cwl"):
            p = self.paths.get(key)
            if p:
                _add_rep_names(r, p)
        return r
