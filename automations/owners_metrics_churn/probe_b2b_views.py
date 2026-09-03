"""READ-ONLY: why Carlos's and Luis's B2B churn pulls stopped finding 'ICD Churn'.

2026-09-03: both dropped with
    Couldn't find the 'ICD Churn' sheet in the Crosstab dialog — saw 4 thumb(s):
    ['1 Rep Churn', 'Churn National Average', 'Disconnect R…']
three attempts in a row (06:24 / 06:49 / 07:12 CT), clean the day before, while
Eveliz's view on the SAME workbook kept working. That is the known
republish-kills-the-custom-view shape, not a flake.

This probe answers the three questions needed before anyone touches Tableau, and
it writes NOTHING — no Sheet, no Slack, no manifest:

  1. Does the BASE CHURNRATES view (no custom-view GUID) still carry the
     'ICD Churn' worksheet? If yes, the dashboard is healthy and only the saved
     views died.
  2. What do the two GUID URLs actually load — which Crosstab thumbs, and does
     Tableau raise the "error occurred while loading the custom view … Re-create
     the custom view" banner? That banner NAMES the broken view and is what
     separates a dead view from a renamed worksheet.
  3. THE ONE THAT MATTERS: can the captain be selected from the URL instead?
     pull.py already overrides this workbook's product filter with a plain URL
     param (`Product Type (Broken Out)=WIRELESS`). If the captain field filters
     the same way, Carlos and Luis can hang off the BASE view and no
     republication can ever break them again — the custom views stop being a
     dependency instead of being re-created and re-broken next time.

Run it on Lucy (it needs that machine's ownerville session — the Tableau SSO
rides ownerville, which allows ONE session per account, so running it from
Windows would evict Lucy's holder and pause every report on the box):

    lucy rerun b2b_views_probe

Output: a verdict block in the log + output/b2b_views_probe/ (raw JSON, the
downloaded crosstabs, screenshots).
"""
from __future__ import annotations

import json
import tempfile
import urllib.parse
from pathlib import Path

from automations.shared.tableau_patchright import (
    tableau_session, download_crosstab_patchright)
from automations.owners_metrics_churn import pull

OUT = Path(__file__).resolve().parents[2] / "output" / "b2b_views_probe"

_SITE = "https://us-east-1.online.tableau.com/#/site/sci/views/"
_WB = "ATTTRACKER-B2B/CHURNRATES"
BASE_VIEW_URL = f"{_SITE}{_WB}?:iid=1"

# The two that dropped, exactly as pull.py holds them today.
BROKEN = [
    ("carlos", "B2BCarlos_Churn", pull.B2B_CARLOS_URL),
    ("luis", "B2BLuis_Churn", pull.B2B_LUIS_URL),
]
# The sibling that still works — the control. If this one ALSO looks wrong here,
# the problem is the probe, not the views.
CONTROL = ("eveliz", "B2BEveliz_Churn", pull.B2B_EVELIZ_URL)

# Candidate captain filter fields, most likely first. 'B2B Captain's Teams
# (SFDC)' is the field the captainship drafts filter B2B1-PAGER_CaptainView on,
# with values "Carlos's Team" / "Eveliz's Team" / "Luis's Team" (SmartCircle owns
# the value list — there is still no "Atef's Team", which is why he rides the
# all-teams slice). Whether CHURNRATES carries the same field is exactly what is
# unknown, so try the plausible spellings and report which one bites.
CAPTAIN_FIELDS = [
    "B2B Captain's Teams (SFDC)",
    "Captain's Bonus Teams",
    "B2B Captain's Team (SFDC)",
]
CAPTAIN_VALUES = {"carlos": "Carlos's Team", "luis": "Luis's Team"}


def log(msg: str = "") -> None:
    print(msg, flush=True)


