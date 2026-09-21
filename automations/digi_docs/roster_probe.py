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

        # ROUND 2 (2026-09-21, 18:01 run): one menu, visible, and picking 100
        # still left "Showing 1 to 25 of 143" -- the table ignores the control
        # entirely, which is also why Next never advanced. Two routes that do
        # not go through the controls:
        _try_datatables_api(page)
        _try_csv_export(page)
    return 0


def _try_datatables_api(page) -> None:
    """Ask DataTables itself to show every row.

    page.evaluate runs in an ISOLATED world under patchright, where the page's
    jQuery does not exist. A <script> tag runs in the page's own world, so the
    call goes in one and leaves its answer on <body> for us to read."""
    js = """
    (function () {
      var out = 'no jQuery';
      try {
        if (window.jQuery && jQuery.fn.dataTable) {
          var tables = jQuery.fn.dataTable.tables({visible: true});
          out = 'visible tables: ' + tables.length;
          if (tables.length) {
            var dt = jQuery(tables[0]).DataTable();
            var s = dt.settings()[0];
            out += ' · serverSide=' + !!(s.oFeatures && s.oFeatures.bServerSide)
                 + ' · ajax=' + !!s.ajax
                 + ' · rows known to DataTables=' + dt.rows().count();
            dt.page.len(-1).draw(false);
          }
        }
      } catch (e) { out += ' · ERROR ' + e; }
      document.body.setAttribute('data-roster-probe', out);
    })();
    """
    try:
        page.add_script_tag(content=js)
        page.wait_for_timeout(5000)
        said = page.locator("body").get_attribute("data-roster-probe")
    except Exception as e:                      # noqa: BLE001
        said = f"script failed: {type(e).__name__}"
    print(f"\nDataTables API: {said}")
    print(f"   after page.len(-1): {_info(page)} · rows in DOM: "
          f"{page.locator('tbody tr:visible').count()}")


def _try_csv_export(page) -> None:
    """The CSV button exports what DataTables holds, not what is on screen.
    Counts the rows; saves nothing past the probe."""
    import csv
    import io
    btn = page.locator("button:has-text('CSV'):visible, "
                       "a:has-text('CSV'):visible").first
    if not btn.count():
        print("\nCSV export: no visible CSV button")
        return
    try:
        with page.expect_download(timeout=30000) as dl:
            btn.click()
        path = dl.value.path()
        with open(path, newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.reader(fh))
        print(f"\nCSV export: {max(len(rows) - 1, 0)} data row(s) "
              f"(header: {rows[0][:4] if rows else '-'})")
    except Exception as e:                      # noqa: BLE001
        print(f"\nCSV export: failed — {type(e).__name__}: "
              f"{str(e).splitlines()[0][:120]}")


if __name__ == "__main__":
    raise SystemExit(main())
