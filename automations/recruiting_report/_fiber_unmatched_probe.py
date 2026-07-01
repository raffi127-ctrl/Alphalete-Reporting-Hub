"""Verify which ATT Focus Report ICD tabs come up EMPTY in the Fiber Lead pull,
and for each, fuzzy-suggest the exact Fiber-view owner spelling — so we know
which ICD-alias entries to add (instead of hunting names by hand). Also flags
any MATCHED tab whose penetration is a bad >100% value (the Aya Al-Khafaji case).

Posts the report to Megan's Slack DM (too long for the mini's status tail).

    lucy rerun fiber_unmatched

Temporary — remove once the aliases are added.
"""
from __future__ import annotations

import os
os.environ.setdefault("CAPTAINSHIP", "Raf")  # ATT Focus Report — set before fill imports

import difflib
import ssl
from pathlib import Path

import certifi

from automations.recruiting_report import fill
from automations.recruiting_report import opt_phase as op
from automations.recruiting_report.opt_phase import _fiber_name_candidates, _norm
from automations.shared.tableau_patchright import download_crosstab_patchright

MEGAN = "U045Z8N0ZQC"


def _pct_over_100(pen: str) -> bool:
    try:
        return float(str(pen).replace("%", "").strip()) > 100
    except Exception:
        return False


def main() -> int:
    out = Path("output") / "_fiber_unmatched_raw.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    download_crosstab_patchright(op.FIBER_BULK_VIEW_URL, op.FIBER_BULK_CROSSTAB_SHEET,
                                 out, verbose=False)
    lines = out.read_bytes().decode("utf-16").replace("\r\n", "\n").split("\n")
    header = lines[0].split("\t")

    def col(needle: str) -> int:
        nl = needle.lower()
        return next(i for i, h in enumerate(header) if nl in h.lower())

    oi, pi = col("account_owner_name"), col("office lead penetration")
    by_owner = {}          # first row per owner
    for ln in lines[1:]:
        c = ln.split("\t")
        if len(c) <= max(oi, pi):
            continue
        o = c[oi].strip()
        if o and o.lower() not in ("grand total", "total") and o not in by_owner:
            by_owner[o] = c[pi].strip()
    owners = list(by_owner)
    owners_norm = {_norm(o): o for o in owners}

    try:
        as_owner_map = {c["sheet_tab"]: c.get("as_owner", "")
                        for c in fill.load_mapping()["confirmed"]}
    except Exception:
        as_owner_map = {}
    try:
        from automations.focus_office_att import aliases as _al
        aliases_map = _al.load_aliases()
    except Exception:
        aliases_map = {}

    tabs = [c["sheet_tab"] for c in fill.load_mapping()["confirmed"]]
    unmatched, weird = [], []
    for tab in tabs:
        matched_owner = None
        for cand in _fiber_name_candidates(tab, as_owner_map, aliases_map):
            if _norm(cand) in owners_norm:
                matched_owner = owners_norm[_norm(cand)]
                break
        if matched_owner is None:
            sug = difflib.get_close_matches(tab, owners, n=2, cutoff=0.5)
            unmatched.append((tab, sug))
        elif _pct_over_100(by_owner[matched_owner]):
            weird.append((tab, matched_owner, by_owner[matched_owner]))

    out_lines = [f"🔧 *Fiber Lead verify* — {len(tabs)} ATT tabs, crosstab has "
                 f"{len(owners)} owners.",
                 f"*Unmatched (need alias): {len(unmatched)}*"]
    for tab, sug in unmatched:
        s = "  |  ".join(sug) if sug else "(no close owner — likely absent from Fiber data)"
        out_lines.append(f"• `{tab}`  →  {s}")
    if weird:
        out_lines.append(f"*Matched but bad >100% penetration: {len(weird)}*")
        for tab, owner, pen in weird:
            out_lines.append(f"• `{tab}` (owner {owner}) = {pen}")
    report = "\n".join(out_lines)

    print(f"FIBER VERIFY: {len(unmatched)} unmatched, {len(weird)} weird-pct "
          f"(of {len(tabs)} tabs); crosstab owners={len(owners)}")
    try:
        from automations.shared import slack_metrics_post as smp
        from slack_sdk import WebClient
        client = WebClient(token=smp._load_token(),
                           ssl=ssl.create_default_context(cafile=certifi.where()))
        dm = client.conversations_open(users=MEGAN)["channel"]["id"]
        client.chat_postMessage(channel=dm, text=report)
        print("posted fiber-unmatched report to Megan's DM")
    except Exception as e:  # noqa: BLE001
        print(f"slack post failed: {type(e).__name__}: {str(e)[:90]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
