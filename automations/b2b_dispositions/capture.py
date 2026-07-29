"""Capture OwnerVille dispositions views as cropped PNGs.

Three views, each per campaign (AT&T SBS, BOX-Energy):
  * Today's Activity   (p=88)  — the rep list + knock counts
  * Time Tracker       (p=510) — the two gap-summary cards
  * Territory Stats    (p=89 + pane=territoryStats&teritoryId=<id>) — 3 stat
    cards, one screenshot PER territory (territories enumerated live).

We SCREENSHOT (not scrape) because Carlos wants the OwnerVille visuals verbatim.
Crops are computed from on-screen TEXT ANCHORS (the view title, the card
headers) rather than fixed pixels, so a template nudge doesn't silently shift
the crop. If an anchor can't be found we fall back to a full-page shot and, on
--dry-run, drop a `<view>.domdump.txt` so the exact container can be pinned on
the first real Lucy-2 run.

Runs inside `ownerville_session()`, i.e. as whoever is logged in on this machine
— on Lucy 2 that's Carlos / office 11580, which is where the B2B campaigns live.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from automations.b2b_dispositions import config as cfg

VIEWPORT = {"width": 1680, "height": 1200}
# How long to let a ColdFusion/DataTables view settle after networkidle. These
# panels paint their rows a beat after the XHR resolves.
SETTLE_MS = 2500


# --- rqst token ---------------------------------------------------------------
def capture_rqst(page) -> str:
    """The session's master rqst token. A bare p=<id> bounces to Welcome, so
    every page URL needs it. Same trick total_knocks/car_rides use: read it off
    the current URL, else hit the v2 root which mints a fresh one."""
    m = re.search(r"rqst=([A-Za-z0-9_\-]+)", page.url or "")
    if m:
        return m.group(1)
    page.goto("https://v2.ownerville.com/", wait_until="networkidle", timeout=25000)
    m = re.search(r"rqst=([A-Za-z0-9_\-]+)", page.url or "")
    if not m:
        raise RuntimeError(
            "No rqst token on v2.ownerville.com — the OwnerVille session isn't "
            "live. Re-export .ownerville_storage_state.json on this machine.")
    return m.group(1)


# --- campaign-aware URL building + verification -------------------------------
def _page_url(page_id: int, rqst: str, campaign: str, extra: str = "") -> str:
    url = f"https://v2.ownerville.com/index.cfm?p={page_id}&rqst={rqst}"
    cid = cfg.CAMPAIGN_URL_IDS.get(campaign)
    if cid is not None:
        url += f"&invD2DClientId={cid}"
    if extra:
        url += extra
    return url


_CAMPAIGN_LABEL_JS = (
    "() => { const rx=/^(B2B AT&T SBS|B2B-BOX-Energy|BASE Energy)$/;"
    " const e=[...document.querySelectorAll('span,a,button')]"
    ".find(x=>rx.test((x.innerText||'').trim()) && x.offsetParent!==null);"
    " return e ? e.innerText.trim() : ''; }")


def _goto(page, url: str) -> None:
    page.goto(url, wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(SETTLE_MS)


def verify_campaign(page, want: str) -> Tuple[bool, str]:
    """(ok, on_screen_label). The top-right toolbar shows the active campaign;
    we read it before every capture so a shot is never mislabeled. Empty label
    (headless can hide the toolbar text) is treated as 'trust the URL param'."""
    got = ""
    try:
        got = page.evaluate(_CAMPAIGN_LABEL_JS) or ""
    except Exception:
        pass
    return (got == want or got == ""), got


# --- generic anchor-based crop ------------------------------------------------
_RECT_JS = """
(args) => {
  const { titleText, bottomText, maxWidth, extraBottom } = args;
  const norm = s => (s||'').replace(/\\s+/g,' ').trim().toLowerCase();
  const all = [...document.querySelectorAll('body *')];
  const byText = t => all.find(e => e.offsetParent !== null &&
      norm(e.innerText) === norm(t));
  // Prefer an exact title match; then "starts with" (dates get appended to some
  // headers, e.g. "Disposition by Rep - 07/29/2026 - ..."); then a SMALL element
  // that merely contains it (avoid a giant wrapper whose innerText is the whole
  // page). This is the top anchor, so pick the tightest match.
  let title = byText(titleText);
  if (!title) title = all.find(e => e.offsetParent !== null &&
      norm(e.innerText).startsWith(norm(titleText)));
  if (!title) {
    const hits = all.filter(e => e.offsetParent !== null &&
        norm(e.innerText).includes(norm(titleText)) &&
        (e.innerText || '').length < norm(titleText).length + 60);
    title = hits.length ? hits[0] : null;
  }
  if (!title) return null;
  const t = title.getBoundingClientRect();
  const contentLeft = t.left;
  let top = t.bottom + 6;
  let bottom;
  if (bottomText) {
    const b = all.find(e => e.offsetParent !== null &&
        norm(e.innerText).includes(norm(bottomText)));
    bottom = b ? b.getBoundingClientRect().bottom : (top + 600);
  } else {
    bottom = document.documentElement.scrollHeight;
  }
  bottom = Math.min(bottom + (extraBottom||0),
                    document.documentElement.scrollHeight);
  const vw = window.innerWidth;
  let width = vw - contentLeft - 24;
  if (maxWidth) width = Math.min(width, maxWidth);
  return { x: Math.max(0, contentLeft - 4), y: Math.max(0, top - 4),
           width: Math.max(50, width + 8),
           height: Math.max(50, bottom - top + 8) };
}
"""


_OUTLINE_JS = """
() => [...document.querySelectorAll('body *')]
  .filter(e => e.offsetParent !== null)
  .map(e => { const r = e.getBoundingClientRect(); return {e, r}; })
  .filter(x => x.r.width > 120 && x.r.height > 40 && x.r.top < 1400)
  .sort((a,b) => (b.r.width*b.r.height) - (a.r.width*a.r.height))
  .slice(0, 22)
  .map(({e,r}) => `${e.tagName} #${e.id||''} .${String(e.className||'').trim().slice(0,40)} `
     + `[${Math.round(r.left)},${Math.round(r.top)} ${Math.round(r.width)}x${Math.round(r.height)}] `
     + `"${(e.innerText||'').replace(/\\s+/g,' ').slice(0,50)}"`)
  .join('\\n')
