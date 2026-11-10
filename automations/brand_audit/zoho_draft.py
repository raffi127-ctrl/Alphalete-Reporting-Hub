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

# Dedicated, isolated profile — separate from the report profiles and from the
# human's everyday Chrome, so the automation can drive it on a schedule.
# Same folder as tableau_patchright.PROFILE_DIR's parent, spelled out here so
# this file ships to ICD office computers (online presence) WITHOUT the whole
# Tableau stack: nothing at import time may need more than patchright.
ZOHO_PROFILE_DIR = (Path(__file__).resolve().parent.parent / "uploaded"
                    / ".browser_profile_zoho")
ZOHO_SOCIAL_URL = "https://social.zoho.com/"


def launch_login(max_minutes: int = 30, profile_dir: Path | None = None) -> int:
    """Open the dedicated Zoho profile in a visible window for a one-time login.
    Cookies persist to the profile dir as the human signs in. `profile_dir` =
    an office's own Zoho login (online_presence); None = Alphalete's."""
    profile_dir = Path(profile_dir or ZOHO_PROFILE_DIR)
    stop_file = profile_dir / ".stop"
    profile_dir.mkdir(parents=True, exist_ok=True)
    if stop_file.exists():
        stop_file.unlink()

    from automations.shared.tableau_patchright import _launch_persistent
    with sync_playwright() as p:
        ctx = _launch_persistent(p, profile_dir, headless=False,
                                 label="zoho-login")
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(ZOHO_SOCIAL_URL, wait_until="domcontentloaded",
                      timeout=60000)
        except Exception:
            pass
        print(f"Chrome is open. Log into Zoho Social (do your 2FA normally).",
              flush=True)
        print(f"When done, this closes on its own once {stop_file} appears "
              f"(or after {max_minutes} min).", flush=True)

        waited, deadline = 0, max_minutes * 60
        while waited < deadline and not stop_file.exists():
            time.sleep(2)
            waited += 2
        ctx.close()
    if stop_file.exists():
        stop_file.unlink()
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


# The pages an ICD can pick on sign-up, and how each shows up in Zoho's
# composer (the <net> in #newpost-composer-header-group-div-<net>-id).
# CONFIRMED on Alphalete's Zoho 2026-11-09: facebookpage, twitter, instagram,
# googlemybusiness, tiktok (LinkedIn wasn't connected there to see its code;
# anything 'linkedin…' except 'linkedinprofile' is read as the company page).
# Matched loosely on purpose -- 'linkedinprofile' is the PERSONAL profile
# and is never a page, everything else LinkedIn is the company page.
PAGES = ("instagram", "facebook", "google", "linkedin", "x")


def page_of(net: str) -> str | None:
    """Zoho channel code -> one of PAGES (None = not a page we post to)."""
    n = (net or "").lower()
    if "linkedinprofile" in n or "youtube" in n or "tiktok" in n:
        return None
    if "instagram" in n:
        return "instagram"
    if "facebook" in n or n.startswith("fb"):
        return "facebook"
    if "linkedin" in n:
        return "linkedin"
    if "twitter" in n or n in ("x", "xprofile"):
        return "x"
    if "google" in n or "gmb" in n or "gbp" in n:
        return "google"
    return None


def _present_channels(pg) -> list[str]:
    return pg.evaluate(
        "() => [...document.querySelectorAll("
        "'[id^=\"newpost-composer-header-group-div-\"]')].map(g => "
        "g.id.replace('newpost-composer-header-group-div-','')"
        ".replace('-id',''))")


# Zoho's home "Brand Health" table names every connected page the way it shows
# publicly, with the network in the icon's class (read 2026-11-10 on
# Alphalete's Zoho: fbPage / tw / lin (a PERSON, skipped) / linPage / ig /
# tiktok). Google isn't in that table.
_NAME_ICON = {"fbPage": "facebook", "ig": "instagram", "tw": "x",
              "linPage": "linkedin", "tiktok": "tiktok"}


