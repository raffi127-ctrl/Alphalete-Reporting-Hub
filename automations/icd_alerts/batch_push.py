"""Resume Helper batch push, on an office's own computer -- TRIAL, 24065 only.

Megan 2026-11-25: "I think we want to try using the resume extension bot
helper to push apps again for Indeed" ... "yes, build it for Raf's 24065".

WHY IT IS BACK. The batch robot (AppStream v2 -> Process in Batches -> the
Resume Helper extension pulls every resume off Indeed in one burst) was
dropped on 2026-10-20 because Indeed blocked it. That was measured on the
Lucys, on the HQ Wi-Fi -- the same Wi-Fi we later proved makes Indeed want a
human on every read (memory: reference_indeed_check_hq_wifi). On an office's
own internet it may hold up. This module finds out, carefully:

  * ONE office (BATCH_OFFICES), a SMALL send (BATCH_LIMIT rows per run).
  * "dry" first: opens Process in Batches, counts what is ready, checks the
    extension is installed in LUCY'S Chrome and that the page is on the right
    office -- and clicks neither Start nor Send.
  * "live": Resume Helper extracts for at most EXTRACT_CAP_S, then the first
    BATCH_LIMIT rows go to AI. If Indeed blocks the extractor twice in a row
    the batch switches ITSELF off for the day and the one-at-a-time walk
    carries on as before.

Self-contained on purpose: resume_pushing/run.py (the Lucys' batch code this
borrows from) imports Hub-only modules an office computer does not have.
Runs in Lucy's own hidden Chrome; opens nothing the owner can see.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time
from pathlib import Path
from typing import Callable, Optional

# office -> "dry" | "live". Live only after a dry run has been read.
BATCH_OFFICES = {"24065": "live"}   # back on 2026-11-25 (Megan: "yes turn it back on"); Thanksgiving pause covers it via quiet_window
BATCH_LIMIT = 10
EXTRACT_CAP_S = 240
OFF_AFTER_BLOCKS = 2
EXT_ID = "goofbdglmeckblcbcoffnkdnmpehhhmo"     # Resume Helper
TABLE = "#table-batch-resume"
CONSOLE_URL = "https://applicantstream.com/index.cfm"

_log: Callable[[str], None] = print
# Where open_batches got to on its last try, for the stats row (11/25: three
# runs said only "Process in Batches not reached").
LAST_STEPS: list = []


def _step(page, what: str) -> None:
    try:
        where = "%s | %s" % ((page.title() or "")[:50], (page.url or "")[-70:])
    except Exception:  # noqa: BLE001
        where = "?"
    LAST_STEPS.append("%s @ %s" % (what, where))
    _log("[batch] step: %s @ %s" % (what, where))


def set_logger(fn) -> None:
    global _log
    _log = fn


def mode_for(office: str) -> Optional[str]:
    return BATCH_OFFICES.get(str(office or ""))


def extension_installed(profile_dir) -> bool:
    """Is Resume Helper in LUCY'S Chrome profile (never the owner's)?"""
    try:
        p = Path(profile_dir)
        return any((p / prof / "Extensions" / EXT_ID).is_dir()
                   for prof in ("Default", "Profile 1"))
    except Exception:  # noqa: BLE001
        return False


# --- small helpers (as in resume_pushing/run.py) ---------------------------------
def _click_if_present(page, labels, timeout: int = 5000) -> bool:
    for label in labels:
        loc = page.locator(f"xpath=//button[contains(normalize-space(.),'{label}')]"
                           f" | //a[contains(normalize-space(.),'{label}')]"
                           f" | //*[@role='button'][contains(normalize-space(.),'{label}')]")
        try:
            if loc.count() > 0:
                loc.first.click(timeout=timeout, no_wait_after=True)
                page.wait_for_timeout(1500)
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _main_world(page, expr: str):
    """jQuery/DataTables live in the page's main world, which patchright's
    evaluate cannot see; a script tag writes the answer into the DOM."""
    try:
        page.add_script_tag(content=(
            "(function(){try{document.body.setAttribute('data-mw', String(" + expr + "));}"
            "catch(e){document.body.setAttribute('data-mw','__ERR__:'+e);}})();"))
        page.wait_for_timeout(300)
        return page.evaluate("() => document.body.getAttribute('data-mw')")
    except Exception as e:  # noqa: BLE001
        return f"__ERR__:{e}"


def _int(v) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _shadow_find(page, text: str):
    """Element with this exact text, piercing shadow roots (the extension's
    popup lives in one). Its centre, or None."""
    return page.evaluate(
        "(want) => { function* walk(r){ for (const e of r.querySelectorAll('*')){"
        " yield e; if (e.shadowRoot) yield* walk(e.shadowRoot); } }"
        " for (const e of walk(document)){ const t=(e.innerText||e.value||'').trim();"
        " if (t===want){ const b=e.getBoundingClientRect();"
        " if (b.width>0&&b.height>0) return [Math.round(b.left+b.width/2),"
        " Math.round(b.top+b.height/2)]; } } return null; }", text)


def _robot_center(page):
    return page.evaluate(r"""() => {
      const cs=[...document.querySelectorAll('div,img,button,a')].filter(e=>{
        const b=e.getBoundingClientRect();
        return b.width>=28&&b.width<=72&&b.height>=28&&b.height<=72
               && b.left>innerWidth-130 && b.top<200 && b.top>=40; });
      if(!cs.length) return null; const b=cs[0].getBoundingClientRect();
      return [Math.round(b.left+b.width/2), Math.round(b.top+b.height/2)]; }""")


# --- navigation ------------------------------------------------------------------
def _has_explore(page) -> bool:
    try:
        return page.locator(
            "xpath=//*[contains(normalize-space(.),'Explore Appstream AI') or "
            "contains(normalize-space(.),'Explore AppStream AI')]").count() > 0
    except Exception:  # noqa: BLE001
        return False


BATCH_PAGE = "616"     # Megan 2026-11-27, from Lucy's Chrome: index.cfm?rqst=<session>&p=616


def _session_token(page) -> str:
    import urllib.parse as _up
    try:
        q = _up.parse_qs(_up.urlparse(page.url or "").query)
        return (q.get("rqst") or [""])[0]
    except Exception:  # noqa: BLE001
        return ""


def open_batches_direct(page, signin=None):
    """PROCESS IN BATCHES IS p=616 OF THE CLASSIC CONSOLE, inside the session
    the walk is already in (Megan 2026-11-27 pasted the page's address from
    Lucy's Chrome: index.cfm?rqst=<session>&p=616). The walk's own page URL
    carries that session token, so go straight there -- no "Explore Appstream
    AI" button (not on the walk's pages: 11/27 test run), no bare console
    load (lands on Login). Returns the page, or None."""
    LAST_STEPS.clear()
    _step(page, "start")
    tok = _session_token(page)
    if not tok and signin is not None:
        ok = False
        try:
            ok = bool(signin(page))
        except Exception as e:  # noqa: BLE001
            _log("[batch] sign-in raised %s" % type(e).__name__)
        LAST_STEPS.append("signed in again" if ok else "sign-in failed")
        tok = _session_token(page) if ok else ""
    if not tok:
        _step(page, "no session token in the page address")
        return None
    url = "https://applicantstream.com/index.cfm?rqst=%s&p=%s" % (tok, BATCH_PAGE)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
    except Exception as e:  # noqa: BLE001
        _log("[batch] could not open p=%s: %s" % (BATCH_PAGE, type(e).__name__))
    for _ in range(20):
        try:
            if page.locator(TABLE).count() > 0:
                _step(page, "batch table")
                return page
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(1000)
    _step(page, "p=%s opened, no batch table" % BATCH_PAGE)
    # Keep the page if the Resume Helper robot is on it: the table id is the
    # v2 one and the classic page may name it differently.
    try:
        if _robot_center(page) is not None:
            LAST_STEPS.append("robot present")
            return page
    except Exception:  # noqa: BLE001
        pass
    return None


def open_batches(page, signin=None):
    """Console -> 'Explore Appstream AI' (v2) -> Applicants > Process Emails >
    Process in Batches. Returns the page the table is on, or None."""
    ctx = page.context
    LAST_STEPS.clear()
    # THE WAY A PERSON GETS THERE (Megan by hand on Raf's MacBook, 11/27: the
    # AppStream tab -> Explore Appstream AI -> Process in Batches -> robot ->
    # Start; one Indeed tick, 10 of 10 resumes read). Never a bare load of the
    # console URL first: that lands on Login and drops the session (11/25 and
    # 11/27 runs: "console @ Login"), and loading it again after signing in
    # dropped it again. Order: the button on the page we are on; if it is not
    # there, the console URL; if that is Login, the saved sign-in, and stay
    # on the page the sign-in leaves us on.
    _step(page, "start")
    if not _has_explore(page):
        try:
            page.goto(CONSOLE_URL, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(2500)
        except Exception as e:  # noqa: BLE001
            _log("[batch] could not open the console: %s" % type(e).__name__)
        try:
            on_login = "login" in (page.title() or "").lower()
        except Exception:  # noqa: BLE001
            on_login = False
        if on_login and signin is not None:
            ok = False
            try:
                ok = bool(signin(page))
            except Exception as e:  # noqa: BLE001
                _log("[batch] sign-in raised %s" % type(e).__name__)
            LAST_STEPS.append("signed in again" if ok else "sign-in failed")
            if not ok:
                return None
            page.wait_for_timeout(2500)
    _step(page, "console")
    before = len(ctx.pages)
    if _click_if_present(page, ["Explore Appstream AI", "Explore AppStream AI"],
                         timeout=10000):
        LAST_STEPS.append("clicked Explore Appstream AI")
        page.wait_for_timeout(3000)
        if len(ctx.pages) > before:
            page = ctx.pages[-1]
            try:
                page.wait_for_load_state("domcontentloaded", timeout=20000)
            except Exception:  # noqa: BLE001
                pass
    else:
        LAST_STEPS.append("no Explore Appstream AI button")
    _step(page, "before menu")
    try:
        page.locator("xpath=//*[normalize-space(.)='Applicants']").first.hover(timeout=8000)
        page.wait_for_timeout(600)
        page.locator("xpath=//*[normalize-space(.)='Process Emails']").first.hover(timeout=8000)
        page.wait_for_timeout(600)
    except Exception as e:  # noqa: BLE001
        _log("[batch] menu hover failed: %s" % type(e).__name__)
    if not _click_if_present(page, ["Process in Batches", "Process In Batches"],
                             timeout=10000):
        _step(page, "no Process in Batches link")
        _log("[batch] could not find 'Process in Batches'")
        return None
    for _ in range(20):
        if page.locator(TABLE).count() > 0:
            return page
        page.wait_for_timeout(1000)
    _log("[batch] Process in Batches opened but the table never rendered")
    return None


def table_counts(page) -> dict:
    """{'rows': all rows, 'ready': still Ready For Extraction}."""
    _main_world(page, f"(function(){{jQuery('{TABLE}').DataTable().page.len(1000).draw();return 1;}})()")
    page.wait_for_timeout(1500)
    rows = _int(_main_world(page, f"jQuery('{TABLE}').DataTable().page.info().recordsDisplay"))
    ready = _int(_main_world(
        page, f"document.querySelectorAll('{TABLE} tbody [title=\"Ready For Extraction\"]').length"))
    return {"rows": rows, "ready": ready}


def office_on_page(page, office: str) -> dict:
    """Does the batch page show THIS office? The v2 page has no Office ID
    banner we have proven yet, so the dry run records what it does show:
    every 5-digit number in the header area, and whether ours is among them."""
    try:
        text = page.evaluate("() => (document.body.innerText || '').slice(0, 4000)")
    except Exception:  # noqa: BLE001
        text = ""
    nums = sorted(set(re.findall(r"\b(\d{5})\b", text or "")))
    return {"ours_shown": str(office) in nums, "numbers": nums[:12],
            "head": " ".join((text or "").split())[:240]}


# --- the trial ---------------------------------------------------------------------
def _state_path() -> Path:
    from automations.icd_alerts import config as C
    return C.APP_DIR / "batch-push.json"


def _state() -> dict:
    try:
        return json.loads(_state_path().read_text())
    except Exception:  # noqa: BLE001
        return {}


def _save(st: dict) -> None:
    try:
        _state_path().write_text(json.dumps(st, indent=2))
    except Exception:  # noqa: BLE001
        pass


def switched_off_today(office: str, today: Optional[str] = None) -> bool:
    today = today or dt.date.today().isoformat()
    return _state().get("off_day", {}).get(str(office)) == today


def _note_block(office: str, blocked: bool) -> None:
    st = _state()
    streak = st.setdefault("block_streak", {})
    streak[office] = (int(streak.get(office) or 0) + 1) if blocked else 0
    if streak[office] >= OFF_AFTER_BLOCKS:
        st.setdefault("off_day", {})[office] = dt.date.today().isoformat()
        _log("[batch] Indeed blocked the batch %d runs in a row -- batch OFF "
             "for %s today; the one-at-a-time push carries on" % (streak[office], office))
    _save(st)


def _extract(page) -> str:
    """Resume Helper -> Start; wait for Reset or the cap. 'reset' | 'cap' | ''."""
    st = _shadow_find(page, "Start")
    if st is None:
        c = _robot_center(page)
        if c is None:
            _log("[batch] Resume Helper robot not on the page (extension not running?)")
            return ""
        page.mouse.click(c[0], c[1])
        page.wait_for_timeout(2500)
        st = _shadow_find(page, "Start")
    if st is None:
        _log("[batch] Resume Helper popup opened but 'Start' not found")
        return ""
    page.mouse.click(st[0], st[1])
    _log("[batch] Resume Helper -> Start")
    t0 = time.time()
    page.wait_for_timeout(5000)
    while time.time() - t0 < EXTRACT_CAP_S:
        if _shadow_find(page, "Reset") is not None:
            _log("[batch] extraction finished in %ds" % int(time.time() - t0))
            return "reset"
        page.wait_for_timeout(6000)
    stop = _shadow_find(page, "Stop")
    if stop is not None:
        page.mouse.click(stop[0], stop[1])
    _log("[batch] extraction stopped at the %ds cap" % EXTRACT_CAP_S)
    return "cap"


def _send_first(page, limit: int) -> Optional[int]:
    """Tick the first `limit` rows, Send To AI, confirm. 'Sent to Call List' N."""
    rows = page.locator(f"{TABLE} tbody tr")
    for i in range(min(limit, rows.count())):
        try:
            rows.nth(i).locator("input[type='checkbox']").first.check(timeout=4000)
        except Exception:  # noqa: BLE001
            pass
    picked = page.locator(f"{TABLE} tbody tr input[type='checkbox']:checked").count()
    if not picked:
        _log("[batch] no rows could be selected -- nothing sent")
        return 0
    if not _click_if_present(page, ["Send To AI", "Send to AI"], timeout=10000):
        _log("[batch] 'Send To AI' not found -- nothing sent")
        return 0
    dlg = page.locator(".modal:visible, .swal2-popup:visible, [role='dialog']:visible")
    for _ in range(120):
        if dlg.count():
            break
        page.wait_for_timeout(1000)
    if not dlg.count():
        _log("[batch] the status box never appeared -- not confirming blind")
        return None
    text = " ".join(dlg.first.inner_text().split())
    _log("[batch] status: %s" % text[:200])
    m = re.search(r"Sent to Call List[^0-9]*([0-9,]+)", text, re.I)
    _click_if_present(page, ["Yes", "Continue", "OK"])
    page.wait_for_timeout(2500)
    return int(m.group(1).replace(",", "")) if m else None


def run(page, office: str, profile_dir, live_allowed: bool, net=None,
        signin=None) -> dict:
    """One trial pass for `office`. Never raises. Leaves `page` alone; any v2
    tab it opened is closed again. Returns what it saw/did for the stats row."""
    office = str(office)
    mode = mode_for(office)
    out = {"mode": mode or "off", "ext": extension_installed(profile_dir)}
    if not mode:
        return out
    if switched_off_today(office):
        out["skipped"] = "switched off today after Indeed blocks"
        return out
    if not out["ext"]:
        _log("[batch] Resume Helper is not installed in Lucy's Chrome -- skipped")
        out["skipped"] = "extension not installed"
        return out
    ctx = page.context
    pages_before = list(ctx.pages)
    bpage = None
    try:
        bpage = (open_batches_direct(page, signin=signin)
                 or open_batches(page, signin=signin))
        if bpage is None:
            out["skipped"] = "Process in Batches not reached"
            out["steps"] = list(LAST_STEPS)[-6:]
            return out
        out.update(table_counts(bpage))
        out["office"] = office_on_page(bpage, office)
        _log("[batch] %s: %s rows, %s ready for extraction; office shown: %s %s"
             % (office, out.get("rows"), out.get("ready"),
                out["office"]["ours_shown"], out["office"]["numbers"]))
        if mode != "live" or not live_allowed:
            _log("[batch] DRY RUN -- no Start, no Send")
            return out
        if not out["office"]["ours_shown"]:
            _log("[batch] the batch page does not show office %s -- NOT sending" % office)
            out["skipped"] = "office not shown on the batch page"
            return out
        res = _extract(bpage)
        try:
            bpage.reload(wait_until="domcontentloaded")
            bpage.wait_for_timeout(3000)
        except Exception:  # noqa: BLE001
            pass
        after = table_counts(bpage)
        blocked = bool(net and (net.get("indeed_403") or net.get("turnstile")))
        blocked = blocked or (res == "cap" and (after.get("ready") or 0)
                              >= (out.get("ready") or 0) > 0)
        out["extract"] = res
        out["ready_after"] = after.get("ready")
        out["blocked"] = blocked
        _note_block(office, blocked)
        out["sent"] = _send_first(bpage, BATCH_LIMIT) or 0
        _log("[batch] LIVE: %s sent to AI from the batch" % out["sent"])
        return out
    except Exception as e:  # noqa: BLE001 -- the trial never costs the walk
        _log("[batch] trial pass failed: %s: %s" % (type(e).__name__, str(e)[:160]))
        out["error"] = type(e).__name__
        return out
    finally:
        for p in list(ctx.pages):
            if p not in pages_before:
                try:
                    p.close()
                except Exception:  # noqa: BLE001
                    pass