def _filtered_url(field: str, value: str) -> str:
    """BASE view + the WIRELESS product param + a captain filter, URL-style."""
    q = (f"{urllib.parse.quote(field)}={urllib.parse.quote(value)}"
         f"&{pull._B2B_PRODUCT_PARAM}")
    return f"{BASE_VIEW_URL}&{q}"


def _thumbs_and_toast(pg, url: str, tag: str) -> dict:
    """Load a view and report what the Crosstab dialog offers + any error toast.

    Deliberately does NOT download: a failed Crosstab dialog stays open and hangs
    every later click, so the probe only ever LOOKS here and does its downloads
    through the shared driver, which re-navigates between attempts.
    """
    info: dict = {"tag": tag, "url": url, "thumbs": [], "toast": "", "ok": False}
    try:
        pg.goto(url, wait_until="domcontentloaded")
    except Exception as e:
        info["error"] = f"goto: {type(e).__name__}: {e}"
        return info
    viz = pg.frame_locator('iframe[title="Data Visualization"]')
    try:
        viz.locator(
            '[data-tb-test-id="viz-viewer-toolbar-button-download"]'
        ).wait_for(state="visible", timeout=90_000)
        info["ok"] = True
    except Exception as e:
        info["error"] = f"toolbar: {type(e).__name__}"
    pg.wait_for_timeout(4_000)

    # The banner NAMES the broken custom view — the single most useful string
    # here, and the one the production runs throw away (_clear_error_toast
    # dismisses it and continues).
    try:
        toast = viz.locator('[data-tb-test-id^="banner-error-toast"]')
        if toast.count():
            info["toast"] = " | ".join(
                " ".join((toast.nth(i).inner_text() or "").split())
                for i in range(min(toast.count(), 4)))
    except Exception:
        pass

    # Worksheet thumbnails, read from the sheet picker without committing to it.
    try:
        viz.locator(
            '[data-tb-test-id="viz-viewer-toolbar-button-download"]'
        ).click(timeout=15_000)
        pg.wait_for_timeout(1_500)
        for sel in ('[data-tb-test-id="download-flyout-crosstab-MenuItem"]',
                    'div[role="menuitem"]:has-text("Crosstab")'):
            try:
                item = pg.locator(sel)
                if item.count():
                    item.first.click(timeout=8_000)
                    break
            except Exception:
                continue
        pg.wait_for_timeout(3_000)
        names = pg.locator('[data-tb-test-id$="-CrosstabSheetThumbnail"], '
                           '[data-tb-test-id*="SheetThumbnail"]')
        info["thumbs"] = [(names.nth(i).inner_text() or "").strip()
                          for i in range(min(names.count(), 20))]
    except Exception as e:
        info["thumbs_error"] = f"{type(e).__name__}: {e}"
    # Leave the dialog behind rather than clicking out of it.
    try:
        pg.goto("about:blank", wait_until="domcontentloaded", timeout=10_000)
    except Exception:
        pass
    try:
        pg.screenshot(path=str(OUT / f"{tag}.png"), full_page=True)
    except Exception:
        pass
    return info


def _filter_state(pg, url: str) -> list:
    """What every filter dropdown on CHURN RATES is set to, for one view.

    Eve's screenshot of the Original view (2026-09-03) showed it pinned to
    `B2B Captain's Teams (SFDC) = Cody's Team` AND `Owner & Office = CODY
    LOWERY` — which is the whole reason the BASE download came back with ONE
    owner, and why setting only the team in the URL still returned Cody. Read
    the filter cards so a view's saved scope is a fact instead of a guess:
    what has to be reproduced when Carlos's and Luis's views get re-created is
    exactly this state, and re-creating either one while Owner & Office is
    pinned would bake the single-owner narrowing into the new view.
    """
    try:
        pg.goto(url, wait_until="domcontentloaded")
    except Exception as e:
        return [f"goto failed: {type(e).__name__}: {e}"]
    viz = pg.frame_locator('iframe[title="Data Visualization"]')
    try:
        viz.locator(
            '[data-tb-test-id="viz-viewer-toolbar-button-download"]'
        ).wait_for(state="visible", timeout=90_000)
    except Exception:
        pass
    pg.wait_for_timeout(6_000)
    out = []
    try:
        cards = viz.locator(
            '[data-tb-test-id$="-FilterCard"], .tab-filterContainer, '
            '[class*="FilterCard"]')
        for i in range(min(cards.count(), 20)):
            txt = " ".join((cards.nth(i).inner_text() or "").split())
            if txt:
                out.append(txt[:160])
    except Exception as e:
        out.append(f"scrape failed: {type(e).__name__}: {e}")
    return out or ["(no filter cards matched — see the screenshot)"]


