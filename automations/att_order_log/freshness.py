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


def _narrow_csv_url(target: dt.date, days: int = 2) -> str:
    """The ORDERLOG .csv for a SHORT window ending at `target` — same endpoint as
    run._csv_url but a few days wide, so the probe fetch is small and quick."""
    start = target - dt.timedelta(days=days)
    return ("https://us-east-1.online.tableau.com"
            "/t/sci/views/ATTTRACKER-B2B/ORDERLOG.csv?:refresh=yes"
            "&Start%20Date={}&End%20Date={}").format(
                start.isoformat(), target.isoformat())


def fetch_narrow_csv(target: dt.date, dest: Path, *, log=lambda *_: None) -> Path:
    """Download a narrow-window ORDERLOG csv to `dest` via Carlos's real-Chrome
    CDP session and Tableau identity (a patchright/ownerville-SSO session is a
    DIFFERENT identity that doesn't see his order rows). Raises on any failure —
    the caller (the readiness probe) fail-opens, so this never needs to swallow.

    NON-DISRUPTIVE by design: the probe and the real CDP reports (att_order_log,
    vantura_churn) share ONE profile (vantura_cdp_profile) + port 9246, and
    _kill_ours would abort a report mid-pull. So this NEVER calls _kill_ours: it
    REUSES a CDP Chrome that's already up (on its own new page, leaving the
    report's pages untouched), launches its OWN only when none is up, and kills
    only a Chrome it started. If the profile is busy and no session answers, it
    raises -> the probe returns not-ready and the fallback floor backstops it."""
    import time

    from patchright.sync_api import sync_playwright

    from automations.shared import tableau_patchright as tp
    from automations.vantura_churn import cdp_pull

    port = cdp_pull.CDP_PORT
    with sync_playwright() as p:
        def _connect():
            try:
                return p.chromium.connect_over_cdp(
                    "http://127.0.0.1:{}".format(port), timeout=2000)
            except Exception:  # noqa: BLE001
                return None

        browser = _connect()
        launched = None
        if browser is not None:
            log("  [probe cdp] reusing live CDP session (no launch)")
        else:
            launched = cdp_pull._launch()          # our own; never _kill_ours
            log("  [probe cdp] launched own Chrome pid={}".format(launched.pid))
            for _ in range(18):                    # poll up to ~18s for CDP
                time.sleep(1)
                browser = _connect()
                if browser is not None:
                    break
        if browser is None:
            raise RuntimeError("CDP session not reachable (profile busy?) — defer")
        try:
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.new_page()                  # OUR page; report's stay untouched
            try:
                tp._ensure_tableau_authenticated(page, verbose=False,
                                                 allow_form_login=True)
                r = page.context.request.get(_narrow_csv_url(target),
                                             timeout=120_000)
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
                    page.close()                   # close only our page
                except Exception:  # noqa: BLE001
                    pass
        finally:
            if launched is not None:               # kill ONLY a Chrome WE started
                try:
                    launched.terminate()
                except Exception:  # noqa: BLE001
                    pass


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
