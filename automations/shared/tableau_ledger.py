"""Tableau access ledger — count every touch we make on Tableau.

WHY (Megan 2026-08-17): the eStream/Tableau folks flagged ~10k accesses a
week. Before we can cut that we have to KNOW what makes it up: which report,
which view, how many of those pulls are the exact same data pulled twice.
Nobody can answer that today because the pulls are spread across ~92
scheduled reports and four different code paths.

This module is a passive recorder wired into the chokepoints:
  - shared.tableau_patchright.download_crosstab_patchright   (kind=crosstab)
  - shared.tableau_patchright.scrape_view_data_patchright    (kind=viewdata)
  - alphalete_org_report.tableau_http.download_view_csv      (kind=http_csv)
  - tableau_screenshots.capture                              (kind=screenshot)

It NEVER changes behaviour and never raises: every entry point is wrapped so
a broken ledger can't take a report down. One append-only JSONL per day under
output/logs/tableau-access/.

Read it with:
    python -m automations.shared.tableau_ledger --summary
    python -m automations.shared.tableau_ledger --summary --days 7
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER_DIR = REPO_ROOT / "output" / "logs" / "tableau-access"

# Set by the day orchestrator per subprocess so a pull can be blamed on the
# report that made it. Falls back to the -m module name for manual runs.
REPORT_ENV = "HUB_REPORT_ID"


def _today() -> str:
    return _dt.date.today().isoformat()


def _caller_report() -> str:
    """Best-effort 'who pulled this'. Orchestrator env first, then the module
    the process was launched with (python -m automations.<pkg>...)."""
    rid = os.environ.get(REPORT_ENV)
    if rid:
        return rid
    try:
        argv0 = Path(sys.argv[0]).resolve()
        parts = argv0.parts
        if "automations" in parts:
            i = parts.index("automations")
            tail = parts[i + 1:]
            if tail:
                return tail[0] if len(tail) > 1 else Path(tail[0]).stem
    except Exception:
        pass
    return "unknown"


def normalize_view(view_url: str) -> str:
    """Drop the volatile bits so the same view matches itself across reports.
    :iid is a UI tab index; :embed/:showVizHome etc. are render flags. Query
    FILTERS are kept — two reports on one view at different weeks are two
    genuinely different pulls."""
    u = (view_url or "").strip()
    u = re.sub(r"[?&]:(iid|embed|showVizHome|toolbar|refresh|origin)=[^&]*", "", u)
    return u.rstrip("?&")


def need_key(view_url: str, sheet: str = "", extra: str = "") -> str:
    """Stable id for 'this exact data'. Two records sharing a key are the same
    bytes pulled twice — i.e. dedupe headroom."""
    raw = "\0".join([normalize_view(view_url), sheet or "", extra or ""])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def record(view_url: str,
           sheet: str = "",
           kind: str = "crosstab",
           cache: str = "miss",
           extra: str = "",
           report: Optional[str] = None,
           ok: bool = True,
           elapsed_ms: Optional[int] = None) -> None:
    """Append one access. Silent no-op on any failure — this must never be
    able to fail a report."""
    try:
        if os.environ.get("TABLEAU_LEDGER", "1") == "0":
            return
        LEDGER_DIR.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": _dt.datetime.now().isoformat(timespec="seconds"),
            "report": report or _caller_report(),
            "kind": kind,
            "cache": cache,
            "ok": bool(ok),
            "view": normalize_view(view_url),
            "sheet": sheet or "",
            "key": need_key(view_url, sheet, extra),
            "pid": os.getpid(),
        }
        if elapsed_ms is not None:
            rec["elapsed_ms"] = int(elapsed_ms)
        line = json.dumps(rec, ensure_ascii=False)
        # One open-append-close per record: many report subprocesses write this
        # file concurrently, and a short line append under O_APPEND is atomic.
        with open(LEDGER_DIR / f"{_today()}.jsonl", "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------- reading

def load(days: int = 1, end: Optional[_dt.date] = None):
    end = end or _dt.date.today()
    out = []
    for i in range(days):
        d = end - _dt.timedelta(days=i)
        p = LEDGER_DIR / f"{d.isoformat()}.jsonl"
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def _short(view: str, sheet: str) -> str:
    tail = view.rsplit("/views/", 1)[-1] if "/views/" in view else view[-48:]
    tail = tail.split("?")[0]
    return f"{tail}" + (f" :: {sheet}" if sheet else "")


def summarize(days: int = 1, end: Optional[_dt.date] = None) -> str:
    recs = load(days=days, end=end)
    if not recs:
        return ("No ledger entries yet.\n"
                f"Expected under {LEDGER_DIR}\n"
                "Nothing has run through an instrumented pull path since the "
                "ledger was wired in.")

    lines = []
    # Logins are counted separately from data pulls: one tableau_session() =
    # one SSO login, and THAT is the number eStream is complaining about.
    logins = [r for r in recs if r.get("kind") == "login"]
    recs = [r for r in recs if r.get("kind") != "login"]
    total = len(recs)
    live = [r for r in recs if r.get("cache") != "hit"]
    hits = total - len(live)
    keys = {}
    for r in live:
        keys.setdefault(r["key"], []).append(r)
    distinct = len(keys)

    lines.append(f"TABLEAU ACCESS LEDGER — last {days} day(s), "
                 f"through {(end or _dt.date.today()).isoformat()}")
    lines.append("=" * 72)
    lines.append(f"  *** TABLEAU LOGINS      : {len(logins)}   "
                 f"({len(logins) / max(days, 1):.0f}/day) ***")
    lines.append(f"  total recorded accesses : {total}")
    lines.append(f"  served from cache       : {hits}")
    lines.append(f"  actually hit Tableau    : {len(live)}")
    lines.append(f"  DISTINCT data needs     : {distinct}   "
                 f"<- the floor a harvest-once design can reach")
    if len(live):
        lines.append(f"  duplicate pulls         : {len(live) - distinct} "
                     f"({100.0 * (len(live) - distinct) / len(live):.0f}% waste)")
    lines.append(f"  per day (avg)           : {len(live) / max(days, 1):.0f} live, "
                 f"{distinct / max(days, 1):.0f} distinct")
    lines.append("")

    by_report = {}
    for r in live:
        by_report.setdefault(r.get("report", "unknown"), []).append(r)
    lines.append("BY REPORT (live pulls, worst first)")
    lines.append("-" * 72)
    lines.append(f"{'report':32s} {'pulls':>6s} {'distinct':>9s} {'dupes':>6s}")
    for rep, rs in sorted(by_report.items(), key=lambda kv: -len(kv[1])):
        dk = len({x["key"] for x in rs})
        lines.append(f"{rep[:31]:32s} {len(rs):6d} {dk:9d} {len(rs) - dk:6d}")
    lines.append("")

    lines.append("BY VIEW (most-pulled first) — 'reports' = how many reports want it")
    lines.append("-" * 72)
    lines.append(f"{'view :: sheet':52s} {'pulls':>6s} {'reports':>8s}")
    for k, rs in sorted(keys.items(), key=lambda kv: -len(kv[1]))[:30]:
        r0 = rs[0]
        nrep = len({x.get("report") for x in rs})
        lines.append(f"{_short(r0['view'], r0['sheet'])[:51]:52s} "
                     f"{len(rs):6d} {nrep:8d}")
    lines.append("")

    if logins:
        by_rep_login = {}
        for r in logins:
            k = r.get("report", "unknown")
            by_rep_login[k] = by_rep_login.get(k, 0) + 1
        lines.append("LOGINS BY REPORT — each one is a separate Tableau sign-in.")
        lines.append("A report logging in more than once is opening a new session "
                     "per pull instead of sharing one page.")
        lines.append("-" * 72)
        for rep, n in sorted(by_rep_login.items(), key=lambda kv: -kv[1])[:25]:
            lines.append(f"  {rep[:40]:42s} {n:5d}")
        lines.append("")

    by_kind = {}
    for r in live:
        by_kind[r.get("kind", "?")] = by_kind.get(r.get("kind", "?"), 0) + 1
    lines.append("BY PATH: " + ", ".join(f"{k}={v}" for k, v in
                                         sorted(by_kind.items(), key=lambda kv: -kv[1])))
    fails = [r for r in live if not r.get("ok", True)]
    if fails:
        lines.append(f"FAILED/RETRIED pulls: {len(fails)} "
                     f"(each retry is another access Tableau counts)")
    return "\n".join(lines)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Tableau access ledger")
    ap.add_argument("--summary", action="store_true", help="print the census")
    ap.add_argument("--days", type=int, default=1, help="how many days back")
    ap.add_argument("--date", help="end date YYYY-MM-DD (default today)")
    a = ap.parse_args(argv)
    end = _dt.date.fromisoformat(a.date) if a.date else None
    print(summarize(days=a.days, end=end))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
