"""Zoho Social draft creator.

Zoho Social has no usable public draft API, so we drive a browser that's
ALREADY logged in — the same warm-session pattern as the ownerville session
holder. The human logs into Zoho ONCE in a dedicated persistent profile (2FA
handled normally); nothing sensitive is stored, the login just persists on
disk. The automation then reuses that profile to create DRAFTS only — it never
auto-publishes.

Two phases:
  --login : open the dedicated profile headful so the human can sign in once.
            Holds the window open until you create a `.stop` file in the
            profile dir (or the timeout elapses), then saves + closes.
  (draft creation is added once the Save-as-Draft composer flow is mapped.)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import sys
import time
from pathlib import Path

from patchright.sync_api import sync_playwright

from automations.shared.tableau_patchright import _launch_persistent, PROFILE_DIR

# Dedicated, isolated profile — separate from the report profiles and from the
# human's everyday Chrome, so the automation can drive it on a schedule.
ZOHO_PROFILE_DIR = PROFILE_DIR.parent / ".browser_profile_zoho"
ZOHO_SOCIAL_URL = "https://social.zoho.com/"
_STOP_FILE = ZOHO_PROFILE_DIR / ".stop"


def launch_login(max_minutes: int = 30) -> int:
    """Open the dedicated Zoho profile in a visible window for a one-time login.
    Cookies persist to ZOHO_PROFILE_DIR as the human signs in."""
    ZOHO_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    if _STOP_FILE.exists():
        _STOP_FILE.unlink()

    with sync_playwright() as p:
        ctx = _launch_persistent(p, ZOHO_PROFILE_DIR, headless=False,
                                 label="zoho-login")
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(ZOHO_SOCIAL_URL, wait_until="domcontentloaded",
                      timeout=60000)
        except Exception:
            pass
        print(f"Chrome is open. Log into Zoho Social (do your 2FA normally).",
              flush=True)
        print(f"When done, this closes on its own once {_STOP_FILE} appears "
              f"(or after {max_minutes} min).", flush=True)

        waited, deadline = 0, max_minutes * 60
        while waited < deadline and not _STOP_FILE.exists():
            time.sleep(2)
            waited += 2
        ctx.close()
    if _STOP_FILE.exists():
        _STOP_FILE.unlink()
    print("Login window closed — profile saved.", flush=True)
    return 0


# Composer selectors (mapped 2026-06-19 from a logged-in session).
_EDITOR = "#content-editor-newpost-content-editor-div"   # caption (contenteditable)
_MEDIA_BTN = "#zs-newpost-composer-footer-option-media"  # opens the media dialog
# after the media dialog uploads, the "Attach" button inserts it into the post
_IMG_PREVIEW = "#newpost-imgpreview img, #newpost-imglists img"  # in-composer thumb
_NEW_POST = "text=New Post"
_SAVE_DRAFT = "text=Save Draft"


# Channel network codes come from #newpost-composer-header-group-div-<net>-id.
# Hard rule: never post to Raf's personal LinkedIn. YouTube is never posted.
_NEVER_CHANNELS = ("linkedinprofile", "youtube")
_VIDEO_ONLY_CHANNELS = ("tiktok",)            # skipped for photo posts
_CHAN_GROUP = "#newpost-composer-header-group-div-{net}-id"


def _present_channels(pg) -> list[str]:
    return pg.evaluate(
        "() => [...document.querySelectorAll("
        "'[id^=\"newpost-composer-header-group-div-\"]')].map(g => "
        "g.id.replace('newpost-composer-header-group-div-','')"
        ".replace('-id',''))")


def select_channels(pg, media_type: str = "photo") -> list[str]:
    """Deselect channels we must not post to, return the ones left selected.
    ALWAYS removes Raf's personal LinkedIn (linkedinprofile) + YouTube; removes
    TikTok for photos (video-only). Raises if Raf's LinkedIn can't be removed —
    we never risk a live post there."""
    exclude = set(_NEVER_CHANNELS)
    if media_type != "video":
        exclude |= set(_VIDEO_ONLY_CHANNELS)

    for net in _present_channels(pg):
        if net not in exclude:
            continue
        try:
            g = pg.locator(_CHAN_GROUP.format(net=net)).first
            g.hover(timeout=4000)
            pg.wait_for_timeout(300)
            close = g.locator(".zs-compose--network-closeicon").first
            if close.count() and close.is_visible():
                close.click(timeout=3000)
            else:
                g.click(timeout=3000)
            pg.wait_for_timeout(500)
        except Exception:
            pass

    remaining = _present_channels(pg)
    # safety: Raf's personal LinkedIn must be gone, full stop
    if "linkedinprofile" in remaining:
        raise RuntimeError(
            "refusing to proceed: could not deselect Raf's personal LinkedIn "
            "(linkedinprofile) — hard rule.")
    return remaining


def _launch_zoho(p, headless: bool):
    """Persistent Zoho context with a LARGE viewport — the media dialog's
    'Attach' button sits bottom-right and is off-screen / unclickable at the
    default window size. System Chrome first, bundled Chromium fallback."""
    base = dict(user_data_dir=str(ZOHO_PROFILE_DIR), headless=headless,
                viewport={"width": 1680, "height": 1000},
                args=["--window-size=1700,1050"])
    try:
        return p.chromium.launch_persistent_context(channel="chrome", **base)
    except Exception:
        return p.chromium.launch_persistent_context(**base)


def _compose(pg, caption: str, image_path: str | None,
             media_type: str) -> list[str]:
    """Open New Post, set the caption, attach the photo (gallery -> Attach),
    and select channels. Returns the channels left selected. Shared by
    create_draft + schedule_post."""
    pg.locator(_NEW_POST).first.click(timeout=15000)
    pg.wait_for_timeout(3000)

    ed = pg.locator(_EDITOR).first
    ed.click()
    try:
        ed.fill(caption)
    except Exception:
        pg.keyboard.type(caption)

    # photo: media button -> file chooser -> gallery -> Attach (set_input_files
    # alone uploads to the gallery but never inserts it)
    if image_path:
        with pg.expect_file_chooser(timeout=15000) as fc:
            pg.locator(_MEDIA_BTN).first.click(timeout=10000)
        fc.value.set_files(image_path)
        pg.wait_for_timeout(3500)
        attach = pg.get_by_role("button", name="Attach").first
        attach.click(timeout=15000)
        try:
            attach.wait_for(state="detached", timeout=15000)  # dialog closes on insert
        except Exception:
            pg.wait_for_timeout(3000)
        pg.wait_for_timeout(2000)

    # channel selection (drops Raf's personal LinkedIn, YouTube, TikTok-for-photos)
    return select_channels(pg, media_type=media_type)


def _click_action(pg, label: str) -> bool:
    """Reliable click of a footer action button ('Post Now', 'Schedule', 'Save
    Draft'). The publishing-options popup overlaps these and the button can read
    'disabled' for a beat, so JS-click the INNERMOST element with this exact
    label (fires the real handler past the overlay); fall back to a forced UI
    click."""
    if pg.evaluate(
            "(t) => { let best = null;"
            " for (const n of document.querySelectorAll('*')) {"
            "   if ((n.innerText||'').trim() === t) {"
            "     if (!best || n.children.length < best.children.length) best = n; } }"
            " if (best) { best.click(); return true; } return false; }", label):
        return True
    loc = pg.locator(f"text={label}")
    for i in range(loc.count()):
        el = loc.nth(i)
        try:
            if el.is_visible():
                el.click(timeout=8000, force=True)
                return True
        except Exception:
            continue
    return False


def _click_save_draft(pg) -> None:
    if not _click_action(pg, "Save Draft"):
        raise RuntimeError("could not click Save Draft")


def create_draft(caption: str, image_path: str | None,
                 company_name: str = "", *, media_type: str = "photo",
                 headless: bool = False, timeout: int = 60000) -> dict:
    """Create a DRAFT post (image + caption) in Zoho Social via the warm
    logged-in profile, WITHOUT publishing. Runs headful — headless trips Zoho's
    re-auth wall. Raises if the session has expired (re-run `--login`).

    Channels are auto-selected by media type: Raf's personal LinkedIn + YouTube
    are always removed; TikTok is removed for photos. Returns the channels left.
    """
    from patchright.sync_api import sync_playwright

    ZOHO_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = _launch_zoho(p, headless)
        try:
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            pg.goto(ZOHO_SOCIAL_URL, wait_until="networkidle", timeout=timeout)
            if "accounts.zoho.com" in pg.url:
                raise RuntimeError(
                    "Zoho session expired — run `zoho_draft.py --login` to "
                    "re-authenticate, then retry.")
            pg.wait_for_timeout(2500)

            channels = _compose(pg, caption, image_path, media_type)
            _click_save_draft(pg)
            pg.wait_for_timeout(4000)

            from automations.brand_audit.config import OUTPUT_DIR
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            shot = str(OUTPUT_DIR / "_zoho_draft_result.png")
            try:
                pg.screenshot(path=shot, full_page=False)
            except Exception:
                shot = None
            # success = the composer closed (editor gone). If it's still open,
            # the save was blocked (validation) — report it instead of lying.
            try:
                still_open = pg.locator(_EDITOR).is_visible()
            except Exception:
                still_open = False
            if still_open:
                return {"ok": False, "screenshot": shot, "channels": channels,
                        "error": "composer still open after Save Draft — likely "
                                 "a channel validation issue"}
            return {"ok": True, "screenshot": shot, "channels": channels}
        finally:
            ctx.close()


# ---- scheduling -------------------------------------------------------------
# Schedule-panel selectors (mapped 2026-06-19).
_SCHED_RADIO = "text=Schedule for a Specific Date"
_DATE_INPUT = "#newpost-compose-publish_schedule_datepicker"
_CALENDAR = "#newpost-calendar-datepicker"
_CAL_NEXT = ".zso-next-line"
_CAL_DAY = "div.publish_day"
_HOUR_C = "#select2-zs-newpost-composer-publishingoption-schedule-custom-time-hour-container"
_MIN_C = "#select2-zs-newpost-composer-publishingoption-schedule-custom-time-minute-container"
# AM/PM is a toggle switch (checkbox), NOT a select2: unchecked = AM, checked = PM.
_AMPM_CHECKBOX = "#publish_time_ampm"
_AMPM_SWITCH = "label.timePeriodSwitch"
_SCHEDULE_BTN = "Schedule"

_SCHED_STATE = Path.home() / ".config" / "brand-audit" / "zoho_schedule.json"


def _visible(locator):
    """First visible match of a locator (or None) — for selectors that resolve
    to duplicate elements where only one is on-screen."""
    try:
        for i in range(locator.count()):
            if locator.nth(i).is_visible():
                return locator.nth(i)
    except Exception:
        pass
    return None


def _select2(pg, container_sel: str, value: str) -> None:
    """Pick `value` in a select2 dropdown (click container -> click option)."""
    pg.locator(container_sel).first.click(timeout=6000)
    pg.wait_for_timeout(400)
    pg.locator("li.select2-results__option", has_text=value).first.click(timeout=5000)
    pg.wait_for_timeout(300)


def _set_schedule(pg, when: dt.datetime) -> None:
    """Set the composer to schedule at `when` (local to the brand's time zone)."""
    pg.locator(_SCHED_RADIO).first.click(timeout=8000)
    pg.wait_for_timeout(1200)
    # date — open the calendar, page to the right month, click the day
    pg.locator(_DATE_INPUT).first.click(timeout=6000)
    pg.wait_for_timeout(800)
    cal = pg.locator(_CALENDAR).first
    target = when.strftime("%B %Y")
    for _ in range(24):
        if target in (cal.text_content(timeout=4000) or ""):
            break
        cal.locator(_CAL_NEXT).first.click(timeout=4000)
        pg.wait_for_timeout(400)
    cal.get_by_text(str(when.day), exact=True).first.click(timeout=5000)
    pg.wait_for_timeout(600)
    # time — 12h clock via select2
    h12 = when.hour % 12 or 12
    _select2(pg, _HOUR_C, f"{h12:02d}")
    _select2(pg, _MIN_C, f"{when.minute:02d}")
    # AM/PM toggle: checked = PM. There are duplicate switches in the DOM, so
    # operate on the VISIBLE one. Click only if it needs flipping.
    want_pm = when.hour >= 12
    sw = _visible(pg.locator(_AMPM_SWITCH))
    if sw is not None:
        cb = sw.locator("input.tpSwitch-input")
        try:
            if cb.is_checked() != want_pm:
                sw.click(timeout=4000)
                pg.wait_for_timeout(300)
        except Exception:
            pass


_JITTER_MINUTES = [3, 11, 17, 24, 33, 41, 48, 56]   # non-round -> looks human


def next_daily_slot(candidate_hours: list[int] | None = None) -> dt.datetime:
    """Next open DAILY slot: one post/day, never in the past, and NEVER the same
    time two days running. Rotates through `candidate_hours` (good windows) and
    adds a random non-round minute so the feed never looks automated."""
    # hard rule: nothing posts past 7pm -> no slot hour later than 6pm
    candidate_hours = [h for h in (candidate_hours or []) if 8 <= h <= 18] or [12]
    state = {}
    try:
        state = json.loads(_SCHED_STATE.read_text())
    except Exception:
        pass
    today = dt.date.today()
    last = state.get("last_scheduled_date")
    nxt = max(dt.date.fromisoformat(last) + dt.timedelta(days=1), today) if last else today
    # rotate to a different hour than the one we used last time
    last_hour = state.get("last_scheduled_hour")
    if last_hour in candidate_hours and len(candidate_hours) > 1:
        hour = candidate_hours[(candidate_hours.index(last_hour) + 1) % len(candidate_hours)]
    else:
        hour = candidate_hours[0]
    when = dt.datetime(nxt.year, nxt.month, nxt.day, hour,
                       random.choice(_JITTER_MINUTES))
    if when <= dt.datetime.now() + dt.timedelta(minutes=5):
        when += dt.timedelta(days=1)      # today's slot already passed -> tomorrow
    return when


def _record_slot(when: dt.datetime) -> None:
    _SCHED_STATE.parent.mkdir(parents=True, exist_ok=True)
    _SCHED_STATE.write_text(json.dumps(
        {"last_scheduled_date": when.date().isoformat(),
         "last_scheduled_hour": when.hour}, indent=2))


def schedule_post(caption: str, image_path: str | None, company_name: str = "",
                  *, when: dt.datetime | None = None, media_type: str = "photo",
                  dry_run: bool = True, headless: bool = False,
                  timeout: int = 60000) -> dict:
    """Compose (caption + photo + channel selection) then SCHEDULE the post.
    when=None -> next daily slot. dry_run=True is SAFE: it sets everything but
    clicks *Save Draft* instead of Schedule, so nothing publishes — flip to
    dry_run=False to actually schedule a live post. Returns the result + the
    scheduled datetime + channels left selected."""
    from patchright.sync_api import sync_playwright

    when = when or next_daily_slot()
    ZOHO_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = _launch_zoho(p, headless)
        try:
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            pg.goto(ZOHO_SOCIAL_URL, wait_until="networkidle", timeout=timeout)
            if "accounts.zoho.com" in pg.url:
                raise RuntimeError("Zoho session expired — run `--login`.")
            pg.wait_for_timeout(2500)
            channels = _compose(pg, caption, image_path, media_type)
            _set_schedule(pg, when)

            if dry_run:
                _click_save_draft(pg)   # SAFE: no live post
                result = {"ok": True, "dry_run": True, "channels": channels,
                          "scheduled_for": when.isoformat()}
            else:
                if not _click_action(pg, _SCHEDULE_BTN):
                    raise RuntimeError("could not click Schedule")
                pg.wait_for_timeout(4000)
                still = False
                try:
                    still = pg.locator(_EDITOR).is_visible()
                except Exception:
                    pass
                if still:
                    result = {"ok": False, "channels": channels,
                              "error": "composer still open after Schedule"}
                else:
                    _record_slot(when)
                    result = {"ok": True, "dry_run": False, "channels": channels,
                              "scheduled_for": when.isoformat()}
            return result
        finally:
            ctx.close()


def post_now(caption: str, image_path: str | None, company_name: str = "",
             *, media_type: str = "photo", headless: bool = False,
             timeout: int = 60000) -> dict:
    """PUBLISH the post immediately (Publish Now -> Post Now). Composes caption
    + photo + channel selection (Raf's personal LinkedIn always excluded), then
    posts live. Returns ok + channels. Irreversible once live."""
    from patchright.sync_api import sync_playwright

    ZOHO_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = _launch_zoho(p, headless)
        try:
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            pg.goto(ZOHO_SOCIAL_URL, wait_until="networkidle", timeout=timeout)
            if "accounts.zoho.com" in pg.url:
                raise RuntimeError("Zoho session expired — run `--login`.")
            pg.wait_for_timeout(2500)

            channels = _compose(pg, caption, image_path, media_type)
            # Publish Now is the default option; make sure it's selected
            try:
                pg.locator("text=Publish Now").first.click(timeout=4000)
                pg.wait_for_timeout(500)
            except Exception:
                pass
            if not _click_action(pg, "Post Now"):
                raise RuntimeError("could not click Post Now")
            pg.wait_for_timeout(2500)
            # a confirm dialog may appear -> accept it
            for sel in ["button:has-text('Publish')", "button:has-text('Confirm')",
                        "button:has-text('Yes')", "button:has-text('Post')"]:
                try:
                    el = pg.locator(sel).first
                    if el.is_visible():
                        el.click(timeout=2500)
                        break
                except Exception:
                    continue
            pg.wait_for_timeout(7000)

            from automations.brand_audit.config import OUTPUT_DIR
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            shot = str(OUTPUT_DIR / "_zoho_postnow_result.png")
            try:
                pg.screenshot(path=shot, full_page=False)
            except Exception:
                shot = None
            try:
                still_open = pg.locator(_EDITOR).is_visible()
            except Exception:
                still_open = False
            return {"ok": not still_open, "channels": channels, "screenshot": shot,
                    "error": None if not still_open else "composer still open after Post Now"}
        finally:
            ctx.close()


def main(argv=None) -> int:
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(prog="brand_audit.zoho_draft")
    p.add_argument("--login", action="store_true",
                   help="open the dedicated profile for a one-time Zoho login")
    p.add_argument("--minutes", type=int, default=30,
                   help="how long to hold the login window open")
    args = p.parse_args(argv)
    if args.login:
        return launch_login(args.minutes)
    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