def page_names(pg) -> dict:
    """{page: public name} for the connected pages, e.g. {"facebook":
    "Alphalete Marketing", "instagram": "alphaletemarketing"}. {} if the
    table isn't there."""
    try:
        pg.wait_for_selector(".zsImg", timeout=15000)
    except Exception:
        return {}
    rows = pg.evaluate("""() => [...document.querySelectorAll('.zsImg')].map(i => {
        let row = i.parentElement;
        for (let k = 0; k < 4 && row && !(row.innerText || '').trim(); k++) row = row.parentElement;
        return {cls: String(i.getAttribute('class') || ''), name: ((row || {}).innerText || '').trim().split(String.fromCharCode(10))[0]};
    })""")
    out = {}
    for r in rows or []:
        toks = set(str(r.get("cls") or "").split())
        page = next((v for k, v in _NAME_ICON.items() if k in toks), None)
        name = (r.get("name") or "").strip()
        if page and name and page not in out:
            out[page] = name
    return out


def select_channels(pg, media_type: str = "photo",
                    keep: tuple | None = None) -> list[str]:
    """Deselect channels we must not post to, return the ones left selected.
    ALWAYS removes Raf's personal LinkedIn (linkedinprofile) + YouTube; removes
    TikTok for photos (video-only). Raises if Raf's LinkedIn can't be removed —
    we never risk a live post there."""
    exclude = set(_NEVER_CHANNELS)
    if media_type != "video":
        exclude |= set(_VIDEO_ONLY_CHANNELS)
    # `keep` = the pages an office chose on sign-up: anything else connected
    # in their Zoho is deselected, so Lucy posts only where they said.
    if keep is not None:
        exclude |= {n for n in _present_channels(pg) if page_of(n) not in keep}

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


def _launch_zoho(p, headless: bool, profile_dir: Path | None = None):
    """Persistent Zoho context with a LARGE viewport — the media dialog's
    'Attach' button sits bottom-right and is off-screen / unclickable at the
    default window size. System Chrome first, bundled Chromium fallback."""
    base = dict(user_data_dir=str(profile_dir or ZOHO_PROFILE_DIR), headless=headless,
                viewport={"width": 1680, "height": 1000},
                args=["--window-size=1700,1050"])
    try:
        return p.chromium.launch_persistent_context(channel="chrome", **base)
    except Exception:
        return p.chromium.launch_persistent_context(**base)


def _compose(pg, caption: str, image_path: str | None,
             media_type: str, keep: tuple | None = None) -> list[str]:
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
    # Several photos = one post (Megan 2026-11-09): they go into the gallery
    # together and Attach inserts them all.
    files = ([str(x) for x in image_path] if isinstance(image_path, (list, tuple))
             else [str(image_path)] if image_path else [])
    if files:
        with pg.expect_file_chooser(timeout=15000) as fc:
            pg.locator(_MEDIA_BTN).first.click(timeout=10000)
        fc.value.set_files(files if len(files) > 1 else files[0])
        # A reel uploads + processes far slower than a photo: give it time
        # before Attach (a too-early click attaches nothing).
        is_video = files[0].lower().endswith((".mp4", ".mov"))
        pg.wait_for_timeout(20000 if is_video else 3500 + 2500 * (len(files) - 1))
        attach = pg.get_by_role("button", name="Attach").first
        attach.click(timeout=60000 if is_video else 15000)
        try:
            attach.wait_for(state="detached", timeout=15000)  # dialog closes on insert
        except Exception:
            pg.wait_for_timeout(3000)
        pg.wait_for_timeout(2000)

    # channel selection (drops Raf's personal LinkedIn, YouTube, TikTok-for-photos)
    return select_channels(pg, media_type=media_type, keep=keep)


