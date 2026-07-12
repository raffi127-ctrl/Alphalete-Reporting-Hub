"""Stage (c) proof — cache-run == live-run, cell-for-cell.

SHADOW-ONLY, THROWAWAY. Runs entirely in this process. It calls ONLY the
reports' pull+parse (pure, reads a crosstab -> dict). It NEVER fills a Sheet,
NEVER posts Slack, and CANNOT reach the live 4am subprocesses.

    python -m automations.harvest.proof                 # structural-cover subset
    python -m automations.harvest.proof --full          # all 19 churn pulls
    python -m automations.harvest.proof --date 2026-07-12

What it does, per need:
  1. HARVEST once -> dated cache (real download, full provenance/manifest).
  2. CONTROL  = a fresh LIVE download (same login) -> the report's own parse().
  3. TREATMENT= load_harvest() (full staleness/provenance guard) -> same parse().
  4. DIFF control vs treatment payload cell-for-cell + compare raw sha256.

Harvest pull and control pull share ONE Tableau session seconds apart, so any
byte/parse difference is a seam bug, not data drift. One need
(new_internet_churn) is additionally driven through the REAL monkeypatched
fetch_crosstab to prove the production cutover is a one-function swap.
"""
from __future__ import annotations

import argparse
import datetime as dt
import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Dict, List, Tuple

from automations.harvest import config
from automations.harvest.needs import (
    DataNeed, cache_key,
    NEED_NI_LOCAL, NEED_WL_LOCAL, NEED_NI_CAP, NEED_WL_CAP,
    NEED_OWN_CARLOS, NEED_OWN_KHALIL, CHURN_CLUSTER_NEEDS,
)
from automations.harvest.harvester import harvest
from automations.harvest.loader import load_harvest


# ---- per-need parse binding: which report parser consumes each crosstab ----
def _parse_binding(need: DataNeed) -> Tuple[str, Callable[[Path], dict]]:
    """(report label, parse fn) for a need. Lazily imports the real report
    parser so this module stays importable without the browser stack until run."""
    from automations import new_internet_churn, captainship_churn, owners_metrics_churn
    ck = cache_key(need)
    if ck in (cache_key(NEED_OWN_CARLOS),):
        return "owners_metrics_churn.parse_b2b", owners_metrics_churn.pull.parse_b2b
    if ck in (cache_key(NEED_OWN_KHALIL),):
        return "owners_metrics_churn.parse_nds", owners_metrics_churn.pull.parse_nds
    if ck in (cache_key(NEED_NI_CAP), cache_key(NEED_WL_CAP)):
        return "captainship_churn.parse", captainship_churn.pull.parse
    # owners fiber views also use the captainship parser (aliased); everything
    # else (local + rashad + aya NI/WL) uses new_internet_churn.parse.
    from automations.owners_metrics_churn import pull as omp
    if need.workbook.startswith("ATTTRACKER2_1-D2D") and "STEAMCHURN" in need.view_url.upper() \
            and "RAFSTEAMCHURN" not in need.view_url.upper():
        return "owners_metrics_churn.parse", omp.parse
    return "new_internet_churn.parse", new_internet_churn.pull.parse


SUBSET: List[DataNeed] = [NEED_NI_LOCAL, NEED_WL_LOCAL, NEED_NI_CAP,
                          NEED_OWN_CARLOS, NEED_OWN_KHALIL]


@contextmanager
def _keep_open(page):
    """Session factory shim: hand harvest the ALREADY-open page; don't close it."""
    yield page


# ---------------------- cell-for-cell diff ----------------------
def _flatten(obj, prefix="") -> Dict[str, str]:
    """Flatten a nested parse payload to dotted path -> stringified leaf."""
    out: Dict[str, str] = {}
    if isinstance(obj, dict):
        for k in obj:
            out.update(_flatten(obj[k], f"{prefix}{k}." ))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            out.update(_flatten(v, f"{prefix}{i}."))
    else:
        out[prefix.rstrip(".")] = "" if obj is None else str(obj)
    return out


def diff_payloads(control: dict, treatment: dict) -> List[str]:
    """Return a list of cell-level mismatch descriptions ([] == identical)."""
    fc, ft = _flatten(control), _flatten(treatment)
    diffs: List[str] = []
    for key in sorted(set(fc) | set(ft)):
        cv, tv = fc.get(key, "<MISSING>"), ft.get(key, "<MISSING>")
        if cv != tv:
            diffs.append(f"{key}: control={cv!r}  treatment={tv!r}")
    return diffs


