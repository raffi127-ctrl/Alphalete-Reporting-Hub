"""Answer a Facebook review the way a person does, from this office's computer.

WHY THIS EXISTS (Megan 2026-11-16: "we need it to automatically happen as
that's going to be a ton of accounts to go in and respond to"). Facebook's API
lets a Page comment on a review written by another Page, and REFUSES one
written by a person ("Permissions error") -- 24 of Alphalete's 26 reviews.
The same comment typed on facebook.com as the Page goes through (Megan checked
Wanda Moore Price's review by hand 11/16). So when the API says no, this
computer opens the review in a browser signed in as someone who manages the
Page, comments AS THE PAGE, and checks the comment is there.

  fb_signin -- PERSON: a window opens, the owner signs in to Facebook once.
               The sign-in stays in this computer's own browser folder.
  browser_reply(story, text, page_name) -- called by office_facebook.reply_job
               only after the API refused. Hidden: on a Mac a real window kept
               out of sight (quiet_window.Guard), elsewhere headless.

NEVER GETS AROUND A CHECK. A Facebook security check / "confirm it's you" page
stops the reply at once and answers "checkpoint"; Lucy 3 holds every reply for
that office and DMs the owner. Lucy 3 also sends at most one reply at a time,
spaced out (eco_fb.OUTBOX_GAP_MIN), so nothing here bursts.
"""
from __future__ import annotations

import platform
import time
from typing import Dict

from automations.icd_alerts import config as C

PROFILE = C.APP_DIR / "facebook-browser"
SIGNIN_MAX_MINUTES = 14
FB = "https://www.facebook.com"

_CHECK_WORDS = ("checkpoint", "confirm it's you", "confirm its you", "security check",
                "suspicious activity", "we suspended", "temporarily blocked",
                "you're temporarily", "your account has been locked")


def _busy() -> bool:
    return any((PROFILE / n).exists() for n in ("SingletonLock", "lockfile"))


def signed_in_here() -> bool:
    """A sign-in was saved on this computer (cookies folder exists)."""
    return (PROFILE / "Default").is_dir()


def _launch(p, *, visible: bool):
    PROFILE.mkdir(parents=True, exist_ok=True)
    args = ["--disable-sync", "--window-size=1280,900"]
    quiet = not visible and platform.system() == "Darwin"
    if quiet:
        from automations.icd_alerts import quiet_window as QW
        args += QW.FLAGS
    base = dict(user_data_dir=str(PROFILE), headless=not visible and not quiet, args=args,
                no_viewport=False)
    try:
        return p.chromium.launch_persistent_context(channel="chrome", **base), quiet
    except Exception:  # noqa: BLE001 -- no Google Chrome installed: patchright's own
        return p.chromium.launch_persistent_context(**base), quiet


def _logged_in(ctx) -> bool:
    try:
        return any(c.get("name") == "c_user" for c in ctx.cookies(FB))
    except Exception:  # noqa: BLE001
        return False


def _checkpoint(pg) -> bool:
    try:
        if "checkpoint" in (pg.url or "").lower():
            return True
        body = (pg.inner_text("body", timeout=4000) or "").lower()[:6000]
    except Exception:  # noqa: BLE001
        return False
    return any(w in body for w in _CHECK_WORDS)


# ---- sign-in (a person is at the screen) -------------------------------------------
def signin_job(payload: Dict, log=print) -> Dict:
    if _busy():
        return {"status": "busy", "error": "Lucy's Facebook window is already open"}
    minutes = int(payload.get("minutes") or SIGNIN_MAX_MINUTES)
    from patchright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx, _ = _launch(p, visible=True)
        try:
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            pg.goto(FB + "/login", wait_until="domcontentloaded", timeout=60000)
            end = time.time() + minutes * 60
            while time.time() < end:
                if _logged_in(ctx) and "checkpoint" not in (pg.url or ""):
                    time.sleep(3)                     # let Facebook finish saving
                    return {"status": "signed_in"}
                time.sleep(2)
            return {"status": "timed_out", "error": "nobody signed in within %d min" % minutes}
        finally:
            ctx.close()


