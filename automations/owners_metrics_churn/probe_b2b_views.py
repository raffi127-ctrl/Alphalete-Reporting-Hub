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
    ("carlos", "CarlosCaptainship", pull.B2B_CARLOS_URL),
    ("luis", "LuissCaptainship", pull.B2B_LUIS_URL),
]
# The sibling that still works — the control. If this one ALSO looks wrong here,
# the problem is the probe, not the views.
CONTROL = ("eveliz", "EvelizWOVan", pull.B2B_EVELIZ_URL)

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
                (toast.nth(i).inner_text() or "").strip()
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


def _try_download(url: str, tag: str) -> dict:
    """Download 'ICD Churn' off a URL and summarise who is in it."""
    out = Path(tempfile.gettempdir()) / f"probe_b2b_{tag}.csv"
    res: dict = {"tag": tag, "url": url, "downloaded": False}
    try:
        download_crosstab_patchright(url, pull.WORKSHEET, out, verbose=False)
        res["downloaded"] = True
    except Exception as e:
        res["error"] = str(e).splitlines()[0][:200]
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
        for tag, url in ([("BASE (no custom view)", BASE_VIEW_URL)]
                         + [(f"{n} ({s})", u) for s, n, u in BROKEN]
                         + [(f"{CONTROL[1]} ({CONTROL[0]}) — control", CONTROL[2])]):
            info = _thumbs_and_toast(pg, url, tag.split()[0].lower())
            info["tag"] = tag
            report["loads"].append(info)
            has = pull.WORKSHEET in info["thumbs"]
            log(f"  • {tag}: toolbar={info['ok']} "
                f"'{pull.WORKSHEET}' present={has} thumbs={info['thumbs']}")
            if info["toast"]:
                log(f"      TOAST: {info['toast']}")

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
            for nm, vid in names:
                log(f"  • {nm!r}  id={vid}")
            for _s, wanted, url in BROKEN:
                guid = url.split("CHURNRATES/")[1].split("/")[0]
                log(f"  -> {wanted} ({guid}) still listed? "
                    f"{any(guid == v for _n, v in names)}")
        except Exception as e:
            log(f"  (vizportal call failed: {type(e).__name__}: {e})")

        log("\n=== 3. can the captain be filtered from the URL? ===")
        for slug, value in CAPTAIN_VALUES.items():
            for field in CAPTAIN_FIELDS:
                url = _filtered_url(field, value)
                res = _try_download(url, f"{slug}_{abs(hash(field)) % 9999}")
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
    base = next((l for l in report["loads"] if l["tag"].startswith("BASE")), {})
    log(f"  BASE view carries '{pull.WORKSHEET}': "
        f"{pull.WORKSHEET in base.get('thumbs', [])}")
    for slug in CAPTAIN_VALUES:
        hit = next((r for r in report["url_filter"]
                    if r["slug"] == slug and r.get("owners")), None)
        log(f"  {slug}: URL filter works = {bool(hit)}"
            + (f" (field {hit['field']!r}, {len(hit['owners'])} owners)" if hit else ""))
    log(f"  artifacts: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