def channel_check(profile_dir: Path | None = None, *, headless: bool = False,
                  timeout: int = 60000) -> dict:
    """Is this Zoho login still signed in, and which socials are connected?

    Opens New Post only to read the channel list, then closes the window
    without saving anything (nothing is typed, so there is nothing to keep).
    For the install call: run it after the owner connects their accounts."""
    Path(profile_dir or ZOHO_PROFILE_DIR).mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = _launch_zoho(p, headless, profile_dir)
        try:
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            pg.goto(ZOHO_SOCIAL_URL, wait_until="networkidle", timeout=timeout)
            if "accounts.zoho.com" in pg.url:
                return {"logged_in": False, "channels": []}
            pg.wait_for_timeout(5000)
            try:
                names = page_names(pg)
            except Exception:
                names = {}
            btn = next((x for x in pg.locator(_NEW_POST).all() if x.is_visible()), None)
            if btn is None:
                return {"logged_in": True, "channels": [], "names": names,
                        "note": "no New Post button"}
            btn.click(timeout=15000)
            pg.wait_for_timeout(4000)
            return {"logged_in": True, "channels": _present_channels(pg), "names": names}
        finally:
            ctx.close()


def wait_for_signin(profile_dir: Path | None = None, *, max_minutes: int = 20,
                    timeout: int = 60000) -> dict:
    """Open Zoho in a visible window and wait for a PERSON to sign in.

    For an ICD's own computer (online presence): Lucy asks, this window opens
    on their screen, the owner signs into THEIR Zoho, and the window closes on
    its own the moment the Zoho home loads -- no stop file, nothing to press.
    Returns {"logged_in", "channels"}; never types a password itself."""
    Path(profile_dir or ZOHO_PROFILE_DIR).mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = _launch_zoho(p, False, profile_dir)
        try:
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                pg.goto(ZOHO_SOCIAL_URL, wait_until="domcontentloaded",
                        timeout=timeout)
            except Exception:
                pass
            deadline = time.time() + max_minutes * 60
            while time.time() < deadline:
                # EVERY TAB, and only a VISIBLE "New Post" (2026-11-09: Zoho
                # landed its home in another tab, and the page carries a hidden
                # duplicate button, so watching the first tab's first match
                # sat there after a successful sign-in).
                for tab in list(ctx.pages):
                    try:
                        if "social.zoho.com" not in tab.url or "accounts.zoho.com" in tab.url:
                            continue
                        btn = next((x for x in tab.locator(_NEW_POST).all()
                                    if x.is_visible()), None)
                        if btn is None:
                            continue
                        btn.click(timeout=15000)
                        tab.wait_for_timeout(4000)
                        return {"logged_in": True, "channels": _present_channels(tab)}
                    except Exception:
                        continue
                time.sleep(3)
            return {"logged_in": False, "channels": []}
        finally:
            ctx.close()


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
                 headless: bool = False, timeout: int = 60000,
                 profile_dir: Path | None = None) -> dict:
    """Create a DRAFT post (image + caption) in Zoho Social via the warm
    logged-in profile, WITHOUT publishing. Runs headful — headless trips Zoho's
    re-auth wall. Raises if the session has expired (re-run `--login`).

    Channels are auto-selected by media type: Raf's personal LinkedIn + YouTube
    are always removed; TikTok is removed for photos. Returns the channels left.
    """
    from patchright.sync_api import sync_playwright

    Path(profile_dir or ZOHO_PROFILE_DIR).mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = _launch_zoho(p, headless, profile_dir)
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
    """Pick `value` in a select2 dropdown (click container -> click option),
    tolerant of the container being briefly off-screen / not yet ready."""
    c = pg.locator(container_sel).first
    try:
        c.scroll_into_view_if_needed(timeout=4000)
    except Exception:
        pass
    c.click(timeout=10000)
    pg.wait_for_timeout(400)
    opt = pg.locator("li.select2-results__option", has_text=value).first
    opt.wait_for(state="visible", timeout=6000)
    opt.click(timeout=6000)
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
    # the calendar overlay must close before the time pickers are reachable
    try:
        pg.locator(_CALENDAR).first.wait_for(state="hidden", timeout=5000)
    except Exception:
        pg.wait_for_timeout(1000)
    pg.wait_for_timeout(500)
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