# ---- one reply, hidden --------------------------------------------------------------
def _comment_box(pg, page_name: str):
    """The comment box, set to post AS THE PAGE. None when it can't be."""
    want = "comment as %s" % page_name.lower()
    boxes = pg.locator('div[contenteditable="true"][role="textbox"]')
    for i in range(min(boxes.count(), 6)):
        b = boxes.nth(i)
        label = ((b.get_attribute("aria-label") or "") + " " + (b.inner_text() or "")).lower()
        if want in label:
            return b
    # Signed in as the person: the little avatar menu beside the box switches who
    # comments. Pick the Page there, then look again.
    # "Switch to a different profile or Page" is the name Facebook gave it on
    # 11/16 (read off Wanda Moore Price's review in Megan's own Chrome).
    #
    # Pick the Page INSIDE the menu that opens. The first "Alphalete Marketing"
    # on the page is the left-hand Shortcuts link, and clicking that one is what
    # sent raf's first browser reply off to the Page's own feed ("not_page",
    # 11/16). In the menu each Page is a button labelled "<Page>" or
    # "<Page>, 9 notifications". Choosing it switches the whole Facebook session
    # to the Page and the post reloads -- so wait, then look again.
    for sel in ('[aria-label="Switch to a different profile or Page"]', '[aria-label*="Choose who"]',
                '[aria-label*="Select profile"]', '[aria-label*="Voice selector"]'):
        try:
            btn = pg.locator(sel).first
            if not btn.count():
                continue
            btn.click(timeout=4000)
            menu = pg.locator('[role="dialog"]').last
            menu.wait_for(timeout=6000)
            pick = menu.locator('[role="button"][aria-label="%s"], [role="button"][aria-label^="%s,"]'
                                % (page_name.replace('"', '\\"'), page_name.replace('"', '\\"'))).first
            pick.click(timeout=6000)
            pg.wait_for_timeout(2000)
            try:
                pg.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:  # noqa: BLE001 -- no reload is fine too
                pass
            pg.wait_for_timeout(4000)
            break
        except Exception:  # noqa: BLE001
            continue
    boxes = pg.locator('div[contenteditable="true"][role="textbox"]')
    for i in range(min(boxes.count(), 6)):
        b = boxes.nth(i)
        label = ((b.get_attribute("aria-label") or "") + " " + (b.inner_text() or "")).lower()
        if want in label:
            return b
    return None


_POSTED_JS = r"""
([name, snip]) => {
  const norm = t => (t || '').replace(/\s+/g, ' ').trim();
  const want = norm(snip);
  // a real comment BY THE PAGE, holding the reply -- never the comment box
  // (the box holds the same words while they're being typed: that is how
  // nine replies were counted as posted on 11/17 when none was)
  return [...document.querySelectorAll('[role="article"][aria-label]')].some(a =>
      a.getAttribute('aria-label').startsWith('Comment by ' + name) &&
      !a.querySelector('[contenteditable="true"]') && norm(a.innerText).includes(want));
}
"""


def _already(pg, page_name: str, text: str) -> bool:
    snip = " ".join((text or "").split())[:50]
    if not snip:
        return False
    try:
        return bool(pg.evaluate(_POSTED_JS, [page_name, snip]))
    except Exception:  # noqa: BLE001
        return False


