"""READ-ONLY probe: which requests does Apex need when Lucy only READS payroll?

WHY (Eve + Megan 2026-11-16). The owner PNL on Lucy Eco will sign into the
owner's own Apex by herself (password + auth-app key kept on the owner's Mac).
That login can do everything in Apex, so the limit has to be Lucy's: her
browser will block every request to Apex that could CHANGE something, and let
through only the ones the read path needs. This probe writes that list down.

It runs the exact path carlos_payroll_pull already runs every Thursday on
Lucy 2 (Carlos's warm Apex window): Payroll Entry -> pay-period dropdown ->
newest completed period -> Export. While it does, it records every request
the page makes: METHOD, host, path, resource type, status. Never bodies,
never query VALUES (only their names) -- payroll stays out of the log.

The exported CSV is deleted right after the download is confirmed. Writes no
sheet, posts nothing, clicks nothing carlos_payroll_pull does not click.

    python -m automations.owner_pnl.probe_apex_requests      # Lucy 2 only
"""
from __future__ import annotations

import datetime as dt
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

# Methods that only read. Everything else is what the guard will block unless
# this probe shows the read path needs it.
READ_METHODS = {"GET", "HEAD", "OPTIONS"}


def shape(method: str, url: str, rtype: str = "") -> tuple:
    """(METHOD, host, path, sorted query NAMES, resource type) -- no values."""
    u = urlsplit(url)
    names = ",".join(sorted({k for k, _ in parse_qsl(u.query, keep_blank_values=True)}))
    return (method.upper(), u.netloc.lower(), u.path or "/", names, rtype or "")


def summarize(seen: dict) -> list:
    """Lines for the log: writes first (the ones the guard has to allow), then
    reads grouped by host. `seen` maps shape -> [count, statuses]."""
    writes = sorted(k for k in seen if k[0] not in READ_METHODS)
    reads = sorted(k for k in seen if k[0] in READ_METHODS)
    out = ["NON-READ requests (the guard must allow exactly these): %d" % len(writes)]
    for k in writes:
        n, st = seen[k]
        out.append("  %-6s %s%s%s  [%s] x%d status %s" % (
            k[0], k[1], k[2], ("?" + k[3]) if k[3] else "", k[4], n,
            ",".join(sorted(st)) or "-"))
    hosts = {}
    for k in reads:
        hosts.setdefault(k[1], 0)
        hosts[k[1]] += seen[k][0]
    out.append("READ requests by host (always allowed):")
    for h in sorted(hosts):
        out.append("  %s x%d" % (h, hosts[h]))
    return out


def main(argv=None) -> int:
    from automations.carlos_payroll_pull import run as AP

    AP.ensure_chrome()
    from patchright.sync_api import sync_playwright

    seen: dict = {}

    def on_req(req):
        try:
            k = shape(req.method, req.url, req.resource_type)
        except Exception:  # noqa: BLE001
            return
        seen.setdefault(k, [0, set()])[0] += 1

    def on_resp(resp):
        try:
            req = resp.request
            k = shape(req.method, req.url, req.resource_type)
            seen.setdefault(k, [0, set()])[1].add(str(resp.status))
        except Exception:  # noqa: BLE001
            pass

    tmp = Path(tempfile.mkdtemp(prefix="apex-probe-"))
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{AP.CDP_PORT}")
        ctx = browser.contexts[0]
        ctx.on("request", on_req)
        ctx.on("response", on_resp)
        page = ctx.pages[-1] if ctx.pages else ctx.new_page()
        # Force the full path (home -> in-app Payroll link) so its requests are
        # recorded even when the window already sits on Payroll Entry.
        page.goto(AP.APEX_URL, wait_until="domcontentloaded")
        AP.goto_payroll_entry(page)
        periods = AP.list_periods(page)
        today = dt.date.today()
        done = [pp for pp in periods if pp[2] < today]
        if not done:
            print("probe: no completed pay period in the dropdown")
            return 1
        idx, start, end = done[0]
        old_out = AP.OUT_DIR
        AP.OUT_DIR = tmp
        try:
            path = AP.export_period(page, idx, end)
            size = path.stat().st_size
        finally:
            AP.OUT_DIR = old_out
        page.wait_for_timeout(2000)
    for f in tmp.glob("*"):
        f.unlink()
    tmp.rmdir()
    print("probe: exported period ending %s (%d bytes), file deleted" % (end, size))
    for line in summarize(seen):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
