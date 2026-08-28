"""Does USING the AppStream console renew its rqst token? Read-only probe.

WHY (Megan 2026-08-28: "test the console theory on lucy 1"). Three fleet-wide
outages and roughly ten fixes have all rested on an unexamined belief about what
re-issues the ~2h rqst SSO token. On 2026-08-27 token-identity logging finally
settled half of it: the storage_state re-hop does NOT renew. Lucy 1 and Lucy 3
both rode one token straight down to expiry —

    19:46  token B6BD16B4, 20m left
    19:52  token B6BD16B4, 14m left        -> EXPIRED 8:06PM, both machines

— while Lucy 2, over the same minutes, renewed. The standing difference is that
Lucy 2 USES the console all evening (applicant_push, resume_pushing) and the
other two hold an idle one and reload it every six minutes.

So the hypothesis is: the token is re-issued by real in-app navigation, not by
reloading or re-hopping. This probe tests it directly and refuses to guess:

  • it records the token id + expiry at EVERY step, so a renewal is attributed
    to the exact request that caused it rather than inferred from a later state;
  • it runs an IDLE-RELOAD control in the same session, because "navigation
    renews" and "any request after enough time renews" predict the same ending
    and only the control separates them;
  • it names what it cannot conclude. A run where nothing renews is evidence
    against the hypothesis only if the session was live throughout, so it says
    so explicitly.

READ-ONLY. It loads two report views (p=701 the console/Retention Details,
p=702 the aggregate Source Report), reads cookies, and writes nothing anywhere —
no Sheet, no Slack, no state file. It takes the report profile, so it yields
immediately if a real report is holding it.

    PYTHONPATH=. .venv/bin/python -m automations.shared.appstream_renew_probe
    PYTHONPATH=. .venv/bin/python -m automations.shared.appstream_renew_probe --settle-min 8
"""
from __future__ import annotations

import argparse
import datetime as dt
import time

APPSTREAM_BASE = "https://applicantstream.com/index.cfm"
# Read-only views. p=604 (the OAT one-app-at-a-time queue) is deliberately NOT
# here: it is where applicants get sent/removed/re-texted, and a diagnostic has
# no business loading a page whose whole purpose is acting on people.
NAV_VIEWS = [("p=701", "console / Retention Details"),
             ("p=702", "Source Report (aggregate counts)")]


def _tokens(ctx) -> list[tuple[str, float, float]]:
    """[(short id, expiry epoch, epoch WHEN READ)] for every applicantstream
    rqst cookie.

    The read time is captured here on purpose. The first version stored only the
    expiry and worked out "how long is left" in the print loop at the END of the
    run — so every row was measured against the same final instant, and a token
    that sat still for 64 minutes printed "20m left" on all five rows. Read
    naively that says the expiry slid forward in lockstep with the clock, i.e. a
    renewal mechanism nobody knew about. It says nothing of the sort; it is one
    number formatted five times. An instrument built to stop this project
    guessing must not be the thing that invents the finding."""
    now = time.time()
    out = []
    for c in ctx.cookies():
        if ("applicantstream" in (c.get("domain") or "")
                and (c.get("name") or "").lower().startswith("rqst_")):
            out.append((c["name"][len("rqst_"):][:8],
                        float(c.get("expires") or 0), now))
    return sorted(out)


def _fmt(toks) -> str:
    if not toks:
        return "NO TOKEN"
    return ", ".join(
        "{}({})".format(t, "no expiry" if not e else
                        "{:.0f}m left".format((e - read_at) / 60.0))
        for t, e, read_at in toks)


def _ids(toks) -> list:
    return sorted(t for t, _, _ in toks)