def next_daily_slot(candidate_hours: list[int] | None = None,
                    sched_state: Path | None = None) -> dt.datetime:
    """Next open DAILY slot: one post/day, never in the past, and NEVER the same
    time two days running. Rotates through `candidate_hours` (good windows) and
    adds a random non-round minute so the feed never looks automated."""
    # hard rule: nothing posts past 7pm -> no slot hour later than 6pm
    candidate_hours = [h for h in (candidate_hours or []) if 8 <= h <= 18] or [12]
    state = {}
    try:
        state = json.loads(Path(sched_state or _SCHED_STATE).read_text())
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


def posted_today(sched_state: Path | None = None) -> bool:
    """True once a post already went out (or was scheduled) for today -- the
    one-a-day rule for offices whose free Zoho cannot schedule."""
    try:
        state = json.loads(Path(sched_state or _SCHED_STATE).read_text())
    except Exception:
        return False
    return state.get("last_scheduled_date") == dt.date.today().isoformat()


def _record_slot(when: dt.datetime, sched_state: Path | None = None) -> None:
    f = Path(sched_state or _SCHED_STATE)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(
        {"last_scheduled_date": when.date().isoformat(),
         "last_scheduled_hour": when.hour}, indent=2))


def schedule_post(caption: str, image_path: str | None, company_name: str = "",
                  *, when: dt.datetime | None = None, media_type: str = "photo",
                  dry_run: bool = True, headless: bool = False,
                  timeout: int = 60000, profile_dir: Path | None = None,
                  sched_state: Path | None = None) -> dict:
    """Compose (caption + photo + channel selection) then SCHEDULE the post.
    when=None -> next daily slot. dry_run=True is SAFE: it sets everything but
    clicks *Save Draft* instead of Schedule, so nothing publishes — flip to
    dry_run=False to actually schedule a live post. Returns the result + the
    scheduled datetime + channels left selected."""
    from patchright.sync_api import sync_playwright

    when = when or next_daily_slot(sched_state=sched_state)
    Path(profile_dir or ZOHO_PROFILE_DIR).mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = _launch_zoho(p, headless, profile_dir)
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
                    _record_slot(when, sched_state)
                    result = {"ok": True, "dry_run": False, "channels": channels,
                              "scheduled_for": when.isoformat()}
            return result
        finally:
            ctx.close()


def post_now(caption: str, image_path: str | None, company_name: str = "",
             *, media_type: str = "photo", headless: bool = False,
             timeout: int = 60000, profile_dir: Path | None = None,
             keep: tuple | None = None) -> dict:
    """PUBLISH the post immediately (Publish Now -> Post Now). Composes caption
    + photo + channel selection (Raf's personal LinkedIn always excluded), then
    posts live. Returns ok + channels. Irreversible once live."""
    from patchright.sync_api import sync_playwright

    Path(profile_dir or ZOHO_PROFILE_DIR).mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = _launch_zoho(p, headless, profile_dir)
        try:
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            pg.goto(ZOHO_SOCIAL_URL, wait_until="networkidle", timeout=timeout)
            if "accounts.zoho.com" in pg.url:
                raise RuntimeError("Zoho session expired — run `--login`.")
            pg.wait_for_timeout(2500)

            channels = _compose(pg, caption, image_path, media_type, keep)
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
    p.add_argument("--office", default="",
                   help="an office's ECO key: log into THAT office's Zoho")
    args = p.parse_args(argv)
    if args.login:
        prof = None
        if args.office:
            from automations.online_presence import offices
            o = offices.get(args.office)
            if not o:
                print(f"no online-presence office {args.office!r}")
                return 1
            prof = o.zoho_profile
        return launch_login(args.minutes, prof)
    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