def _box_text(box) -> str:
    try:
        return (box.inner_text(timeout=2000) or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def browser_reply(story: str, text: str, page_name: str, log=print, *, practice: bool = False) -> Dict:
    """practice=True stops once the 'Comment as <page>' box is found: nothing typed."""
    if not signed_in_here():
        return {"status": "needs_signin", "story": story,
                "error": "Facebook isn't signed in on this computer yet"}
    if _busy():
        return {"status": "busy", "story": story, "error": "Lucy's Facebook window is open"}
    from patchright.sync_api import sync_playwright
    guard = None
    with sync_playwright() as p:
        ctx, quiet = _launch(p, visible=False)
        try:
            if quiet:
                from automations.icd_alerts import quiet_window as QW
                guard = QW.Guard(PROFILE).start()
            if not _logged_in(ctx):
                return {"status": "needs_signin", "story": story, "error": "Facebook signed out"}
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            pg.goto("%s/%s" % (FB, story), wait_until="domcontentloaded", timeout=60000)
            pg.wait_for_timeout(4000)
            if _checkpoint(pg):
                return {"status": "checkpoint", "story": story,
                        "error": "Facebook is asking for a security check"}
            if "/login" in (pg.url or ""):
                return {"status": "needs_signin", "story": story, "error": "Facebook signed out"}
            if _already(pg, page_name, text):
                return {"status": "replied", "story": story, "via": "browser", "note": "already there"}
            box = _comment_box(pg, page_name)
            if box is None:
                return {"status": "not_page", "story": story,
                        "error": "this Facebook sign-in can't comment as %s" % page_name}
            if practice:
                return {"status": "found_box", "story": story, "via": "browser"}
            box.click(timeout=8000)
            pg.wait_for_timeout(600)
            # Typed like a person, one line at a time (Enter alone would send).
            lines = text.split("\n")
            for n, line in enumerate(lines):
                pg.keyboard.type(line, delay=25)
                if n < len(lines) - 1:
                    pg.keyboard.press("Shift+Enter")
            pg.wait_for_timeout(500)
            pg.keyboard.press("Enter")
            for _ in range(15):
                pg.wait_for_timeout(1000)
                if _checkpoint(pg):
                    return {"status": "checkpoint", "story": story,
                            "error": "Facebook asked for a security check after sending"}
                if _already(pg, page_name, text):
                    return {"status": "replied", "story": story, "via": "browser"}
            stuck = _box_text(box)
            return {"status": "error", "story": story,
                    "error": ("typed, but Facebook didn't send it (still in the comment box)" if stuck
                              else "sent, but the comment didn't show up under the review")}
        except Exception as e:  # noqa: BLE001
            return {"status": "error", "story": story, "error": ("%s: %s" % (type(e).__name__, e))[:200]}
        finally:
            if guard:
                guard.stop()
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass


# ---- reading the Page's reviews, no key needed -------------------------------------
# An office that never shared its Page with Alphalete's Meta business has no key
# on its computer, so the Graph read can't run. The same signed-in browser that
# types the replies reads the Page's Reviews tab instead (Megan 11/17: the owner
# signs in to Facebook once on the install call and never touches Meta settings).
#
# How the tab is laid out (read 11/17 on Alphalete Marketing's):
#   * only ~5 review cards are on the page at a time -- they come and go as it
#     scrolls, so the read scrolls slowly and collects each card as it passes
#   * a card's header says "<Name> recommends <Page>." or "doesn't recommend"
#   * a review the Page answered carries "Comment by <Page>" -- and a link to
#     the post with ?comment_id=; an unanswered one has no post link until the
#     mouse is over its date (the date's address fills in on hover)
#   * long reviews end in "See more" -- clicked before the text is kept
READ_MAX = 30                 # new reviews per read; the next read gets the rest
_MARK_JS = r"""
(name) => {
  const HEAD = / (recommends|doesn't recommend) /;
  const heads = [...document.querySelectorAll('div,span,h2,h3,h4')].filter(e =>
      e.children.length < 8 && HEAD.test(e.textContent||'') && (e.textContent||'').length < 200);
  const smallest = heads.filter(h => !heads.some(o => o !== h && h.contains(o)));
  const count = el => ((el.innerText||'').match(/ (recommends|doesn't recommend) /g)||[]).length;
  const out = [];
  for (const h of smallest) {
    let p = h, best = h;
    // climb to the whole card, never past it into the page (with one review on
    // screen, "one header inside" is true all the way up to <body>)
    const tooBig = el => el === document.body || el.matches('[role="main"]') ||
        el.querySelector('[role="navigation"], [role="banner"], [role="main"]');
    while (p.parentElement && count(p.parentElement) <= 1 && !tooBig(p.parentElement)) {
      p = p.parentElement; best = p;
    }
    if (!best.dataset.lucy) best.dataset.lucy = Math.random().toString(36).slice(2, 10);
    const labels = [...best.querySelectorAll('[aria-label]')].map(e => e.getAttribute('aria-label') || '');
    out.push({mark: best.dataset.lucy, head: (h.textContent||'').trim(), text: best.innerText || '',
              links: [...best.querySelectorAll('a[href]')].map(a => a.getAttribute('href')).filter(Boolean),
              answered: labels.some(l => l.startsWith('Comment by ' + name))});
  }
  return out;
}
"""


_LINKS_JS = """(m) => [...document.querySelectorAll('[data-lucy="' + m + '"] a[href]')]
                     .map(a => a.getAttribute('href')).filter(Boolean)"""


def post_link(links) -> str:
    """'<who>/posts/<id>' or 'permalink.php?story_fbid=..&id=..' -- what browser_reply opens."""
    import re
    for h in links or []:
        h = h.split("__cft__")[0]
        m = re.search(r"facebook\.com/([^?#]+?/posts/[^?&#/]+)", h)
        if m:
            return m.group(1)
        m = re.search(r"facebook\.com/(permalink\.php\?story_fbid=[^&#]+&id=\d+)", h)
        if m:
            return m.group(1)
    return ""


def _review_body(text: str) -> str:
    import re
    body = text.split("·", 1)[-1] if "·" in text else text
    body = re.sub(r"(?m)^Facebook\n", "", body)
    # the card's buttons and comments come after the review: stop at the first
    m = re.search(r"(?m)^(Like|Comment|Share|All reactions:?|Comment as .*|Comment by .*|\d+ comments?)$", body)
    if m:
        body = body[:m.start()]
    return re.sub(r"\s*… See more\s*$", "", body).strip()


def _listed_count(pg) -> int:
    """The '92% recommend (55 reviews)' number at the top of the tab, 0 if absent."""
    import re
    try:
        m = re.search(r"\((\d[\d,]*) reviews?\)", pg.inner_text("body", timeout=4000))
        return int(m.group(1).replace(",", "")) if m else 0
    except Exception:  # noqa: BLE001
        return 0


def read_reviews(page_url: str, page_name: str, skip=(), log=print) -> Dict:
    """Unanswered reviews on the Page's Reviews tab, in the shape the Graph read gives."""
    if not signed_in_here():
        return {"status": "signed_out", "error": "Facebook isn't signed in on this computer yet"}
    if _busy():
        return {"status": "busy", "error": "Lucy's Facebook window is open"}
    url = page_url.rstrip("/")
    if not url.startswith("http"):
        url = "%s/%s" % (FB, url.lstrip("/"))
    if not url.endswith("/reviews"):
        url += "/reviews"
    skip = set(skip or ())
    from patchright.sync_api import sync_playwright
    guard = None
    with sync_playwright() as p:
        ctx, quiet = _launch(p, visible=False)
        try:
            if quiet:
                from automations.icd_alerts import quiet_window as QW
                guard = QW.Guard(PROFILE).start()
            if not _logged_in(ctx):
                return {"status": "signed_out", "error": "Facebook signed out"}
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            pg.goto(url, wait_until="domcontentloaded", timeout=60000)
            pg.wait_for_timeout(6000)
            if _checkpoint(pg):
                return {"status": "checkpoint", "error": "Facebook is asking for a security check"}
            if "/login" in (pg.url or ""):
                return {"status": "signed_out", "error": "Facebook signed out"}
            seen, new, tried, still, linked = {}, [], set(), 0, set()
            for _ in range(160):
                for card in pg.evaluate(_MARK_JS, page_name):
                    link = post_link(card["links"])
                    if not link and card["mark"] not in tried:
                        tried.add(card["mark"])
                        try:                                  # the date fills its address on hover
                            a = pg.locator('[data-lucy="%s"] a[href^="?"], [data-lucy="%s"] a[href^="#"]'
                                           % (card["mark"], card["mark"])).first
                            if a.count():
                                # by script, not the mouse: a hidden window never
                                # answers real mouse input (hung here 11/17). The
                                # first pointer event re-writes the date's address,
                                # so the "?"-link locator stops matching -- read the
                                # card's links again rather than that element.
                                # "focusin" is the one that fills it (tested 11/17:
                                # pointer/mouse events alone left it as "?")
                                for ev in ("pointerover", "focusin"):
                                    try:
                                        a.dispatch_event(ev, timeout=1500)
                                    except Exception:  # noqa: BLE001 -- re-rendered: done
                                        break
                                pg.wait_for_timeout(400)
                                link = post_link(pg.evaluate(_LINKS_JS, card["mark"]))
                        except Exception:  # noqa: BLE001
                            pass
                    if link:
                        linked.add(card["mark"])
                    if not link or link in seen:
                        continue
                    seen[link] = card["answered"]
                    if card["answered"] or link in skip or len(new) >= READ_MAX:
                        continue
                    text = card["text"]
                    try:
                        more = pg.locator('[data-lucy="%s"] [role="button"]:text-is("See more")' % card["mark"]).first
                        if more.count():
                            more.dispatch_event("click", timeout=3000)
                            pg.wait_for_timeout(500)
                            text = pg.locator('[data-lucy="%s"]' % card["mark"]).inner_text(timeout=3000)
                    except Exception:  # noqa: BLE001
                        pass
                    new.append({"story": link,
                                "recommendation_type": "negative" if "doesn" in card["head"] else "positive",
                                "review_text": _review_body(text)[:2000], "created_time": ""})
                before = len(seen)
                pg.evaluate("window.scrollBy(0, 1400)")        # not mouse.wheel: see above
                pg.wait_for_timeout(2200)
                still = still + 1 if len(seen) == before else 0
                if still >= 14:
                    break
            if not seen:
                # Empty is only "no reviews" when the page says so; anything else
                # is a read that didn't work, and must not look like a quiet day.
                body = ""
                try:
                    body = pg.inner_text("body", timeout=5000)
                except Exception:  # noqa: BLE001
                    pass
                if "No reviews" not in body and "Not yet rated" not in body:
                    return {"status": "error", "error": "couldn't find any reviews on %s" % url}
            return {"status": "ok", "reviews": new, "total": len(seen), "via": "browser",
                    "unlinked": len(tried - linked),     # cards whose address never showed
                    "listed": _listed_count(pg), "more": len(new) >= READ_MAX}
        except Exception as e:  # noqa: BLE001
            return {"status": "error", "error": ("%s: %s" % (type(e).__name__, e))[:200]}
        finally:
            if guard:
                guard.stop()
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass


def main(argv=None) -> int:
    """By hand, for trying it out: sign in, or a practice run on one review.
        python -m automations.icd_alerts.office_fb_browser --signin
        python -m automations.icd_alerts.office_fb_browser --practice STORY "Page Name"
    """
    import argparse
    import json
    ap = argparse.ArgumentParser()
    ap.add_argument("--signin", action="store_true")
    ap.add_argument("--practice", nargs=2, metavar=("STORY", "PAGE"))
    ap.add_argument("--visible", action="store_true", help="practice in a window you can watch")
    a = ap.parse_args(argv)
    if a.signin:
        print(json.dumps(signin_job({})))
    elif a.practice:
        if a.visible:
            global _launch
            real = _launch
            _launch = lambda p, visible: real(p, visible=True)
        print(json.dumps(browser_reply(a.practice[0], "practice", a.practice[1], practice=True)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
