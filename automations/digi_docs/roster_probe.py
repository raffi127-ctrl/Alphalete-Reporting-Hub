"""READ-ONLY: why does the View Progress roster read stop at one page?

Run:  lucy --machine "Lucy 3" rerun digi_docs_roster_probe
      (after 4pm -- the send tick shares Lucy 3's one OwnerVille session)

WHY (2026-09-21). roster_check and the add pass both logged
"RES-AT&T: read 24, table says 144  ⛔ INCOMPLETE". 24 is one page. The
"show every row" step (ownerville._show_all_entries) picks the page-length
menu with `.first` and no `:visible` -- the same mistake that once had the
campaign picker grab a hidden select#state -- so the suspicion is it resizes a
hidden table and leaves the real one on page one. This prints what is actually
on the page instead of guessing a fourth time.

It changes the table's view (campaign, Show All, rows per page) and reads.
It adds nobody, sends nothing, and touches no Sheet.
"""
from __future__ import annotations

from automations.digi_docs import config


_LENGTH_SEL = ("div[id$='_length'] select, div.dataTables_length select, "
               "select[name$='_length']")


def _describe_length_menus(page) -> None:
    menus = page.locator(_LENGTH_SEL)
    n = menus.count()
    print(f"page-length menus on the page: {n}")
    for i in range(n):
        m = menus.nth(i)
        try:
            vis = m.is_visible()
            opts = m.evaluate("el => [...el.options].map(o => o.value + '=' + "
                              "o.text.trim())")
            ident = m.evaluate("el => (el.name || '') + ' #' + (el.id || '')")
        except Exception as e:                  # noqa: BLE001
            print(f"   [{i}] unreadable: {type(e).__name__}")
            continue
        print(f"   [{i}] visible={vis}  {ident}  options={opts}")


def _info(page) -> str:
    try:
        return page.locator(".dataTables_info:visible, div[id$='_info']:visible"
                            ).first.inner_text(timeout=4000).strip()
    except Exception:                           # noqa: BLE001
        return "(no visible info line)"


def main(argv=None) -> int:
    from automations.digi_docs import ownerville as ov
    from automations.headshots.ov_upload import (
        VIEW_PROGRESS_P, _campaign_select, _show_all,
    )

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
        _campaign_select(page).select_option(label=config.ADD_CAMPAIGN)
        page.wait_for_timeout(3000)
        _show_all(page)
        page.wait_for_timeout(3000)

        print(f"campaign: {config.ADD_CAMPAIGN}")
        print(f"before: {_info(page)} · rows in DOM: "
              f"{page.locator('tbody tr:visible').count()}\n")
        _describe_length_menus(page)

        vis = page.locator(_LENGTH_SEL).filter(visible=True)
        if not vis.count():
            print("\n⛔ no VISIBLE page-length menu -- the fix is not :visible")
            return 2
        opts = vis.first.evaluate("el => [...el.options].map(o => o.value)")
        size = {v: (10 ** 9 if int(v) < 0 else int(v))
                for v in opts if v.lstrip("-").isdigit()}
        best = max(size, key=size.get)
        vis.first.select_option(value=best)
        page.wait_for_timeout(5000)
        print(f"\nafter picking '{best}' on the VISIBLE menu: {_info(page)} · "
              f"rows in DOM: {page.locator('tbody tr:visible').count()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