"""


def print_outline(page, label: str) -> None:
    """Print a compact outline of the biggest on-screen containers to stdout.
    In --dry-run this lands in the run log, so `logtail` can fetch the real DOM
    structure from the laptop and crop anchors can be pinned exactly."""
    try:
        txt = page.evaluate(_OUTLINE_JS)
    except Exception:
        txt = "(outline unavailable)"
    print(f"--- DOM outline [{label}] ---\n{txt}\n--- end [{label}] ---",
          flush=True)


def _shoot(page, out_path: Path, *, title_text: str,
           bottom_text: Optional[str] = None, max_width: Optional[int] = None,
           extra_bottom: int = 20, dump: bool = False) -> str:
    """Screenshot the region between the view title and a bottom anchor. Returns
    'clip' | 'full' describing which path was taken. On dump=True (dry-run),
    also writes a DOM outline next to the PNG when we had to fall back."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rect = None
    try:
        rect = page.evaluate(_RECT_JS, {
            "titleText": title_text, "bottomText": bottom_text,
            "maxWidth": max_width, "extraBottom": extra_bottom})
    except Exception:
        rect = None
    if rect and rect.get("width", 0) > 40 and rect.get("height", 0) > 40:
        # Clamp to the rendered page so Playwright doesn't reject the clip.
        page.screenshot(path=str(out_path), clip={
            "x": float(rect["x"]), "y": float(rect["y"]),
            "width": float(rect["width"]), "height": float(rect["height"])})
        return "clip"
    # Fallback: whole page, and leave breadcrumbs to pin the anchor next time.
    page.screenshot(path=str(out_path), full_page=True)
    if dump:
        try:
            outline = page.evaluate(
                """() => [...document.querySelectorAll('body *')]
                    .filter(e => e.offsetParent !== null &&
                        (e.id || (e.className && String(e.className).length)))
                    .slice(0, 400)
                    .map(e => { const r = e.getBoundingClientRect();
                        return `${e.tagName} #${e.id||''} .${String(e.className||'').slice(0,60)} `
                          + `[${Math.round(r.left)},${Math.round(r.top)} `
                          + `${Math.round(r.width)}x${Math.round(r.height)}] `
                          + `"${(e.innerText||'').replace(/\\s+/g,' ').slice(0,40)}"`; })
                    .join('\\n')""")
            out_path.with_suffix(".domdump.txt").write_text(outline)
        except Exception:
            pass
    return "full"


# --- the three views ----------------------------------------------------------
def capture_todays_activity(page, rqst: str, campaign: str,
                            out_dir: Path, dump: bool = False) -> Dict:
    """Today's Activity (p=88): the rep list + knock-count badges. Narrow crop —
    the meaningful content is the left panel; the right pane is empty until a rep
    is picked."""
    _goto(page, _page_url(cfg.PAGE_TODAYS_ACTIVITY, rqst, campaign))
    ok, label = verify_campaign(page, campaign)
    tag = cfg.CAMPAIGN_TAG[campaign]
    if dump:
        print_outline(page, f"todays_activity {tag}")
    out = out_dir / f"todays_activity_{_slug(tag)}.png"
    how = _shoot(page, out, title_text="Today's Activity",
                 max_width=430, extra_bottom=40, dump=dump)
    return {"view": "todays_activity", "campaign": campaign, "tag": tag,
            "path": out, "how": how, "campaign_ok": ok, "on_screen": label}


