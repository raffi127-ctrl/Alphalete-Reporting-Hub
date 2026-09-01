"""READ-ONLY: can the add path actually select RES-AT&T on the live page?

Run:  lucy --machine "Lucy 3" rerun digi_docs_campaign_probe

WHY (Megan 2026-08-31, "people will only get res at&t - no water or primo?").

The campaign fix is real but it was UNPROVEN against OwnerVille, and the usual
ways of proving it do not reach it:

  • a DRY add returns "WOULD add" from find_rep and never gets as far as
    choosing a campaign, so --dry-run can never exercise this
  • a LIVE add would prove it by adding a real person to a real campaign,
    which is not a test
  • "found X under RES-AT&T" in today's logs is find_rep LOCATING people
    Megan re-added by hand — it says nothing about what our add would pick

So this does the one thing in between: open View Progress and run the real
_select_campaign against the real dropdown, then report which option it landed
on. That is the whole risk — the label carries an ampersand and there are
lookalikes — and it is answerable without adding anybody.

It selects a dropdown value and reads the page. It adds nobody, sends nothing,
and touches no Sheet.
"""
from __future__ import annotations

import argparse

from automations.digi_docs import config


def main(argv=None) -> int:
    from automations.digi_docs import ownerville as ov
    from automations.headshots.ov_upload import (
        VIEW_PROGRESS_P, _campaign_select,
    )

    ap = argparse.ArgumentParser()
    ap.add_argument("--want", default=config.ADD_CAMPAIGN,
                    help="campaign to select (default: config.ADD_CAMPAIGN)")
    args = ap.parse_args(argv)

    with ov.session(headless=True) as page:
        from automations.b2b_dispositions.capture import capture_rqst
        rqst = capture_rqst(page)
        page.set_default_navigation_timeout(90000)
        page.goto(f"https://v2.ownerville.com/index.cfm?p={VIEW_PROGRESS_P}"
                  f"&rqst={rqst}", wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=60000)
        except Exception:                       # noqa: BLE001
            pass

        options = [o.strip() for o in
                   _campaign_select(page).locator("option").all_inner_texts()
                   if o.strip()]
        print("campaigns on the page:")
        for o in options:
            print(f"   · {o}")
        print()

        try:
            got = ov._select_campaign(page, args.want, verbose=False)
        except ov.Refused as e:
            print(f"⛔ REFUSED — {e}")
            print("   An add would stop here rather than land on the wrong "
                  "campaign, which is the intended behaviour, but it means "
                  "nobody can be added until the name matches.")
            return 2

        print(f"✅ selected: {got!r}")
        if got.strip().lower() != args.want.strip().lower():
            print(f"   ⚠ that is a SUBSTRING match, not exact — wanted "
                  f"{args.want!r}. Check it is the right one.")
            return 2
        print("\nAn add would put the new start on this campaign. "
              "Nobody was added and nothing was sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
