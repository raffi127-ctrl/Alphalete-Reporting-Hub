"""Probe NDS Weekly Metrics (Rep) to see how to pull the Insurance % values.

The UI crosstab download FAILS for this view class (React ignores the worksheet
thumbnail click — see tableau_http.py), which is why opt_nds pulls it via the
HTTP .csv endpoint instead. So this probe pulls it the SAME way (HTTP, base view
= Last Week, all owners) and UPLOADS the CSV to the Lucy↔Megan Slack DM so Claude
can read the exact columns + whether per-owner Total rows are present, before
wiring the fill. Compact verdict also lands in `lucy status`.

    lucy rerun insurance_probe

Temporary — remove once the Insurance % pull is wired.
"""
from __future__ import annotations

import ssl
from pathlib import Path

import certifi

from automations.alphalete_org_report import tableau_http

WORKBOOK = "NDS-SNRES-ATT-OOFWorkbook"
VIEW = "NDSWeeklyMetricsRep"
MEGAN = "U045Z8N0ZQC"


def _peek(rows: list[list[str]]) -> str:
    if not rows:
        return "EMPTY csv"
    header = rows[0]
    ins_i = next((i for i, h in enumerate(header) if "nsurance" in h.lower()), None)
    owner_i = next((i for i, h in enumerate(header) if "owner" in h.lower()), None)
    rep_i = next((i for i, h in enumerate(header) if h.strip().lower() in ("rep", "rep name")), None)
    # Count rows that look like per-owner subtotals (Rep cell == 'Total' or blank).
    total_rows = 0
    if rep_i is not None:
        for r in rows[1:]:
            if rep_i < len(r) and r[rep_i].strip().lower() in ("total", ""):
                total_rows += 1
    khalil = "?"
    if owner_i is not None and ins_i is not None:
        for r in rows[1:]:
            if owner_i < len(r) and "khalil" in r[owner_i].lower():
                khalil = r[ins_i] if ins_i < len(r) else "?"
                break
    return (f"{len(rows)-1} data rows; cols={len(header)}; "
            f"insurance_col={header[ins_i] if ins_i is not None else 'MISSING'!r}; "
            f"owner_col={'yes' if owner_i is not None else 'no'}; "
            f"rep_col={'yes' if rep_i is not None else 'no'}; "
            f"total/blank-rep rows={total_rows}; khalil_insurance={khalil!r}")


def _post_to_slack(out: Path, summary: str) -> str:
    from automations.shared import slack_metrics_post as smp
    from slack_sdk import WebClient
    tok = smp._load_token()
    client = WebClient(token=tok, ssl=ssl.create_default_context(cafile=certifi.where()))
    dm = client.conversations_open(users=MEGAN)["channel"]["id"]
    client.files_upload_v2(
        channel=dm, file=str(out), filename="insurance_probe.csv",
        title="Insurance% NDS probe",
        initial_comment=f"🔧 Insurance% probe — NDS Weekly Metrics (Rep) via HTTP. {summary}")
    return "posted CSV to Megan's Slack DM"


def main() -> int:
    out = Path("output") / "_insurance_probe.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        tableau_http.download_view_csv(WORKBOOK, VIEW, out)
    except Exception as e:  # noqa: BLE001
        print(f"INSURANCE PROBE VERDICT: ❌ HTTP pull failed — "
              f"{type(e).__name__}: {str(e)[:160]}")
        return 1
    try:
        rows = tableau_http.parse_csv(out)
    except Exception as e:  # noqa: BLE001
        rows = []
        print(f"  parse_csv failed: {e}")
    summary = _peek(rows)
    try:
        posted = _post_to_slack(out, summary)
    except Exception as e:  # noqa: BLE001
        posted = f"Slack upload failed ({type(e).__name__}: {str(e)[:80]})"
    print(f"INSURANCE PROBE VERDICT: ✓ HTTP OK — {summary} — {posted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
