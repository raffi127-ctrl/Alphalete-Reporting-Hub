"""Probe NDS Weekly Metrics (Rep) to see how to pull the Insurance % values.

The UI crosstab download FAILS for this view class (React ignores the worksheet
thumbnail click). The HTTP helper (tableau_http) is ALSO dead on the mini — it
attaches to a CDP debug Chrome on :9222 that no longer runs (patchright now).

So this probe fetches the view's .csv endpoint through the PATCHRIGHT tableau
session's authenticated request context (shares the SSO cookies, no CDP needed),
then uploads the CSV to the Lucy↔Megan Slack DM so Claude can read the real
columns + whether per-owner Total rows are present before wiring the fill.

    lucy rerun insurance_probe

Temporary — remove once the Insurance % pull is wired.
"""
from __future__ import annotations

import ssl
from pathlib import Path

import certifi

from automations.shared.tableau_patchright import tableau_session

CSV_URL = ("https://us-east-1.online.tableau.com/t/sci/views/"
           "NDS-SNRES-ATT-OOFWorkbook/NDSWeeklyMetricsRep.csv")
MEGAN = "U045Z8N0ZQC"


def _fetch_csv(out: Path) -> None:
    with tableau_session(verbose=True) as page:
        # context.request shares the SSO auth cookies but isn't a same-origin
        # browser fetch, so no CORS wall. 120s for a big export.
        resp = page.context.request.get(CSV_URL, timeout=120_000)
        if not resp.ok:
            raise RuntimeError(f"HTTP {resp.status} from .csv endpoint")
        out.write_bytes(resp.body())


def _peek(out: Path) -> str:
    from automations.alphalete_org_report import tableau_http
    try:
        rows = tableau_http.parse_csv(out)
    except Exception:
        rows = [ln.split(",") for ln in
                out.read_text(encoding="latin-1", errors="replace").splitlines()[:400]]
    if not rows:
        return "EMPTY csv"
    header = rows[0]
    ins_i = next((i for i, h in enumerate(header) if "nsurance" in h.lower()), None)
    owner_i = next((i for i, h in enumerate(header) if "owner" in h.lower()), None)
    rep_i = next((i for i, h in enumerate(header)
                  if h.strip().lower() in ("rep", "rep name")), None)
    total_rows = 0
    if rep_i is not None:
        total_rows = sum(1 for r in rows[1:]
                         if rep_i < len(r) and r[rep_i].strip().lower() in ("total", ""))
    khalil = "?"
    if owner_i is not None and ins_i is not None:
        for r in rows[1:]:
            if owner_i < len(r) and "khalil" in r[owner_i].lower():
                khalil = r[ins_i] if ins_i < len(r) else "?"
                break
    return (f"{len(rows)-1} rows; cols={len(header)}; "
            f"insurance={header[ins_i] if ins_i is not None else 'MISSING'!r}; "
            f"owner_col={'y' if owner_i is not None else 'n'}; "
            f"rep_col={'y' if rep_i is not None else 'n'}; "
            f"total/blank-rep rows={total_rows}; khalil={khalil!r}")


def _post_to_slack(out: Path, summary: str) -> str:
    from automations.shared import slack_metrics_post as smp
    from slack_sdk import WebClient
    tok = smp._load_token()
    client = WebClient(token=tok, ssl=ssl.create_default_context(cafile=certifi.where()))
    dm = client.conversations_open(users=MEGAN)["channel"]["id"]
    client.files_upload_v2(
        channel=dm, file=str(out), filename="insurance_probe.csv",
        title="Insurance% NDS probe",
        initial_comment=f"🔧 Insurance% probe — NDS Weekly Metrics (Rep) via patchright .csv. {summary}")
    return "posted CSV to Megan's Slack DM"


def main() -> int:
    out = Path("output") / "_insurance_probe.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        _fetch_csv(out)
    except Exception as e:  # noqa: BLE001
        print(f"INSURANCE PROBE VERDICT: ❌ .csv fetch failed — "
              f"{type(e).__name__}: {str(e)[:160]}")
        return 1
    summary = _peek(out)
    try:
        posted = _post_to_slack(out, summary)
    except Exception as e:  # noqa: BLE001
        posted = f"Slack upload failed ({type(e).__name__}: {str(e)[:80]})"
    print(f"INSURANCE PROBE VERDICT: ✓ .csv OK — {summary} — {posted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
