"""Mini-runnable wrapper around the Stage (c) proof (proof.run_proof).

SHADOW-ONLY. Nothing on the live 4am path imports this. See README.md.

Why this exists separately from proof.py: the mini's rerun path (mini_control
_run_cmd) only surfaces the LAST 3 lines of stdout via `lucy status`, and
`lucy logtail` can only page files under output/logs/. So this wrapper:
  * tees the FULL proof output to output/logs/harvest_proof-<date>.log
    (retrievable from the laptop with `lucy logtail harvest_proof`), and
  * prints a COMPACT final verdict last, so the `lucy status` tail carries the
    headline (compared / identical / mismatch / cutover / VERDICT).

Run on the mini via:  lucy rerun harvest_proof            (5-need structural cover)
                      lucy rerun harvest_proof --full     (all 19 churn pulls)
Exit 0 iff every payload is identical cell-for-cell AND the cutover monkeypatch
is identical.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from automations.harvest import config
from automations.harvest.needs import CHURN_CLUSTER_NEEDS
from automations.harvest.proof import run_proof, SUBSET


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="harvest-proof-mini")
    ap.add_argument("--date", default=None, help="target date YYYY-MM-DD (default today)")
    ap.add_argument("--full", action="store_true",
                    help="all 19 churn-cluster pulls (default: 5-need structural cover)")
    ap.add_argument("--keep-cache", action="store_true",
                    help="don't delete the throwaway dated cache after the proof")
    args = ap.parse_args(argv)

    target = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    needs = CHURN_CLUSTER_NEEDS if args.full else SUBSET

    logs_dir = config.REPO_ROOT / "output" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"harvest_proof-{target.isoformat()}.log"

    captured: list[str] = []

    def tee(msg: str = "") -> None:
        print(msg)
        captured.append(str(msg))

    summary = run_proof(target, needs, keep_cache=args.keep_cache, logfn=tee)

    # ---- compact verdict (printed LAST so it lands in the lucy-status tail) ----
    compared = [r for r in summary["per_need"]
                if r.get("status") in ("OK", "MISMATCH")]
    identical = sum(1 for r in compared if r.get("identical"))
    mism = len(compared) - identical
    mp_ok = bool(summary.get("monkeypatch", {}).get("identical"))
    verdict = bool(summary["all_identical"]) and mp_ok

    tee("")
    tee(f"PROOF {target.isoformat()}: {len(compared)} compared · "
        f"{identical} identical · {mism} mismatch")
    tee(f"cutover monkeypatch: {'identical' if mp_ok else 'MISMATCH'}")
    tee(f"VERDICT: {'ALL IDENTICAL' if verdict else 'MISMATCH'} "
        f"(full log: lucy logtail harvest_proof)")

    log_path.write_text("\n".join(captured), encoding="utf-8")
    return 0 if verdict else 1


if __name__ == "__main__":
    sys.exit(main())