def _try_download(url: str, tag: str, page) -> dict:
    """Download 'ICD Churn' off a URL and summarise who is in it.

    `page` is NOT optional. Called without it the driver launches its OWN
    session, which inside this already-open sync context dies with "It looks
    like you are using Playwright Sync API inside the asyncio loop" — a probe
    failure that reads exactly like Tableau refusing the URL, and which made the
    first two runs report a false 'URL filter works = False'. Every production
    caller passes the shared page (run.py: `fetch_fn(verbose=False, page=page)`);
    so does this.
    """
    out = Path(tempfile.gettempdir()) / f"probe_b2b_{tag}.csv"
    res: dict = {"tag": tag, "url": url, "downloaded": False}
    try:
        download_crosstab_patchright(url, pull.WORKSHEET, out, verbose=False,
                                     page=page)
        res["downloaded"] = True
    except Exception as e:
        res["error"] = " ".join(str(e).split())[:600]
        return res
    try:
        parsed = pull.parse_b2b(out)
        res["owners"] = sorted(parsed.get("reps", {}))
        res["office_total"] = parsed.get("office_total", {})
        (OUT / f"{tag}.csv").write_bytes(out.read_bytes())
    except Exception as e:
        res["parse_error"] = f"{type(e).__name__}: {e}"
    return res


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    report: dict = {"loads": [], "url_filter": [], "custom_views": None}

    with tableau_session(verbose=False) as pg:
        log("=== 1. what each view LOADS ===")
        # The first pass scraped the Crosstab thumbnails by selector and got []
        # for ALL FOUR views — including Eveliz, which production pulls fine. A
        # check that fails on the control proves nothing about the others, so
        # the load test is now the production driver itself: ask each view for
        # 'ICD Churn' exactly as the real pull does. Eveliz is the control — if
        # SHE fails here too, the probe is broken, not the views.
        for tag, url in ([("BASE (no custom view)", BASE_VIEW_URL)]
                         + [(f"{n} ({s})", u) for s, n, u in BROKEN]
                         + [(f"{CONTROL[1]} ({CONTROL[0]}) — control", CONTROL[2])]):
            slug = tag.split()[0].lower().strip("(")
            toast = _thumbs_and_toast(pg, url, slug)
            res = _try_download(url, f"load_{slug}", pg)
            res["tag"] = tag
            res["toast"] = toast.get("toast", "")
            res["toolbar"] = toast.get("ok")
            report["loads"].append(res)
            log(f"  • {tag}: toolbar={res['toolbar']} "
                f"'{pull.WORKSHEET}' downloaded={res['downloaded']} "
                f"owners={len(res.get('owners') or [])}")
            if not res["downloaded"]:
                log(f"      ERROR: {res.get('error', '')}")
            if res["toast"]:
                log(f"      TOAST: {res['toast']}")

        log("\n=== 1b. how each view is SAVED (filter cards) ===")
        for tag, url in [("BASE (Original)", BASE_VIEW_URL),
                         (CONTROL[1] + " (control)", CONTROL[2])]:
            log(f"  -- {tag}")
            for line in _filter_state(pg, url):
                log(f"     {line}")

        log("\n=== 2. custom views still registered on this workbook (as Raf) ===")
        try:
            pg.goto(BASE_VIEW_URL, wait_until="domcontentloaded")
            pg.wait_for_timeout(5_000)
            report["custom_views"] = pg.evaluate(
                r"""async () => {
                  const xsrf = (document.cookie.match(/XSRF-TOKEN=([^;]+)/)||[])[1]||'';
                  const base = location.origin + '/vizportal/api/web/v1/';
                  const call = async (method, params) => {
                    const r = await fetch(base + method, {
                      method: 'POST', credentials: 'include',
                      headers: {'Content-Type': 'application/json;charset=UTF-8',
                                'Accept': 'application/json',
                                'X-XSRF-TOKEN': decodeURIComponent(xsrf)},
                      body: JSON.stringify({method, params})});
                    let b; try { b = JSON.parse(await r.text()); } catch(e) { b = null; }
                    return {status: r.status, body: b};
                  };
                  const out = {};
                  for (const m of ['getCustomViewsForUser', 'getCustomViews']) {
                    try { out[m] = await call(m, {}); } catch (e) { out[m] = String(e); }
                  }
                  return out;
                }""")
            (OUT / "custom_views_raw.json").write_text(
                json.dumps(report["custom_views"], indent=2), encoding="utf-8")
            names = []

            def harvest(o):
                if isinstance(o, dict):
                    if o.get("name") and (o.get("id") or o.get("luid")):
                        names.append((o["name"], o.get("id") or o.get("luid")))
                    for v in o.values():
                        harvest(v)
                elif isinstance(o, list):
                    for v in o:
                        harvest(v)
            harvest(report["custom_views"])
            log(f"  vizportal returned {len(names)} name/id record(s)")
            if not names:
                log("  !! EMPTY — 'still listed? False' below would be a probe "
                    "artifact, not a deleted view. Read custom_views_raw.json.")
            for nm, vid in names:
                log(f"  • {nm!r}  id={vid}")
            # CONTROL first: Eveliz's view demonstrably works, so if HER GUID is
            # not listed either, this whole check is worthless and says nothing
            # about Carlos and Luis.
            for wanted, url in ([(CONTROL[1] + " (CONTROL)", CONTROL[2])]
                                + [(n, u) for _s, n, u in BROKEN]):
                guid = url.split("CHURNRATES/")[1].split("/")[0]
                log(f"  -> {wanted} ({guid}) still listed? "
                    f"{any(guid == v for _n, v in names)}")
        except Exception as e:
            log(f"  (vizportal call failed: {type(e).__name__}: {e})")

        log("\n=== 3. can the captain be filtered from the URL? ===")
        for slug, value in CAPTAIN_VALUES.items():
            for field in CAPTAIN_FIELDS:
                url = _filtered_url(field, value)
                res = _try_download(url, f"{slug}_{abs(hash(field)) % 9999}", pg)
                res.update(slug=slug, field=field, value=value)
                report["url_filter"].append(res)
                owners = res.get("owners")
                log(f"  • {slug} via {field!r}: downloaded={res['downloaded']} "
                    f"owners={len(owners) if owners else 0}"
                    f"{'' if res['downloaded'] else ' — ' + res.get('error', '')}")
                if owners:
                    log(f"      {owners}")
                    break   # this field works; no need to try the others

    (OUT / "report.json").write_text(json.dumps(report, indent=2, default=str),
                                     encoding="utf-8")
    log("\n=== VERDICT ===")
    for l in report["loads"]:
        log(f"  {l['tag']}: '{pull.WORKSHEET}' downloaded={l.get('downloaded')}"
            f" owners={len(l.get('owners') or [])}")
    for slug in CAPTAIN_VALUES:
        hit = next((r for r in report["url_filter"]
                    if r["slug"] == slug and r.get("owners")), None)
        log(f"  {slug}: URL filter works = {bool(hit)}"
            + (f" (field {hit['field']!r}, {len(hit['owners'])} owners)" if hit else ""))
    log(f"  artifacts: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
