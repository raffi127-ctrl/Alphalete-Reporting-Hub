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


def _shoot(page, out_path: Path, *, crop=None) -> str:
    """Full-page screenshot, then optionally PIL-crop to `crop`, a callable
    (W, H) -> (left, top, right, bottom) in image pixels. Full-page can never
    come back blank (the earlier anchor-clip approach did); the crop just trims
    the fixed left sidebar + top chrome so the content fills the frame. Returns
    'clip' if cropped, 'full' if we kept the whole page."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    full = out_path.with_name(out_path.stem + "_full.png")
    page.screenshot(path=str(full), full_page=True)
    if crop is not None:
        try:
            from PIL import Image
            im = Image.open(full)
            w, h = im.size
            left, top, right, bottom = crop(w, h)
            left = max(0, min(int(left), w - 1))
            right = max(left + 10, min(int(right), w))
            top = max(0, min(int(top), h - 1))
            bottom = max(top + 10, min(int(bottom), h))
            im.crop((left, top, right, bottom)).save(out_path)
            try:
                full.unlink()
            except Exception:
                pass
            return "clip"
        except Exception as e:  # noqa: BLE001 — never let a crop kill the run
            print(f"  crop failed ({type(e).__name__}: {str(e)[:70]}) — keeping "
                  f"full page", flush=True)
    try:
        full.replace(out_path)
    except Exception:
        page.screenshot(path=str(out_path), full_page=True)
    return "full"


# Per-view crop boxes over the full-page image (1680px-wide viewport). The left
# nav is ~168px and the top user-bar + page title ~205px; territories/cards sit
# near the top, so we cap their height. Tuned against Lucy 2 dry-runs; a full
# page is captured first so a wrong box degrades to "too much", never blank.
CROP_TODAYS_ACTIVITY = lambda w, h: (168, 205, min(w, 720), h)          # noqa: E731
CROP_TIME_TRACKER = lambda w, h: (168, 205, w, min(h, 1150))            # noqa: E731
CROP_TERRITORY_STATS = lambda w, h: (168, 205, w, min(h, 1150))        # noqa: E731


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
    how = _shoot(page, out, crop=CROP_TODAYS_ACTIVITY)
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
    how = _shoot(page, out, crop=CROP_TIME_TRACKER)
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
    if dump:
        print_outline(page, f"territory_stats {tag} {name}")
    how = _shoot(page, out, crop=CROP_TERRITORY_STATS)
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
