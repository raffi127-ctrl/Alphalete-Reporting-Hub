"""Read this office's own knocks out of OwnerVille, on this office's machine.

ONE DAY, ONE GRID, THEIR OWN LOGIN. No impersonation, no office picker, no
campaign pin -- an owner's account lands on their own office, which is the
entire reason this read is worth moving to their laptop rather than adding a
53rd impersonation to ours.

IT RELAYS ROWS, NOT A BOARD. What the rows are called, which columns matter,
how the card is drawn and when it is posted are all decided on our side. The
laptop's job is to be the thing that can authenticate, and nothing more.

THE SESSION IS REUSED. A persistent profile keeps the OwnerVille session alive
between runs, so most sweeps skip the login entirely -- which matters because
the login costs a full minute of deliberate waiting (see
shared/ownerville_knocks: the security box clears itself if you leave it
alone). Signing in every 15 minutes would be both slow and the kind of pattern
that earns a challenge.

THE LOGIN NEEDS A VISIBLE WINDOW; THE READS DO NOT. Proven against the live
site on 2026-09-11: headless, the password step comes back "Please complete the
security check" no matter how long you wait -- the box does not clear for a
headless browser. The same login headful sailed through and landed on the
office dashboard with an rqst. Once the session is in the profile, reads run
headless perfectly well (41 reps and 41 tracker rows, invisible).

So this opens headless, and only falls back to a window when the session has
actually lapsed -- which is rare. That window is why browser_banner exists: it
appears on somebody's screen unannounced, and the reasonable thing for them to
do with an unexplained browser is close it.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

from automations.icd_alerts import config as C
from automations.shared import ownerville_knocks as K


# Bump with every release that changes what this module does or reports; it
# is what a KnocksProblem's summary carries (see the stamp note below).
CODE_RELEASE = "2026.10.06.10"


class KnocksProblem(RuntimeError):
    """Phrased for whoever is reading it on an owner's laptop."""


# What the campaigns are called in OwnerVille's own client picker, for the
# fallback when the option values are not the ids. Seen on Jamis's page
# (2026-10-06): "B2B AT&T SBS" (id 2) and "B2B-BOX-Energy" (id 16).
_CLIENT_WORDS = {"b2b_att": ("at&t", "att"), "att": ("at&t", "att"),
                 "nds": ("nds", "at&t"), "b2b_box": ("box",), "energy": ("energy",)}


def _choose_client(page, cid: str, campaign: str, *, log=print) -> bool:
    """Pick this campaign in the page's own client <select>, if there is one.

    By option VALUE first (the ids OwnerVille uses everywhere else), then by
    the campaign's name words. Fires a change event so the page reloads its
    grid the way a click would. Returns False when nothing on the page could
    be picked -- the caller then raises the original error, with evidence."""
    words = list(_CLIENT_WORDS.get((campaign or "").strip().lower(), ()))
    try:
        picked = page.evaluate(
            """([cid, words]) => {
                const sels = Array.from(document.querySelectorAll('select'));
                const pick = (s, o) => {
                    s.value = o.value;
                    s.dispatchEvent(new Event('change', {bubbles: true}));
                    return (s.id || s.name || 'select') + ' -> ' + o.text.trim()
                        + ' (' + o.value + ')';
                };
                if (cid) for (const s of sels) {
                    const o = Array.from(s.options).find(o => o.value == cid);
                    if (o) return pick(s, o);
                }
                for (const s of sels) {
                    const o = Array.from(s.options).find(o => {
                        const t = (o.text || '').toLowerCase();
                        return t && !/choose/.test(t) && words.some(w => t.includes(w));
                    });
                    if (o) return pick(s, o);
                }
                return '';
            }""", [str(cid or ""), words])
    except Exception as e:  # noqa: BLE001 — no picker is an answer, not a crash
        log("client picker check failed: %s" % type(e).__name__)
        return False
    if not picked:
        # NOT A <select> ON HIS BUILD. Code .8/.9 evidence (Jamis): the body
        # shows "Choose a Client" with the two clients as LINKS, the header
        # dropdown already says the pinned client, and the page makes no
        # data call at all -- so the server wants the choice made through
        # its own link. Click the link whose text names this campaign,
        # preferring one that carries the id and one that is NOT inside the
        # header dropdown.
        try:
            picked = page.evaluate(
                """([cid, words]) => {
                    const all = Array.from(document.querySelectorAll('a, li, button, [onclick]'));
                    const cands = all.filter(e => {
                        const t = (e.innerText || '').trim().toLowerCase();
                        return t && t.length < 40 && !/choose/.test(t) && words.some(w => t.includes(w));
                    });
                    const tag = e => '<' + e.tagName.toLowerCase() + '#' + (e.id || '-') + '.' + (String(e.className) || '-')
                        + (e.href ? ' href=' + e.href.slice(0, 120) : '')
                        + (e.getAttribute('onclick') ? ' onclick=' + e.getAttribute('onclick').slice(0, 80) : '')
                        + '> ' + (e.innerText || '').trim().slice(0, 30);
                    const carries = e => cid && ((e.href || '') + (e.getAttribute('onclick') || '')).includes(cid);
                    const inHeader = e => !!e.closest('.D2DClientDropdown, .dropdown-menu, .navbar, nav, header');
                    const el = cands.find(e => carries(e) && !inHeader(e))
                        || cands.find(e => !inHeader(e))
                        || cands.find(carries) || cands[0];
                    if (!el) return '';
                    const d = 'link ' + tag(el);
                    el.click();
                    return d;
                }""", [str(cid or ""), words])
        except Exception as e:  # noqa: BLE001
            log("client link check failed: %s" % type(e).__name__)
            return False
    if not picked:
        log("no client picker or client link on the page")
        return False
    log("chose client in the page's own picker: %s" % picked)
    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except Exception:  # noqa: BLE001
        pass
    page.wait_for_timeout(1500)
    return True


