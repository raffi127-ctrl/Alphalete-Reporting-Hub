"""Fiber Metrics — Raf's SaraPlus Sales Order History pull (RUNS ON LUCY 1).

Carlos 2026-10-08: "yes lets make this come from sara plus instead" — the
Fiber Order Log + Pending Orders should read Raf's SaraPlus (near-live), not
Tableau (days behind), mirroring his B2B setup.

HOW: Raf's dealer login + Chrome profile already live on Lucy 1
(alphalete_sales_board.config — NOT the B2B dealer). This reuses:
  * shared.saraplus.login_healing     (the sweep's own login path)
  * rc_contact_sync.sara              (order-history panel drivers — the
                                       SaraPlus UI is the same product, only
                                       the dealer differs)
  * alphalete_sales_board.run.Lock    (the sweep holds the profile most of
                                       each 5-min cycle — we WAIT politely
                                       instead of stacking a second Chrome
                                       on the same profile)

OUTPUT: the raw SOH csv, base64'd into the control sheet tab 'FIB SOH' for
Lucy 2's fiber_metrics to decode and build from (same relay pattern the
office mini uses toward Lucy 1). Always prints the export HEADER + row
count + how many rows carry crew reps — the first runs are probes; nothing
downstream trusts a column until it has been seen.

    lucy rerun fiber_sara_pull            (Lucy 1 / "Mini Control" tab)
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "output" / "fiber_metrics"
SOH_TAB = "FIB SOH"
WINDOW_DAYS = 31          # same hard rule as the B2B order log


def _wait_for_profile(log=print, max_wait_s: int = 1200):
    """The sweep's Lock SKIPS when held; we instead wait our turn — a stacked
    Chrome on the sweep's profile corrupts it for both of us."""
    from automations.alphalete_sales_board.run import Lock
    waited = 0
    while True:
        lk = Lock()
        lk.__enter__()
        if lk.held:
            return lk
        if waited >= max_wait_s:
            raise RuntimeError(
                "SaraPlus profile busy for %ds — giving up this pass "
                "(the sweep owns it; rerun later)" % waited)
        log(f"[fib-sara] profile busy (sweep running) — waiting 30s "
            f"({waited}s so far)")
        time.sleep(30)
        waited += 30


def _open_soh_panel(page, log=print) -> None:
    """Dealer-agnostic 'Detail Reports -> Sales Order History'.

    The B2B helper posts a tab index captured off the wire for THAT dealer
    ("3:0"); Raf's hub orders its tabs differently (first probe 2026-10-08:
    panel never appeared). Same postback mechanic, but the index is READ
    from the tab strip by text, every run."""
    from automations.rc_contact_sync import config as RC
    from automations.rc_contact_sync import sara

    if sara.panel_loaded(page):
        return
    tabs = page.evaluate(
        """() => {
             const out = [];
             const tops = document.querySelectorAll(
                 '.RadTabStrip .rtsUL > .rtsLI');
             tops.forEach((li, i) => {
               const t = li.querySelector('.rtsTxt');
               out.push([String(i), t ? t.textContent.trim() : '']);
               li.querySelectorAll('.rtsUL .rtsLI').forEach((c, j) => {
                 const ct = c.querySelector('.rtsTxt');
                 out.push([i + ':' + j, ct ? ct.textContent.trim() : '']);
               });
             });
             return out;
           }""")
    for ix, txt in tabs:
        log(f"  TAB {ix}: {txt}")
    hit = next((ix for ix, txt in tabs
                if ":" in ix and "order history" in txt.lower()), None)
    if hit is None:
        # child tabs may not be in the DOM until the parent expands — fall
        # back to probing every parent's first few children blind.
        parents = [ix for ix, _t in tabs if ":" not in ix]
        cands = [f"{p}:{c}" for p in parents for c in range(3)]
    else:
        cands = [hit]
    for arg_ix in cands:
        posted = page.evaluate(
            """(cfg) => {
                 const t = document.getElementsByName('__EVENTTARGET')[0];
                 const a = document.getElementsByName('__EVENTARGUMENT')[0];
                 if (!t || !a) return 'no fields';
                 t.value = cfg.target;
                 a.value = JSON.stringify({type: 0, index: cfg.ix});
                 const f = document.getElementById(cfg.form)
                       || document.forms[0];
                 f.submit();
                 return 'posted';
               }""",
            {"target": RC.TAB_POSTBACK_TARGET, "ix": arg_ix,
             "form": RC.FORM_ID})
        if posted != "posted":
            continue
        try:
            page.wait_for_load_state("networkidle",
                                     timeout=RC.NAV_TIMEOUT_MS)
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(1500)
        if sara.panel_loaded(page):
            log(f"  Sales Order History panel loaded (tab {arg_ix})")
            return
        log(f"  tab {arg_ix}: not the SOH panel — next")
    raise RuntimeError("Sales Order History tab not found on this hub — "
                       "see the TAB list above")