# ---------------------- the run ----------------------
def run_proof(target_date: dt.date, needs: List[DataNeed],
              *, keep_cache: bool, logfn=print) -> dict:
    from automations.shared.tableau_patchright import (
        tableau_session, download_crosstab_patchright,
    )
    from automations import new_internet_churn

    logfn(f"=== PROOF {target_date.isoformat()} — {len(needs)} need(s) ===")
    logfn("side-effects: NONE (parse-only; no Sheet writes, no Slack).\n")

    per_need: List[dict] = []
    tmp = Path(tempfile.mkdtemp(prefix="harvest_proof_"))

    with tableau_session(verbose=False) as page:
        # --- Phase 1: harvest once (real manifest, same open session) ---
        logfn("--- Phase 1: HARVEST (one login) ---")
        result = harvest(target_date, needs, probe=True, logfn=logfn,
                         _session_factory=lambda verbose=False: _keep_open(page),
                         _download=download_crosstab_patchright)
        if result.deferred:
            logfn(f"  ! {len(result.deferred)} need(s) deferred (not ready) — "
                  f"excluded from the diff.")

        harvested = {e.cache_key for e in result.entries if e.error is None}

        # --- Phase 2+3: control (live) vs treatment (cache) per need ---
        logfn("\n--- Phase 2/3: CONTROL (live) vs TREATMENT (cache) ---")
        for need in needs:
            ck = cache_key(need)
            label, parse_fn = _parse_binding(need)
            rec: dict = {"need": need.label, "cache_key": ck, "parser": label}
            if ck not in harvested:
                rec["status"] = "SKIPPED (not harvested / deferred)"
                logfn(f"\n[{need.label}] SKIPPED — not in harvest set")
                per_need.append(rec)
                continue

            logfn(f"\n[{need.label}]  parser={label}  key={ck}")
            # CONTROL: fresh live download on the same session -> report parse
            control_path = tmp / f"{ck}.control.tsv"
            download_crosstab_patchright(need.view_url, need.crosstab_sheet,
                                         control_path, verbose=False, page=page)
            control_payload = parse_fn(control_path)
            # TREATMENT: verified cache via the full loader guard -> report parse
            cache_path = load_harvest(need, target_date)
            treatment_payload = parse_fn(cache_path)

            # raw-byte comparison (drift detector)
            import hashlib
            def _sha(p):
                return hashlib.sha256(p.read_bytes()).hexdigest()
            same_bytes = _sha(control_path) == _sha(cache_path)
            diffs = diff_payloads(control_payload, treatment_payload)

            cells = len(_flatten(control_payload))
            rec.update(status="OK" if not diffs else "MISMATCH",
                       identical=not diffs, raw_bytes_identical=same_bytes,
                       cells_compared=cells, mismatches=diffs[:50])
            logfn(f"    raw bytes identical : {same_bytes}")
            logfn(f"    cells compared      : {cells}")
            logfn(f"    payload identical   : {not diffs}")
            if diffs:
                logfn(f"    !! {len(diffs)} MISMATCH(es):")
                for d in diffs[:20]:
                    logfn(f"       {d}")
            per_need.append(rec)

        # --- Phase 4: prove the production cutover is a one-function swap ---
        logfn("\n--- Phase 4: monkeypatch integration (new_internet_churn) ---")
        mp = _monkeypatch_demo(new_internet_churn, NEED_NI_LOCAL, target_date,
                               page, download_crosstab_patchright, logfn)

    if not keep_cache:
        shutil.rmtree(result.day_dir, ignore_errors=True)
        logfn(f"\n(cleaned throwaway cache {result.day_dir})")
    shutil.rmtree(tmp, ignore_errors=True)

    summary = {
        "target_date": target_date.isoformat(),
        "needs": len(needs),
        "compared": [r for r in per_need if r.get("status") in ("OK", "MISMATCH")],
        "all_identical": all(r.get("identical") for r in per_need
                             if r.get("status") in ("OK", "MISMATCH")),
        "monkeypatch": mp,
        "per_need": per_need,
    }
    logfn("\n=== RESULT: "
          + ("ALL IDENTICAL ✅" if summary["all_identical"] else "MISMATCH ❌")
          + " ===")
    return summary


def _monkeypatch_demo(report_pkg, need: DataNeed, target_date: dt.date,
                      page, real_download, logfn) -> dict:
    """Patch the report's OWN download symbol to serve the cache, then call its
    REAL fetch_crosstab + parse. Proves the cutover changes one function."""
    pull = report_pkg.pull
    # CONTROL via the report's real fetch (live)
    live = pull.fetch_crosstab(page=page)
    control = pull.parse(live)
    # TREATMENT: swap the seam to serve the verified cache file
    orig = pull.download_crosstab_patchright
    def _cache_download(view_url, crosstab_sheet, out_path, verbose=True,
                        page=None, pre_export=None):
        shutil.copyfile(load_harvest(need, target_date), out_path)
        return out_path
    pull.download_crosstab_patchright = _cache_download
    try:
        cached = pull.fetch_crosstab(page=page)
        treatment = pull.parse(cached)
    finally:
        pull.download_crosstab_patchright = orig   # always restore
    diffs = diff_payloads(control, treatment)
    logfn(f"    real fetch_crosstab() via patched seam -> "
          + ("IDENTICAL ✅" if not diffs else f"{len(diffs)} MISMATCH ❌"))
    return {"identical": not diffs, "mismatches": diffs[:20]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="harvest-proof")
    ap.add_argument("--date", default=None, help="target date YYYY-MM-DD (default today)")
    ap.add_argument("--full", action="store_true",
                    help="all 19 churn-cluster pulls (default: 5-need structural cover)")
    ap.add_argument("--keep-cache", action="store_true",
                    help="don't delete the throwaway dated cache after the proof")
    args = ap.parse_args(argv)
    target = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    needs = CHURN_CLUSTER_NEEDS if args.full else SUBSET
    summary = run_proof(target, needs, keep_cache=args.keep_cache)
    return 0 if summary["all_identical"] and summary["monkeypatch"]["identical"] else 1


if __name__ == "__main__":
    sys.exit(main())