def _page_evidence(page, seen: List[str], wire: Optional[List[str]] = None) -> str:
    """The read's own log lines plus where the page ended up and what it says.

    Best effort on every line: this runs inside a failure, and a probe that
    itself throws would replace a diagnosable fault with a crash."""
    out = ["what the read saw:"] + ["  " + ln for ln in seen[-15:]]
    if wire:
        # Code .9 showed the whole wire for his page: index.cfm?p=89 200,
        # dashboard/wizard.cfc 200, releaseManagement.cfc 200, cdn-cgi/rum
        # 204 -- and NO data call. Keep only what is not that: failures,
        # anything under /telemapper/, console errors.
        odd = [w for w in wire if not w.startswith("200 ") or "/telemapper/" in w
               or w.startswith("console")]
        out.append("wire: %d call(s); of note: %s" % (len(wire), " ; ".join(odd[-8:]) or "none"))
    try:
        out.append("page url: %s" % page.url)
    except Exception:  # noqa: BLE001
        pass
    try:
        out.append("page title: %s" % page.title())
    except Exception:  # noqa: BLE001
        pass
    # WHAT IS ON THE PAGE WHERE THE GRID SHOULD BE. Release .3 showed only the
    # menu (400 chars of nav) and nothing of the content; Jamis's page title
    # was right ("MIDSPIRE INC (19592) - Disposition By Rep") and the grid
    # still never built. So: every table's id/class, every iframe (a grid
    # inside a frame is invisible to a document query), and the content text
    # with the navigation stripped out.
    try:
        shape = page.evaluate(
            """() => {
                const tables = Array.from(document.querySelectorAll('table'))
                    .map(t => '#' + (t.id || '-') + '.' + (t.className || '-'))
                    .slice(0, 12).join(' | ');
                const frames = Array.from(document.querySelectorAll('iframe'))
                    .map(f => f.id || f.name || f.src || '?').slice(0, 6).join(' | ');
                const selects = Array.from(document.querySelectorAll('select'))
                    .map(s => '#' + (s.id || s.name || '-') + '[' + Array.from(s.options)
                        .map(o => o.value + '=' + (o.text || '').trim()).slice(0, 6).join(',') + ']')
                    .slice(0, 6).join(' | ');
                const dlgs = Array.from(document.querySelectorAll(
                        '[role=dialog], .modal, .swal2-popup, .ui-dialog, dialog'))
                    .filter(d => d.offsetParent !== null || d.open)
                    .map(d => '<' + d.tagName.toLowerCase() + '#' + (d.id || '-') + '.'
                        + (d.className || '-') + '> ' + (d.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 160)
                        + ' clickables[' + Array.from(d.querySelectorAll('button, a, li, [onclick], input[type=radio], input[type=button]'))
                            .map(b => (b.tagName.toLowerCase() + '#' + (b.id || '-') + '.' + (b.className || '-') + ':' + (b.innerText || b.value || '').trim().slice(0, 30)))
                            .slice(0, 10).join(' ; ') + ']')
                    .slice(0, 3).join(' || ');
                // THE CLIENT SWITCHER AND THE V1/V2 TOGGLE, wherever they live.
                // Jamis's page (code .6 evidence): "no client picker" -- the
                // only <select> was the V2-feedback module list; "Choose a
                // Client / B2B AT&T SBS / B2B-BOX-Energy" is a menu of links or
                // list items, and the page is the NEW (V2) OwnerVille, whose
                // grid is not #table-dispositions (zero <table> elements).
                const want = /return to v1|back to v1|switch to v1|classic|choose a client|b2b at&t|b2b-box|at&t sbs|energy/i;
                const hits = Array.from(document.querySelectorAll('a, button, li, span, label, div[onclick], [data-client], [data-id]'))
                    .filter(e => { const t = (e.innerText || '').trim(); return t && t.length < 60 && want.test(t); })
                    .map(e => '<' + e.tagName.toLowerCase() + '#' + (e.id || '-') + '.' + (String(e.className) || '-')
                        + (e.href ? ' href=' + e.href.slice(0, 150) : '') + (e.getAttribute('onclick') ? ' onclick=' + e.getAttribute('onclick').slice(0, 120) : '')
                        + (e.dataset && Object.keys(e.dataset).length ? ' data=' + JSON.stringify(e.dataset).slice(0, 60) : '')
                        + '> ' + (e.innerText || '').trim().slice(0, 40))
                    .slice(0, 8).join(' ; ');
                const c = document.body ? document.body.cloneNode(true) : null;
                if (c) c.querySelectorAll(
                    'nav, header, footer, script, style, #sidebar, .sidebar, '
                    + '.navbar, .nav, .menu, #menu, .topbar, #header, #footer')
                    .forEach(e => e.remove());
                const text = (c ? (c.innerText || c.textContent || '') : '')
                    .replace(/\\s+/g, ' ').trim().slice(0, 120);
                return {tables, frames, selects, dlgs, hits, text};
            }""")
        out.append("tables: %s" % (shape.get("tables") or "none"))
        out.append("iframes: %s" % (shape.get("frames") or "none"))
        out.append("selects: %s" % (shape.get("selects") or "none"))
        out.append("dialogs: %s" % (shape.get("dlgs") or "none"))
        out.append("controls: %s" % (shape.get("hits") or "none"))
        out.append("content text: %s" % (shape.get("text") or ""))
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(out)