def pull(start: dt.date, end: dt.date, *, headless: bool = True,
         log=print) -> bytes:
    from patchright.sync_api import sync_playwright

    from automations.alphalete_sales_board import config as AC
    from automations.rc_contact_sync import config as RC
    from automations.rc_contact_sync import sara
    from automations.rc_contact_sync.status_probe import _export_csv
    from automations.shared import saraplus as _sp

    cr = AC.creds()
    lk = _wait_for_profile(log=log)
    try:
        with sync_playwright() as p:
            ctx, page, base = _sp.login_healing(
                p, AC.PROFILE_DIR, cr["email"], cr["password"],
                headless=headless, creds_hint=str(AC.CREDS_PATH), log=log)
            try:
                log(f"[fib-sara] logged in as {cr['email']}")
                page.goto(base + RC.HUB_PATH, wait_until="networkidle",
                          timeout=RC.NAV_TIMEOUT_MS)
                _open_soh_panel(page, log=log)
                sara._set_telerik_date(page, RC.FIELD_START, start)
                sara._set_telerik_date(page, RC.FIELD_END, end)
                try:
                    sara._set_customer_type(page, RC.CUSTOMER_TYPE_BOTH,
                                            log=log)
                    # Customer Type autoposts back and can reset the dates.
                    sara._set_telerik_date(page, RC.FIELD_START, start)
                    sara._set_telerik_date(page, RC.FIELD_END, end)
                except Exception as e:  # noqa: BLE001 — RES dealer may lack it
                    log(f"[fib-sara] no Customer Type control here ({e}) — "
                        "continuing with the dealer default")
                sara._submit(page, log=log)
                data = _export_csv(page, log)
                if not data or len(data) < 200:
                    raise RuntimeError("SOH export came back empty")
                return data
            finally:
                ctx.close()
    finally:
        lk.__exit__(None, None, None)


def describe(data: bytes, log=print) -> None:
    from automations.total_knocks import guests
    text = data.decode("utf-8-sig", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        log("[fib-sara] EMPTY csv")
        return
    header = rows[0]
    for i in range(0, len(header), 6):
        log(f"SOHH{i // 6}: " + " | ".join(header[i:i + 6]))
    log(f"[fib-sara] {len(rows) - 1} data row(s)")
    norm = [h.strip().lower() for h in header]
    i_rep = next((i for i, h in enumerate(norm)
                  if "user name" in h or h == "rep"), None)
    if i_rep is None:
        log("[fib-sara] no rep/user-name column spotted — see header above")
        return
    crew = guests.roster("Rafael Hidalgo", "Carlos Hidalgo")
    toks = [guests._tokens(n) for n in crew]
    hits = sum(1 for r in rows[1:] if len(r) > i_rep and any(
        guests._subseq(ct, guests._tokens(r[i_rep]))
        or guests._subseq(guests._tokens(r[i_rep]), ct) for ct in toks))
    log(f"[fib-sara] crew rows: {hits}/{len(rows) - 1}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="fiber_sara_pull")
    ap.add_argument("--today", default=None, metavar="YYYY-MM-DD")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--no-push", action="store_true",
                    help="probe only — don't relay the csv to the mini")
    a = ap.parse_args(argv)
    today = (dt.date.fromisoformat(a.today) if a.today else dt.date.today())
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    data = pull(today - dt.timedelta(days=WINDOW_DAYS), today,
                headless=not a.headed)
    raw = OUT_DIR / f"fib_soh_{today.isoformat()}.csv"
    raw.write_bytes(data)
    print(f"[fib-sara] export saved {raw.name} ({len(data):,} bytes)")
    describe(data)
    if not a.no_push:
        from automations.rc_contact_sync.status_probe import _upload_bytes
        stamped = (b"#pulled=" + dt.datetime.now().isoformat().encode()
                   + b"\n" + data)
        ok = _upload_bytes(stamped, SOH_TAB, log=print)
        print(f"[fib-sara] relay -> {SOH_TAB!r}: {ok}")
    print("=== done ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