def _minted(toks, first) -> bool:
    """Did a token appear that was NOT there at the start?

    Set inequality is the wrong test and produced three false "TOKEN CHANGED"
    flags in the 2026-08-28 10:26 run: the session started with one ALREADY
    EXPIRED cookie beside the live one, the browser dropped it, and every later
    row differed from the first. A cookie being discarded is not the server
    issuing anything. Only a NEW id counts."""
    return bool(set(_ids(toks)) - set(_ids(first)))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pre-settle-min", type=float, default=0.0,
                    help="Hold the session this long BEFORE navigating, so the "
                         "navigation pass happens with the token near expiry. "
                         "The first run (2026-08-28 07:47) navigated with 78m "
                         "left on the freshest token and nothing minted — real, "
                         "but not the case anyone cares about. What has to be "
                         "ruled out is navigation INSIDE the last minutes.")
    ap.add_argument("--own-profile", action="store_true",
                    help="Run in a dedicated Chrome profile instead of the "
                         "reports' shared one. Required for a long hold: the "
                         "probe keeps the profile for its whole run, and a "
                         "70-minute diagnostic must not stand in front of a "
                         "scheduled report.")
    ap.add_argument("--settle-min", type=float, default=6.0,
                    help="Minutes to hold the session between the navigation "
                         "pass and the idle-reload control (default 6 — one "
                         "holder cycle, so the control matches what the holder "
                         "actually does).")
    a = ap.parse_args(argv)

    from automations.shared.tableau_patchright import (
        APPSTREAM_STORAGE_STATE, AppStreamBusy, appstream_direct_session)

    kw = {}
    if a.own_profile:
        kw["profile_dir"] = APPSTREAM_STORAGE_STATE.with_name(
            ".appstream_profile_renewprobe")

    steps: list[tuple[str, list]] = []
    try:
        with appstream_direct_session(headless=False, verbose=False,
                                      yield_if_busy=True, **kw) as page:
            ctx = page.context
            live = page.locator("#searchMC").count() > 0
            steps.append(("after restore (the reports' own reuse path)",
                          _tokens(ctx)))
            print("console rendered: {}".format("yes" if live else "NO"),
                  flush=True)
            if not live:
                print("-> no live console; nothing this probe says about "
                      "renewal would mean anything. Stopping.", flush=True)
                return 2

            if a.pre_settle_min:
                print(f"holding {a.pre_settle_min:g} min BEFORE navigating, so "
                      f"the token is near expiry when we do…", flush=True)
                time.sleep(a.pre_settle_min * 60)
                steps.append((f"after idling {a.pre_settle_min:g}m, before any "
                              f"navigation", _tokens(ctx)))

            for view, label in NAV_VIEWS:          # the hypothesis
                page.goto(f"{APPSTREAM_BASE}?{view}", wait_until="domcontentloaded")
                page.wait_for_timeout(2_500)
                steps.append((f"after navigating {view} — {label}", _tokens(ctx)))

            # THE CONTROL. Same elapsed time, same session, no navigation — just
            # the reload the holder has always done. If this renews too, the
            # difference is time and not use, and the hypothesis is wrong.
            print(f"holding {a.settle_min:g} min, then reloading in place "
                  f"(control)…", flush=True)
            time.sleep(a.settle_min * 60)
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(2_500)
            steps.append((f"after an idle reload (+{a.settle_min:g}m) — CONTROL",
                          _tokens(ctx)))
    except AppStreamBusy:
        print("a real report is holding the AppStream profile — try again "
              "later; this probe never takes the session from one.", flush=True)
        return 3
    except Exception as e:                                      # noqa: BLE001
        print(f"probe could not open the console: {type(e).__name__}: "
              f"{str(e)[:160]}", flush=True)
        return 1

    print("\n=== token at each step ===", flush=True)
    first = steps[0][1]
    for label, toks in steps:
        mark = "   <-- NEW TOKEN MINTED" if _minted(toks, first) else ""
        dropped = set(_ids(first)) - set(_ids(toks))
        if dropped and not mark:
            mark = "   (expired cookie dropped: {})".format(", ".join(sorted(dropped)))
        print(f"  {label:58} {_fmt(toks)}{mark}", flush=True)

    nav_rows = [st for st in steps if st[0].startswith("after navigating")]
    nav_changed = any(_minted(toks, first) for _, toks in nav_rows)
    ctl_changed = _minted(steps[-1][1], first)
    print("\n=== reading ===", flush=True)
    if nav_changed and not ctl_changed:
        print("Navigation renewed the token and an idle reload did not — this "
              "is what the hypothesis predicts. Make the holder navigate.",
              flush=True)
    elif nav_changed and ctl_changed:
        print("Both renewed, so this run cannot tell use from elapsed time. "
              "Re-run with a longer --settle-min before concluding anything.",
              flush=True)
    elif ctl_changed:
        print("The idle reload renewed but navigation did not — the opposite of "
              "the hypothesis. Do not act on this without a second run.",
              flush=True)
    else:
        print("Nothing renewed. Against the hypothesis, but only weakly: a "
              "token far from expiry may simply not be due yet. Note how much "
              "life it had above, and re-run inside the last ~30m.", flush=True)
    print(f"(run at {dt.datetime.now():%H:%M}, read-only — nothing was written)",
          flush=True)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
