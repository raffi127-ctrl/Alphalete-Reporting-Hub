"""HTTP-based Tableau view downloader — bypasses the Crosstab dialog UI.

Tableau Cloud exposes a direct CSV-export URL for any view:
  https://us-east-1.online.tableau.com/t/{site}/views/{workbook}/{view}.csv

A GET on that URL returns the view's data as a regular CSV file IF the
caller is authenticated. We piggyback on the auth state of the debug-port
Chrome (which the user is logged into via SSO) by lifting its session
cookies and reusing them on the requests session.

Why this exists: the UI-driven download_crosstab() function in
opt_phase.py works for most Tableau views but FAILS for a specific
class (Activation Rates, Weekly Metrics, Lead Penetration, etc.) where
Tableau's React layer ignores synthetic thumbnail clicks — even
page.mouse.click() with real coords. Diagnosed exhaustively 2026-05-21.
The HTTP path doesn't trigger any of that UI machinery, so it works for
the views the UI path can't.

PAT auth was explored but disabled by the site admin. Session cookies
are sufficient for the GET endpoints we need.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Dict, List, Optional

import requests
from patchright.sync_api import sync_playwright

from automations.recruiting_report import fetch_office
from automations.recruiting_report.opt_phase import (
    _find_tableau_page,
    _reauth_tableau,
)

TABLEAU_BASE = "https://us-east-1.online.tableau.com"
TABLEAU_SITE = "sci"


def _grab_session() -> requests.Session:
    """Build a requests.Session pre-loaded with Tableau SSO cookies.

    Repointed 2026-07-01 to the PATCHRIGHT tableau session — the old CDP debug
    Chrome on :9222 no longer runs on the mini, so connect_over_cdp failed
    ("retrieving websocket url from http://localhost:9222"). Production callers
    (opt_nds) already pass their own patchright session via
    requests_session_from_page(page); this fallback now uses the same source, so
    a caller that omits `session` no longer hits the dead CDP path."""
    from automations.shared.tableau_patchright import (
        tableau_session, requests_session_from_page,
    )
    with tableau_session(verbose=False) as page:
        return requests_session_from_page(page)


def download_view_csv(workbook: str, view: str, out_path: Path,
                      session: Optional[requests.Session] = None,
                      timeout: int = 120,
                      params: Optional[Dict[str, str]] = None) -> Path:
    """GET the .csv export of a Tableau view + save it to disk.
    `workbook` and `view` are the URL slugs (e.g. 'DropshipV_2' and
    'ACTIVATIONRATES'). Reuses `session` if provided; otherwise grabs
    a fresh one from the debug Chrome.

    `params` (e.g. {'Min Date': '2026-05-11', 'Max Date': '2026-05-17'})
    are passed as query params to pin the view's date filter — the .csv
    endpoint honors them the same way the dashboard URL does."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    s = session or _grab_session()
    url = f"{TABLEAU_BASE}/t/{TABLEAU_SITE}/views/{workbook}/{view}.csv"
    r = s.get(url, params=params or {}, allow_redirects=True, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(
            f"Tableau CSV download failed for {workbook}/{view}: "
            f"HTTP {r.status_code} ({len(r.content)} bytes)")
    ct = (r.headers.get("content-type") or "").lower()
    if "csv" not in ct:
        raise RuntimeError(
            f"Tableau CSV download returned unexpected content-type "
            f"{ct!r} for {workbook}/{view}")
    out_path.write_bytes(r.content)
    return out_path


def parse_csv(path: Path) -> List[List[str]]:
    """Parse a Tableau-exported CSV — comma-delimited, ISO-8859-1
    encoded (Tableau Cloud's quirk). Returns rows."""
    if not path.exists() or path.stat().st_size == 0:
        return []
    text = path.read_text(encoding="iso-8859-1", errors="replace")
    return list(csv.reader(io.StringIO(text)))


def _norm_owner(s: str) -> str:
    """Same normalizer as opt_nds._norm_owner — strip [city, state]
    suffix, lowercase, collapse whitespace."""
    import re
    s = (s or "").strip()
    s = re.split(r"[\[\n]", s, maxsplit=1)[0].strip()
    return " ".join(s.lower().split())


def col_idx(header: List[str], label: str) -> Optional[int]:
    """Find column index by header text (case-insensitive, whitespace-
    trimmed). Returns None if not found."""
    target = " ".join((label or "").lower().split())
    for i, h in enumerate(header):
        if " ".join((h or "").lower().split()) == target:
            return i
    return None


# ------------------------------------------------------- per-view parsers


def parse_activation(path: Path,
                     bucket: str = "60+ Days") -> Dict[str, str]:
    """{normalized owner: 'Activation Rate' for the given bucket} from
    the Activation Rates CSV. Bucket defaults to '60+ Days' since
    that's the metric we map to 'Activation % by Week'."""
    rows = parse_csv(path)
    if not rows:
        return {}
    header = rows[0]
    owner_i = col_idx(header, "Owner & Office")
    bucket_i = col_idx(header, "Sales Date Bucket")
    rate_i = col_idx(header, "Activation Rate")
    if owner_i is None or bucket_i is None or rate_i is None:
        return {}
    out: Dict[str, str] = {}
    for r in rows[1:]:
        if len(r) <= max(owner_i, bucket_i, rate_i):
            continue
        if (r[bucket_i] or "").strip() != bucket:
            continue
        owner = _norm_owner(r[owner_i])
        if owner:
            out[owner] = (r[rate_i] or "").strip()
    return out


def parse_weekly_metrics_cancel(path: Path) -> Dict[str, str]:
    """{normalized owner: '0-30 Day Cancel Rate 4wk avg'} from the NDS
    Weekly Metrics CSV. The CSV is in long format (Measure Names /
    Measure Values per row); we filter to the Cancel Fraud Review %
    measure."""
    rows = parse_csv(path)
    if not rows:
        return {}
    header = rows[0]
    owner_i = col_idx(header, "Owner & Office")
    measure_i = col_idx(header, "Measure Names")
    value_i = col_idx(header, "Measure Values")
    if owner_i is None or measure_i is None or value_i is None:
        return {}
    out: Dict[str, str] = {}
    target = "cancel fraud review"   # looser match — exact label tbd
    for r in rows[1:]:
        if len(r) <= max(owner_i, measure_i, value_i):
            continue
        m = (r[measure_i] or "").strip().lower()
        if target not in m:
            continue
        owner = _norm_owner(r[owner_i])
        if owner:
            out[owner] = (r[value_i] or "").strip()
    return out


def parse_lead_penetration(path: Path) -> Dict[str, int]:
    """{normalized owner: total Lead Count summed across all rows}.
    Each ICD has multiple rows (one per Customer Zip). We sum to get
    the per-ICD total."""
    rows = parse_csv(path)
    if not rows:
        return {}
    header = rows[0]
    owner_i = col_idx(header, "ICD Owner Name")
    measure_i = col_idx(header, "Measure Names")
    value_i = col_idx(header, "Measure Values")
    if owner_i is None or measure_i is None or value_i is None:
        return {}
    totals: Dict[str, int] = {}
    target = "lead count"
    for r in rows[1:]:
        if len(r) <= max(owner_i, measure_i, value_i):
            continue
        m = (r[measure_i] or "").strip().lower()
        if target not in m:
            continue
        owner = _norm_owner(r[owner_i])
        try:
            val = int(float((r[value_i] or "0").replace(",", "")))
        except ValueError:
            continue
        if owner:
            totals[owner] = totals.get(owner, 0) + val
    return totals


def parse_sara_plus_byday(path: Path,
                          metrics: Optional[List[str]] = None
                          ) -> Dict[str, Dict[str, int]]:
    """Parse SARAPLUSSALESSUMMARYBYDAY: {normalized owner: {metric: total}}.

    The CSV is long-format with one row per (owner, metric, day). We sum
    across all days in the file to get the week-to-date total per metric
    per rep. Tableau exports only the currently-filtered week (Sales Week
    = This Week on the dashboard), so this naturally scopes to the
    current week.

    Confirmed columns (2026-05-21): ICD Owner Name | Measure Names |
    Order Date | Owner & Office | Measure Values. 361 rows for a
    mid-week pull (5 metrics × 6+ reps × 4-5 days).

    `metrics` filter is case-insensitive against Measure Names. Default
    keeps all five (ATV/DTV/Internet/AIA/Wireless Lines)."""
    rows = parse_csv(path)
    if not rows:
        return {}
    header = rows[0]
    owner_i = col_idx(header, "ICD Owner Name")
    measure_i = col_idx(header, "Measure Names")
    value_i = col_idx(header, "Measure Values")
    if owner_i is None or measure_i is None or value_i is None:
        return {}
    wanted = None
    if metrics is not None:
        wanted = {m.strip().lower() for m in metrics}
    out: Dict[str, Dict[str, int]] = {}
    for r in rows[1:]:
        if len(r) <= max(owner_i, measure_i, value_i):
            continue
        owner = _norm_owner(r[owner_i])
        metric = (r[measure_i] or "").strip()
        if not owner or not metric:
            continue
        if wanted is not None and metric.lower() not in wanted:
            continue
        try:
            val = int(float((r[value_i] or "0").replace(",", "")))
        except ValueError:
            continue
        bucket = out.setdefault(owner, {})
        bucket[metric] = bucket.get(metric, 0) + val
    return out