def capture_time_tracker(page, rqst: str, campaign: str,
                         out_dir: Path, dump: bool = False) -> Dict:
    """Time Tracker (p=510): the two gap-summary cards. Carlos pointed at 'Reps
    Over 15 Minute Gap'; we capture from the 'Reps Under 15 Minute Gap' card
    header (top of the section) through the Over card, i.e. both cards."""
    _goto(page, _page_url(cfg.PAGE_TIME_TRACKER, rqst, campaign))
    ok, label = verify_campaign(page, campaign)
    tag = cfg.CAMPAIGN_TAG[campaign]
    if dump:
        print_outline(page, f"time_tracker {tag}")
    out = out_dir / f"time_tracker_{_slug(tag)}.png"
    # Anchor top on the stable page title "Time Tracker", bottom on the "Reps
    # Over 15 Minute Gap" card, so both gap-summary cards are in frame. (The card
    # headers themselves carry a count badge, so they're not reliable anchors.)
    how = _shoot(page, out, title_text="Time Tracker",
                 bottom_text="Reps Over 15 Minute Gap", extra_bottom=160,
                 dump=dump)
    return {"view": "time_tracker", "campaign": campaign, "tag": tag,
            "path": out, "how": how, "campaign_ok": ok, "on_screen": label}


_TERRITORY_OPTIONS_JS = """
() => {
  // The Territory <select> on Disposition-by-Rep. Options carry the teritoryId
  // as value and "name (date range)" as text. Read whatever select actually
  // holds territory-shaped options — never a fixed list.
  const sels = [...document.querySelectorAll('select')];
  let best = null, bestN = 0;
  for (const s of sels) {
    const opts = [...s.options].filter(o => o.value && /\\d/.test(o.value));
    if (opts.length > bestN) { best = opts; bestN = opts.length; }
  }
  if (!best) return [];
  return best.map(o => ({ id: String(o.value).trim(),
                          name: (o.textContent||'').replace(/\\s+/g,' ').trim() }));
}
"""


def list_territories(page, rqst: str, campaign: str) -> List[Dict]:
    """Enumerate territories for `campaign` from the page's own dropdown (values
    = teritoryId). Territories are campaign-scoped, so this is called once per
    campaign."""
    extra = f"&pane={cfg.DISPOSITION_PANE}"
    _goto(page, _page_url(cfg.PAGE_DISPOSITION, rqst, campaign, extra))
    try:
        opts = page.evaluate(_TERRITORY_OPTIONS_JS) or []
    except Exception:
        opts = []
    # Drop a leading placeholder ("select a territory") if present.
    return [o for o in opts if o.get("id") and o["id"] not in ("0", "")]


def capture_territory_stats(page, rqst: str, campaign: str, terr: Dict,
                            out_dir: Path, dump: bool = False) -> Dict:
    """Territory Stats for one territory: the 3 stat cards. Crop starts at the
    'Report By' filter row (which shows the territory name Carlos wants visible)
    and runs to the bottom of the cards."""
    extra = (f"&pane={cfg.DISPOSITION_PANE}"
             f"&{cfg.TERRITORY_ID_PARAM}={terr['id']}")
    _goto(page, _page_url(cfg.PAGE_DISPOSITION, rqst, campaign, extra))
    ok, label = verify_campaign(page, campaign)
    tag = cfg.CAMPAIGN_TAG[campaign]
    name = _clean_territory_name(terr.get("name", terr["id"]))
    out = out_dir / f"territory_{_slug(tag)}_{_slug(name)}.png"
    # "Report By" is the filter-row label; the three cards end with "CURRENT
    # PERIOD". Anchor top on Report By so the selected territory name is in frame.
    how = _shoot(page, out, title_text="Report By",
                 bottom_text="Current Period", extra_bottom=380, dump=dump)
    return {"view": "territory_stats", "campaign": campaign, "tag": tag,
            "territory_id": terr["id"], "territory": name,
            "path": out, "how": how, "campaign_ok": ok, "on_screen": label}


# --- small helpers ------------------------------------------------------------
def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", (s or "").strip()).strip("-").lower() or "x"


def _clean_territory_name(raw: str) -> str:
    """'luis (07/29/2026 - 08/02/2026)' -> 'luis'. Keep just the name for the
    caption; the date range is noise for a daily post."""
    return re.sub(r"\s*\(.*\)\s*$", "", raw or "").strip() or raw