def _context(p, headless: bool):
    C.OV_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    ctx = p.chromium.launch_persistent_context(
        str(C.OV_PROFILE_DIR), headless=headless, args=["--disable-sync"])
    if not headless:
        from automations.shared import browser_banner
        browser_banner.attach(ctx)
    return ctx


def _session(page, log=print) -> str:
    """An rqst token, signing in only if the profile's session has lapsed."""
    rqst = K.capture_rqst(page)
    if rqst:
        log("OwnerVille session still good")
        return rqst

    try:
        cr = C.ownerville_creds()
    except RuntimeError as e:
        raise KnocksProblem(str(e))

    log("OwnerVille session has lapsed — signing in")
    try:
        K.login(page, cr["username"], cr["password"], log=log)
    except Exception as e:  # noqa: BLE001
        raise KnocksProblem(
            "Could not sign in to OwnerVille. If you recently changed your "
            "OwnerVille password, open Lucy Reports and enter the new one. "
            "(%s)" % type(e).__name__)

    rqst = K.capture_rqst(page)
    if not rqst:
        raise KnocksProblem(
            "Signed in to OwnerVille but it did not open a working session. "
            "Nothing is lost — the next run tries again.")
    return rqst


def _has_session(p, log=print) -> bool:
    """Cheap headless probe: is the profile's OwnerVille session still live?"""
    ctx = _context(p, True)
    try:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        return bool(K.capture_rqst(page))
    except Exception:  # noqa: BLE001
        return False
    finally:
        try:
            ctx.close()
        except Exception:  # noqa: BLE001
            pass


