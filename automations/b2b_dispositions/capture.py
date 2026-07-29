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


_CAMPAIGN_SWITCH_RX = r"^(B2B AT&T SBS|B2B-BOX-Energy|BASE Energy)$"


# Reads every campaign option OwnerVille knows about, with the invD2DClientId
# each one carries (in href / onclick / data-*). The dropdown is collapsed, so
# we click it open first; then the options are in the DOM.
_CAMPAIGN_OPTIONS_JS = r"""
(rx) => {
  const re = new RegExp(rx);
  const out = [];
  [...document.querySelectorAll('a,li,span,button,option')].forEach(x => {
    const t = (x.innerText || x.textContent || '').trim();
    if (!re.test(t)) return;
    const blob = [x.getAttribute('href'), x.getAttribute('onclick'),
                  x.getAttribute('data-id'), x.getAttribute('data-invd2dclientid'),
                  x.value].filter(Boolean).join(' ');
    const m = blob.match(/(?:invD2DClientId|clientId|id)\D{0,3}(\d{1,6})/i);
    out.push({ name: t, id: m ? m[1] : null,
               html: (x.outerHTML || '').replace(/\s+/g,' ').slice(0, 140) });
  });
  return out;
}
"""


def _open_campaign_dropdown(page) -> None:
    """Open the Bootstrap campaign dropdown so its options are VISIBLE (collapsed,
    the option <a>s have offsetParent===null and can't be clicked). Click the
    toggle AND force the open/show classes + menu display, so it opens whether or
    not the site's jQuery handler fires under patchright's isolated world."""
    try:
        page.evaluate(
            "()=>{const tg=document.querySelector('.D2DClientDropdown,"
            "[data-toggle=\"dropdown\"]'); if(!tg) return; tg.click();"
            " const dd=tg.closest('.dropdown,.btn-group,li'); "
            " if(dd){dd.classList.add('open','show');"
            " const m=dd.querySelector('.dropdown-menu'); "
            " if(m){m.classList.add('show'); m.style.display='block';}}}")
        page.wait_for_timeout(900)
    except Exception:
        pass


def campaign_options(page) -> List[Dict]:
    """Every campaign option + its invD2DClientId, read after opening the
    dropdown. Lets us switch by the id OwnerVille itself uses (incl. AT&T's,
    which isn't in the code) instead of guessing."""
    _open_campaign_dropdown(page)
    try:
        return page.evaluate(_CAMPAIGN_OPTIONS_JS, _CAMPAIGN_SWITCH_RX) or []
    except Exception:
        return []


def ensure_campaign(page, rqst: str, campaign: str) -> bool:
    """Make the session's ACTIVE campaign = `campaign`, returning True on success.

    The campaign is a STICKY session-global: invD2DClientId=16 switches to Box,
    but a no-param nav does NOT switch back to AT&T — so both campaigns end up
    capturing Box (the 'same people' bug). We read the real invD2DClientId of
    each option from the dropdown and set the global by navigating Time Tracker
    (which honors the param) with that id; fall back to clicking the option."""
    # Load a page that carries the toolbar, then learn each option's real id.
    _goto(page, _page_url(cfg.PAGE_TIME_TRACKER, rqst, campaign))
    opts = campaign_options(page)
    print(f"  campaign options: {opts}", flush=True)
    want = next((o for o in opts if o.get("name") == campaign), None)
    cid = (want or {}).get("id") or (
        str(cfg.CAMPAIGN_URL_IDS[campaign])
        if cfg.CAMPAIGN_URL_IDS.get(campaign) is not None else None)

    if cid:
        url = (f"https://v2.ownerville.com/index.cfm?p={cfg.PAGE_TIME_TRACKER}"
               f"&rqst={rqst}&invD2DClientId={cid}")
        _goto(page, url)
        _, got = verify_campaign(page, campaign)
        if got == campaign:
            return True

    # Fallback: click the option in the open dropdown.
    try:
        _open_campaign_dropdown(page)
        page.evaluate(
            "(c)=>{const a=[...document.querySelectorAll('a,li,span,button,option')]"
            ".find(x=>((x.innerText||x.textContent||'').trim())===c "
            "&& x.offsetParent!==null); if(a){a.click(); return true;} return false;}",
            campaign)
        page.wait_for_timeout(8000)
    except Exception as e:  # noqa: BLE001
        print(f"  campaign click to {campaign!r} errored: {type(e).__name__}",
              flush=True)
    _, got = verify_campaign(page, campaign)
    if got != campaign:
        print(f"  ⚠ campaign still {got!r} after switching to {campaign!r}",
              flush=True)
    return got == campaign


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


_CONTENT_BOX_JS = r"""
(kind) => {
  window.scrollTo(0, 0);
  const vis = e => e && e.offsetParent !== null;
  const norm = s => (s||'').replace(/\s+/g,' ').trim().toLowerCase();
  const all = [...document.querySelectorAll('body *')].filter(vis);
  const containing = t => all.filter(e => norm(e.innerText).includes(norm(t)));
  // The tightest element whose text contains `t` (leaf-most, smallest area).
  const tight = t => { const c = containing(t);
    return c.length ? c.sort((a,b)=>{const ra=a.getBoundingClientRect(),rb=b.getBoundingClientRect();
      return (ra.width*ra.height)-(rb.width*rb.height);})[0] : null; };
  const union = els => { const rs = els.filter(Boolean).map(e=>e.getBoundingClientRect());
    if (!rs.length) return null;
    return { left: Math.min(...rs.map(r=>r.left)), top: Math.min(...rs.map(r=>r.top)),
             right: Math.max(...rs.map(r=>r.right)), bottom: Math.max(...rs.map(r=>r.bottom)) }; };
  const box = e => { const r=e.getBoundingClientRect();
    return {left:r.left, top:r.top, right:r.right, bottom:r.bottom}; };
  let b = null;
  if (kind === 'todays_activity') {
    // The rep-list panel: from the search box, climb to the tall/narrow panel
    // that holds the rows (adapts to the collapsed sidebar).
    let inp = document.querySelector(
      'input[placeholder*="owner" i], input[placeholder*="rep" i], input[type="search"]');
    if (inp) { let el = inp;
      for (let i=0;i<7 && el.parentElement;i++){ el = el.parentElement;
        const r = el.getBoundingClientRect();
        if (r.height > 350 && r.width > 180 && r.width < 760) { b = box(el); break; } }
      if (!b) b = box(inp.parentElement || inp); }
  } else if (kind === 'time_tracker') {
    // The two gap cards sit ABOVE the "Time Tracking Data" table. Bound the crop
    // by that heading so the table is never included (it kept swallowing the
    // shot). Left/right from the gap-card blocks; top from their top; bottom at
    // the data-table heading.
    const under = tight('Reps Under 15 Minute Gap');
    const over = tight('Reps Over 15 Minute Gap');
    const card = e => { let el=e; for (let i=0;i<4 && el.parentElement;i++){ el=el.parentElement;
      const r=el.getBoundingClientRect(); if (r.height > 80 && r.width > 200) return el; } return e; };
    const cu = union([under && card(under), over && card(over)]);
    const dataHdr = tight('Time Tracking Data');
    if (cu) {
      const bottom = dataHdr ? Math.min(cu.bottom, dataHdr.getBoundingClientRect().top - 8) : cu.bottom;
      b = { left: cu.left, top: cu.top, right: cu.right,
            bottom: Math.max(cu.top + 60, bottom) };
    }
  } else if (kind === 'territory_stats') {
    // The 3 stat cards, from the "Report By" filter row to the CURRENT PERIOD
    // card. Climb from each card's header to the card block, then union with the
    // filter row (which carries the territory name Carlos wants visible).
    const rb = tight('Report By');
    const cardEls = ['TODAY', 'SINCE TERRITORY', 'CURRENT PERIOD']
      .map(t => tight(t))
      .map(e => { if (!e) return null; let el = e;
        for (let i=0;i<5 && el.parentElement;i++){ el = el.parentElement;
          if (el.getBoundingClientRect().height > 200) return el; } return e; });
    b = union([rb, ...cardEls]);
  }
  if (!b) return null;
  return { left:b.left, top:b.top, right:b.right, bottom:b.bottom,
           innerWidth: window.innerWidth };
}
"""


def content_box(page, kind: str):
    """The live bounding box (CSS px) of a view's real content, so the crop
    adapts to the collapsed sidebar / actual layout instead of fixed pixels.
    Returns a dict with left/top/right/bottom/innerWidth, or None."""
    try:
        return page.evaluate(_CONTENT_BOX_JS, kind)
    except Exception:
        return None


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


def _shoot(page, out_path: Path, *, kind: str, fixed=None, pad: int = 14,
           pad_bottom: int = 0) -> str:
    """Full-page screenshot, then PIL-crop to the view's real content. Two crop
    sources, in order: (1) the LIVE element bounding box from content_box(kind)
    — adapts to the collapsed sidebar / actual layout, the tight crop Megan
    asked for; (2) a fixed fallback box `fixed(W,H)` if the element can't be
    located. Full-page can never come back blank, so a miss degrades to "too
    much", never empty. Returns 'box' | 'fixed' | 'full'."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    box = content_box(page, kind)      # measured BEFORE the shot (scrolls to top)
    full = out_path.with_name(out_path.stem + "_full.png")
    page.screenshot(path=str(full), full_page=True)
    how = "full"
    try:
        from PIL import Image
        im = Image.open(full)
        w, h = im.size
        rect = None
        if box and box.get("innerWidth"):
            # getBoundingClientRect is CSS px; the full-page PNG is scaled by the
            # device pixel ratio, so map CSS px -> image px via W / innerWidth.
            s = w / float(box["innerWidth"]) or 1.0
            rect = (box["left"] * s - pad, box["top"] * s - pad,
                    box["right"] * s + pad, box["bottom"] * s + pad + pad_bottom)
            how = "box"
        elif fixed is not None:
            rect = fixed(w, h)
            how = "fixed"
        if rect is not None:
            left = max(0, min(int(rect[0]), w - 1))
            top = max(0, min(int(rect[1]), h - 1))
            right = max(left + 10, min(int(rect[2]), w))
            bottom = max(top + 10, min(int(rect[3]), h))
            im.crop((left, top, right, bottom)).save(out_path)
            try:
                full.unlink()
            except Exception:
                pass
            return how
    except Exception as e:  # noqa: BLE001 — never let a crop kill the run
        print(f"  crop failed ({type(e).__name__}: {str(e)[:70]}) — keeping "
              f"full page", flush=True)
    try:
        full.replace(out_path)
    except Exception:
        page.screenshot(path=str(out_path), full_page=True)
    return "full"


# Fixed fallback boxes over the full-page image, used only when the live element
# box can't be found (1680px-wide viewport; left nav ~168px, top chrome ~205px).
CROP_TODAYS_ACTIVITY = lambda w, h: (168, 205, min(w, 720), h)          # noqa: E731
CROP_TIME_TRACKER = lambda w, h: (168, 300, w, min(h, 620))            # noqa: E731
CROP_TERRITORY_STATS = lambda w, h: (168, 250, w, min(h, 1000))        # noqa: E731


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
    how = _shoot(page, out, kind="todays_activity", fixed=CROP_TODAYS_ACTIVITY,
                 pad_bottom=36)
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
    how = _shoot(page, out, kind="time_tracker", fixed=CROP_TIME_TRACKER)
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
    how = _shoot(page, out, kind="territory_stats", fixed=CROP_TERRITORY_STATS)
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
