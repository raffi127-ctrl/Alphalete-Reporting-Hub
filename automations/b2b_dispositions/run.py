"""B2B Dispositions — capture OwnerVille views and post them to Slack.

Cadence (scheduled on Lucy 2, mini-local/Central):
  * 12,1,2,3,4,5,6pm + 6:30pm  ->  Today's Activity + Time Tracker  (both campaigns)
  * 6:30pm only                ->  Territory Stats, one shot per territory

Usage:
  # capture only, save PNGs to output/, post NOTHING (default — the review loop)
  python -m automations.b2b_dispositions.run --which all --dry-run

  # the hourly job (Today's Activity + Time Tracker into their 2 threads)
  python -m automations.b2b_dispositions.run --which hourly --send

  # the 6:30 final: hourly views (tagged Final) + every-territory dispositions
  python -m automations.b2b_dispositions.run --which all --final --send

--dry-run is the DEFAULT. --send is the only thing that touches Slack.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import Dict, List, Optional

from automations.b2b_dispositions import capture as cap
from automations.b2b_dispositions import config as cfg
from automations.b2b_dispositions import slack_post as sp

try:
    from zoneinfo import ZoneInfo
    _CENTRAL = ZoneInfo("America/Chicago")
except Exception:  # pragma: no cover — zoneinfo is stdlib on 3.9+
    _CENTRAL = None

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output" / "b2b_dispositions"


def _central_now() -> dt.datetime:
    now = dt.datetime.now(_CENTRAL) if _CENTRAL else dt.datetime.now()
    return now


def slot_label(final: bool, now: Optional[dt.datetime] = None) -> str:
    """The caption's time tag, snapped to the nearest scheduled slot so a job
    that fires a few minutes late still reads '1:00 PM', not '1:03 PM'. The
    6:30 final is tagged so the last shot of the day is obvious."""
    now = now or _central_now()
    if final:
        return f"{_fmt12(cfg.FINAL_SLOT)} (Final)"
    # snap to the closest hourly slot
    best = min(cfg.HOURLY_SLOTS,
               key=lambda hm: abs((now.hour * 60 + now.minute)
                                  - (hm[0] * 60 + hm[1])))
    return _fmt12(best)


def _fmt12(hm) -> str:
    h, m = hm
    ampm = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {ampm}"


def _capture_hourly(page, rqst: str, out_dir: Path, slot: str,
                    dry_run: bool, today: dt.date) -> List[Dict]:
    """Today's Activity + Time Tracker for both campaigns -> ONE thread spec.
    Each hour is its own thread ("Hourly Activity 7/30/26 - 4 PM") with a single
    reply carrying both campaign images (Megan 7/30)."""
    paths, notes = [], []
    for campaign in cfg.CAMPAIGNS:
        cap.ensure_campaign(page, rqst, campaign)  # sticky global — flip it first
        ta = cap.capture_todays_activity(page, rqst, campaign, out_dir, dump=dry_run)
        tt = cap.capture_time_tracker(page, rqst, campaign, out_dir, dump=dry_run)
        tag = cfg.CAMPAIGN_TAG[campaign]
        combined = out_dir / f"hourly_{cap._slug(tag)}.png"
        try:
            cap.stitch_vertical(
                [(cfg.PANEL_TODAYS_ACTIVITY, ta["path"]),
                 (cfg.PANEL_TIME_TRACKER, tt["path"])],
                title=f"{tag} — {slot}", out_path=combined)
            paths.append(combined)
        except Exception as e:  # noqa: BLE001
            print(f"  {tag} stitch failed ({type(e).__name__}) — Today's Activity "
                  f"only", flush=True)
            paths.append(ta["path"])
        notes.append(f"{tag}[TA:{ta.get('how')} TT:{tt.get('how')} "
                     f"camp_ok={ta.get('campaign_ok') and tt.get('campaign_ok')}]")
    title = sp.thread_title(cfg.THREAD_HOURLY, slot, today)
    return [{"title": title, "paths": paths, "meta": {"note": " ".join(notes)}}]


def _capture_dispositions(page, rqst: str, out_dir: Path,
                          dry_run: bool, limit: int = 0,
                          slot: str = "", today: Optional[dt.date] = None) -> List[Dict]:
    today = today or _central_now().date()
    """Territory Stats: capture every territory per campaign, then STACK a
    campaign's territories into ONE tall image (each keeps its name header). One
    reply carries both campaign stacks (Megan 7/30 — 2 images at 6:30, not 18
    posts). `limit` > 0 caps territories per campaign for a quick preview."""
    stacks, notes = [], []
    for campaign in cfg.CAMPAIGNS:
        cap.ensure_campaign(page, rqst, campaign)  # sticky global — flip it first
        terrs = cap.list_territories(page, rqst, campaign)
        tag = cfg.CAMPAIGN_TAG[campaign]
        print(f"  {tag}: {len(terrs)} territories"
              + (f" (limited to {limit})" if limit else ""), flush=True)
        if limit:
            terrs = terrs[:limit]
        terr_paths = []
        for terr in terrs:
            res = cap.capture_territory_stats(page, rqst, campaign, terr,
                                              out_dir, dump=dry_run)
            terr_paths.append(res["path"])
        if not terr_paths:
            continue
        stack = out_dir / f"dispositions_{cap._slug(tag)}.png"
        try:
            cap.stack_images(terr_paths, stack)
            stacks.append(stack)
        except Exception as e:  # noqa: BLE001
            print(f"  {tag} stack failed ({type(e).__name__})", flush=True)
            stacks.extend(terr_paths)  # fall back to individual images
        notes.append(f"{tag}={len(terr_paths)}")
    if not stacks:
        return []
    # Dispositions posts once a day, so "(Final)" is meaningless here (Megan
    # 7/30) — that tag only belongs on the hourly. Strip it.
    clean_slot = (slot or "6:30 PM").replace(" (Final)", "")
    title = sp.thread_title(cfg.THREAD_DISPOSITIONS, clean_slot, today)
    return [{"title": title, "paths": stacks, "meta": {"note": " ".join(notes)}}]


def _post_specs(specs: List[Dict], today: dt.date, dry_run: bool) -> List[Dict]:
    """Each spec is its own thread: a titled parent + one image reply, in both
    channels (Megan 7/30)."""
    return [sp.post_thread(s["title"], s["paths"], today, dry_run=dry_run)
            for s in specs]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="B2B Dispositions -> Slack")
    ap.add_argument("--which", choices=["hourly", "dispositions", "all"],
                    default="all", help="hourly = Today's Activity + Time "
                    "Tracker; dispositions = per-territory; all = both")
    ap.add_argument("--final", action="store_true",
                    help="tag the hourly shots as the 6:30 Final")
    ap.add_argument("--send", action="store_true",
                    help="post to the live Slack channels")
    ap.add_argument("--preview", action="store_true",
                    help="DM the captured shots to Megan for review (no channel post)")
    ap.add_argument("--dry-run", action="store_true",
                    help="capture + report only, post nothing (default)")
    ap.add_argument("--headless", action="store_true",
                    help="run the browser headless")
    ap.add_argument("--probe-campaigns", action="store_true",
                    help="scan invD2DClientId ids and log which campaign each maps to")
    ap.add_argument("--probe-tt", action="store_true",
                    help="dump the Time Tracker JSON endpoint fields")
    ap.add_argument("--probe-terr", action="store_true",
                    help="dump every <select> on the dispositions page")
    ap.add_argument("--probe-ta", action="store_true",
                    help="capture network requests on the Today's Activity page")
    ap.add_argument("--limit", type=int, default=0,
                    help="cap territories per campaign (dispositions preview)")
    args = ap.parse_args(argv)

    if getattr(args, "probe_ta", False):
        from automations.shared.tableau_patchright import ownerville_session
        mdy = _central_now().strftime("%m/%d/%Y")
        firstjs = ("() => { const inp=document.querySelector("
                   "'input[placeholder*=\"owner\" i]'); let p=inp;"
                   " for(let i=0;i<7&&p&&p.parentElement;i++){p=p.parentElement;"
                   " const r=p.getBoundingClientRect(); if(r.height>300&&r.width<760)break;}"
                   " return p?[...p.querySelectorAll('*')].map(e=>(e.innerText||'')"
                   ".trim()).filter(t=>/[A-Za-z]{4} [A-Za-z]/.test(t)&&t.length<40)"
                   ".slice(0,4):[]; }")
        with ownerville_session(headless=args.headless) as page:
            rqst = cap.capture_rqst(page)
            cap.ensure_campaign(page, rqst, cfg.CAMPAIGN_ATT)
            cap._goto(page, cap._page_url(cfg.PAGE_TODAYS_ACTIVITY, rqst,
                      cfg.CAMPAIGN_ATT))
            dp = page.evaluate("() => [...document.querySelectorAll('input')]"
                ".filter(i=>/date/i.test(i.name||i.id||'')).map(i=>"
                "({name:i.name||i.id,val:i.value}))")
            print(f"  TA2 datepickers={dp}", flush=True)
            print(f"  TA2 before reps={page.evaluate(firstjs)}", flush=True)
            # Try setting each datepicker to today + fire change; then re-read.
            page.evaluate(
                "(mdy)=>{ for(const i of document.querySelectorAll('input')){"
                " if(/date/i.test(i.name||i.id||'')){ i.value=mdy;"
                " i.dispatchEvent(new Event('input',{bubbles:true}));"
                " i.dispatchEvent(new Event('change',{bubbles:true})); } } }", mdy)
            page.wait_for_timeout(4000)
            print(f"  TA2 after-setdate reps={page.evaluate(firstjs)}", flush=True)
            # Also try a URL date param.
            for pnm in ("date", "searchDate", "startDate"):
                cap._goto(page, cap._page_url(cfg.PAGE_TODAYS_ACTIVITY, rqst,
                          cfg.CAMPAIGN_ATT, f"&{pnm}={mdy}"))
                print(f"  TA2 url {pnm}={mdy} reps={page.evaluate(firstjs)}",
                      flush=True)
        return 0

    if getattr(args, "probe_terr", False):
        from automations.shared.tableau_patchright import ownerville_session
        with ownerville_session(headless=args.headless) as page:
            rqst = cap.capture_rqst(page)
            cap.ensure_campaign(page, rqst, cfg.CAMPAIGN_ATT)
            cap._goto(page, cap._page_url(cfg.PAGE_DISPOSITION, rqst,
                      cfg.CAMPAIGN_ATT, f"&pane={cfg.DISPOSITION_PANE}"))
            info = page.evaluate(
                "() => [...document.querySelectorAll('select')].map((s,i) => ({"
                " i, name: s.name||s.id||'', vis: s.offsetParent!==null,"
                " n: s.options.length,"
                " sample: [...s.options].slice(0,3).map(o=>(o.textContent||'')"
                ".replace(/\\s+/g,' ').trim().slice(0,40)) }))")
            for s in info:
                print(f"  select[{s['i']}] name={s['name']!r} vis={s['vis']} "
                      f"n={s['n']} sample={s['sample']}", flush=True)
        return 0

    if getattr(args, "probe_tt", False):
        from automations.shared.tableau_patchright import ownerville_session
        mdy = _central_now().strftime("%m/%d/%Y")
        with ownerville_session(headless=args.headless) as page:
            rqst = cap.capture_rqst(page)
            cap.ensure_campaign(page, rqst, cfg.CAMPAIGN_BOX)
            rows = cap.fetch_time_tracking(page, rqst, mdy)
            print(f"  tt rows={len(rows)}", flush=True)
            if rows:
                print(f"  keys={sorted(rows[0].keys())}", flush=True)
                for r in rows[:3]:
                    print(f"  row={r}", flush=True)
        return 0

    if args.probe_campaigns:
        from automations.shared.tableau_patchright import ownerville_session
        with ownerville_session(headless=args.headless) as page:
            try:
                page.set_viewport_size(dict(cap.VIEWPORT))
            except Exception:
                pass
            rqst = cap.capture_rqst(page)
            for cid in range(1, 31):
                url = (f"https://v2.ownerville.com/index.cfm?p={cfg.PAGE_TIME_TRACKER}"
                       f"&rqst={rqst}&invD2DClientId={cid}")
                try:
                    cap._goto(page, url)
                    label, cur = cap.current_campaign(page)
                except Exception as e:  # noqa: BLE001
                    label, cur = f"(err {type(e).__name__})", ""
                print(f"  probe id={cid} -> label={label!r} current={cur!r}",
                      flush=True)
        return 0

    # send -> live channels; preview -> DM Megan; neither -> dry-run (save only).
    dry_run = not (args.send or args.preview)
    today = _central_now().date()
    out_dir = OUTPUT_DIR / today.strftime("%Y-%m-%d")
    slot = slot_label(args.final)

    mode = ("SEND" if args.send else "PREVIEW-DM" if args.preview
            else "DRY-RUN (no Slack)")
    print(f"B2B Dispositions — {mode} — which={args.which} slot={slot!r} "
          f"out={out_dir}", flush=True)

    from automations.shared.tableau_patchright import ownerville_session
    specs: List[Dict] = []
    with ownerville_session(headless=args.headless) as page:
        # Tall viewport so more of each view sits in-frame (a plain screenshot
        # clips only within the viewport). Best-effort — a persistent context can
        # refuse a resize; the clamp in _shoot covers whatever the real size is.
        try:
            page.set_viewport_size(dict(cap.VIEWPORT))
        except Exception:
            pass
        rqst = cap.capture_rqst(page)
        if args.which in ("hourly", "all"):
            specs += _capture_hourly(page, rqst, out_dir, slot, dry_run, today)
        if args.which in ("dispositions", "all"):
            specs += _capture_dispositions(page, rqst, out_dir, dry_run,
                                           limit=args.limit, slot=slot, today=today)

    # Report captures (and flag any that fell back to a full-page shot or whose
    # on-screen campaign didn't match — the two things worth eyeballing).
    for s in specs:
        m = s["meta"]
        flag = []
        if m.get("how") == "full":
            flag.append("FULL-PAGE (crop anchor missed)")
        if "campaign_ok" in m and not m.get("campaign_ok"):
            flag.append(f"campaign on-screen={m.get('on_screen')!r}")
        if m.get("note"):
            flag.append(m["note"])
        note = ("  " + "; ".join(flag)) if flag else ""
        files = ", ".join(Path(p).name for p in s["paths"])
        print(f"  [{s['title']}]  ->  {files}{note}", flush=True)

    if args.preview:
        res = sp.preview_dm(specs, today)
        print(f"\nPREVIEW — DM'd {len(res.get('sent', []))}/{len(specs)} shot(s) "
              f"to Megan for review. errors={res.get('errors')}", flush=True)
        return 0 if res.get("ok") else 1

    if dry_run:
        print(f"\nDRY-RUN complete — {len(specs)} shot(s) saved to {out_dir}. "
              f"Nothing posted. Review the PNGs, then re-run with --preview/--send.",
              flush=True)
        return 0

    results = _post_specs(specs, today, dry_run=False)
    ok = all(r.get("ok") for r in results)
    print(f"\nPosted. ok={ok}", flush=True)
    for r in results:
        print(f"  {r['title']}: ok={r.get('ok')}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
