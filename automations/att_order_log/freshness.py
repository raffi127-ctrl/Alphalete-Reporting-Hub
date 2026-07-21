"""Readiness probe for the ATT B2B Order Log — is today's ORDERLOG extract in?

This is the Layer-2 freshness gate that lets att_order_log behave like Lucy 1's
Box board in the orchestrator: if the Tableau data isn't up to date the pass
skips it and circles back to re-probe before finishing, instead of running it on
a fixed clock. (readiness.py dispatches probe type "att_orderlog" here.)

HOW: fetch a NARROW window of the same ATTTRACKER-B2B/ORDERLOG.csv the report
pulls — Start/End = the last couple of days, so it's a tiny/fast download, not
the ~120MB 60-day export — through Carlos's real-Chrome CDP session (the same
auth path run.py uses; a patchright/warm session gets a different Tableau
identity and the wrong slice). Then readiness._csv_covers_date checks the max
`sp.Order Date (copy)` reaches the target day.

SEPARATE FILE on purpose: run.py / metrics_shot.py are edited by other sessions;
this only READS run.py's URL/auth helpers, so it never conflicts. Kept
self-contained and best-effort — it raises to the probe, which fail-opens.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

# Column carrying the order date in the raw ORDERLOG crosstab (see sheet.py).
DATE_COL = "sp.Order Date (copy)"


def _narrow_csv_url(target: dt.date, days: int = 3) -> str:
    """The ORDERLOG .csv for a SHORT window ending at `target` — same endpoint as
    run._csv_url but a few days wide, so the probe fetch is small and quick."""
    start = target - dt.timedelta(days=days)
    return ("https://us-east-1.online.tableau.com"
            "/t/sci/views/ATTTRACKER-B2B/ORDERLOG.csv?:refresh=yes"
            "&Start%20Date={}&End%20Date={}").format(
                start.isoformat(), target.isoformat())


def fetch_narrow_csv(target: dt.date, dest: Path, *, log=lambda *_: None) -> Path:
    """Download a narrow-window ORDERLOG csv to `dest` via Carlos's real-Chrome
    CDP session (reuses run.py's exact auth path). Raises on any failure — the
    caller (the readiness probe) fail-opens on error, so this never needs to
    swallow. Kept parallel to run._pull but with the small window."""
    import time

    from patchright.sync_api import sync_playwright

    from automations.shared import tableau_patchright as tp
    from automations.vantura_churn import cdp_pull

    cdp_pull._kill_ours()
    proc = cdp_pull._launch()
    log("  [probe cdp] real Chrome pid={}; waiting 20s".format(proc.pid))
    time.sleep(20)
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(
                "http://127.0.0.1:{}".format(cdp_pull.CDP_PORT))
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            tp._ensure_tableau_authenticated(page, verbose=False,
                                             allow_form_login=True)
            r = page.context.request.get(_narrow_csv_url(target), timeout=120_000)
            body = r.body() or b""
            log("  [probe csv] status={} bytes={:,}".format(r.status, len(body)))
            if r.status != 200 or len(body) < 200:
                raise RuntimeError(
                    "orderlog probe export failed: status={} bytes={}".format(
                        r.status, len(body)))
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(body)
            return dest
    finally:
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass
        cdp_pull._kill_ours()


def _selftest() -> int:
    """Live check, RUN ON LUCY 2: pull a narrow ORDERLOG window and report the
    freshness verdict for today (expect READY this evening) and tomorrow (expect
    NOT-ready — no future orders). Proves the probe's pull + date logic against
    the real extract before it's wired into att_order_log's readiness. Writes
    nothing to any Sheet/report; only a temp CSV.

        lucy rerun test_att_orderlog_freshness --machine \"Lucy 2\"
    """
    import tempfile
    import time

    from automations.day_orchestrator.readiness import _csv_covers_date

    target = dt.date.today()
    out = Path(tempfile.gettempdir()) / "att_orderlog_freshness_selftest.csv"
    print(f"[selftest] fetching narrow ORDERLOG window ending {target} …", flush=True)
    t0 = time.monotonic()
    try:
        fetch_narrow_csv(target, out, log=print)
    except Exception as e:  # noqa: BLE001
        print(f"[selftest] FETCH FAILED: {type(e).__name__}: {e}", flush=True)
        print("=== done ===", flush=True)
        return 1
    took = time.monotonic() - t0
    print(f"[selftest] fetched in {took:.0f}s -> {out.stat().st_size:,} bytes", flush=True)
    for label, tgt in (("today", target),
                       ("tomorrow", target + dt.timedelta(days=1))):
        ok, why = _csv_covers_date(out, DATE_COL, tgt, 1)
        print(f"[selftest] {label} ({tgt}): ready={ok} — {why}", flush=True)
    print("=== done ===", flush=True)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_selftest())