def read_knocks(day: Optional[dt.date] = None, *, headless: bool = True,
                campaign: str = "",
                log=print) -> Dict[str, List[Dict]]:
    """Today's grid AND time tracker for this office, both raw.

    {'rows': [...], 'time_tracker': [...]}. The gaps live in the second one --
    the disposition grid has no idea how long a rep stood still -- and a board
    without them reads as "nobody was idle" rather than "we did not look".
    """
    from patchright.sync_api import sync_playwright

    day = day or C.today()
    mdy = day.strftime("%m/%d/%Y")      # NOT %-m/%-d: that is not portable

    with sync_playwright() as p:
        # A window ONLY when one is actually needed. The security check on the
        # password step never clears for a headless browser, so a lapsed
        # session has to be re-established in a visible one -- but that is the
        # rare case, and making every sweep visible would put a browser on the
        # owner's screen four times an hour for no reason.
        show = headless and not _has_session(p, log=log)
        if show:
            log("OwnerVille needs signing in again — opening a window briefly")
        ctx = _context(p, headless and not show)
        # KEEP WHAT THE READ SAW. When the grid never appears, the traceback
        # says only that -- and from a laptop we cannot open, that was the
        # whole story. Jamis (2026-10-06): signed in, campaigns pinned, no
        # table, for four hours, while the same office impersonated from
        # Lucy 2 served its grid at once. The log lines, the URL the page
        # ended on and the first words of its body are the difference.
        seen: List[str] = []

        def _l(msg: str) -> None:
            seen.append(str(msg))
            log(msg)

        # WHAT THE PAGE ASKED THE SERVER FOR. On Jamis's new-UI account the
        # dispositions page lands on the right client (D2DClientDropdown
        # currentId = the pin) and still renders no grid; the grid is filled
        # by an AJAX call, so the calls and their statuses are the next thing
        # to read -- and the data call's URL is what would let this reader
        # fetch rows on either UI.
        wire: List[str] = []

        def _on_response(resp):
            try:
                url = resp.url
                if "ownerville" not in url or any(
                        url.split("?")[0].lower().endswith(x) for x in
                        (".js", ".css", ".png", ".gif", ".svg", ".woff", ".woff2",
                         ".ico", ".jpg", ".ttf", ".map")):
                    return
                wire.append("%s %s" % (resp.status, url[:150]))
            except Exception:  # noqa: BLE001
                pass

        def _on_console(msg):
            try:
                if msg.type in ("error", "warning"):
                    wire.append("console %s: %s" % (msg.type, msg.text[:140]))
            except Exception:  # noqa: BLE001
                pass

        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.on("response", _on_response)
            page.on("console", _on_console)
            rqst = _session(page, log=_l)
            # PIN THE CAMPAIGN FIRST. The campaign is a sticky session-global
            # in OwnerVille, so an unpinned read on a multi-campaign owner
            # returns whatever THEY last clicked. Whether the grid that
            # arrives really is that campaign's is checked on our side,
            # against the rows -- a pin can fail to take and still serve a
            # grid (Calvin, 2026-09-02).
            cid = C.CAMPAIGN_IDS.get((campaign or "").strip().lower()) \
                if campaign else C.campaign_id()
            if cid:
                K.pin_campaign(page, rqst, cid, log=_l)
            K.navigate(page, rqst, mdy, log=_l)
            try:
                try:
                    rows = K.read_rows(page, log=_l)
                except K.OwnervilleError:
                    # HIS OWNERVILLE ASKS ON THE PAGE. Jamis (2026-10-06):
                    # signed in, campaign pinned through p=88, and the page
                    # rendered "Choose a Client -- B2B AT&T SBS / B2B-BOX-
                    # Energy" with no table at all, for four hours. On that
                    # build the pin is not enough; the client has to be
                    # picked in the page's own selector. So pick it, land
                    # on the page once more, and read again.
                    if not _choose_client(page, cid, campaign, log=_l):
                        raise
                    K.navigate(page, rqst, mdy, attempts=1, log=_l)
                    rows = K.read_rows(page, log=_l)
            except K.OwnervilleError as e:
                # STAMPED WITH THE RELEASE: the relay folds same-summary
                # faults and keeps the FIRST detail, so a new release's
                # evidence would otherwise land under the old release's
                # cut-off text. One row per release, not one per sweep.
                # THE CODE'S OWN STAMP, not the release file on disk: twice
                # today (.4, .6) an update landed while a sweep was mid-read,
                # the stamp came from the new file and the evidence from the
                # old code, and the one row that release gets was spent on it.
                problem = KnocksProblem(
                    "%s (what the page showed is in the fault detail, "
                    "code %s)" % (e, CODE_RELEASE))
                problem.seen = _page_evidence(page, seen, wire)
                raise problem
            # Never fatal: the disposition half is still worth handing over,
            # and losing the whole board because the gaps endpoint blipped
            # would be the wrong trade.
            try:
                tracker = K.fetch_time_tracker(page, rqst, mdy, log=log)
            except Exception as e:  # noqa: BLE001
                log("time tracker failed (%s) — gaps will be blank"
                    % type(e).__name__)
                tracker = []
            return {"rows": rows, "time_tracker": tracker}
        finally:
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass
