"""Edit office 11580's "Await Call AI" SMS template so its interview-time
clause matches the clock (Carlos 2026-10-28). await_window.await_clause says
WHAT it should say; this module drives the AppStream UI to make it so, along
Carlos's own route: SMS/Email (top-left) -> SMS Templates -> Await Call AI ->
Edit (next to Activated) -> fix the "Are you available ... ?" box -> save.

Run `applicant_push --office 11580 --await-probe` to dump what the pages hold
(no edit), `--await-apply` to do one live update and stop. The push pass calls
ensure_await_template(page) before walking; failures are logged, never raised
— a stale clause must not stop the push itself.
"""

import datetime as dt
import re

from automations.oat_processing.await_window import (WINDOWS_BY_OFFICE,
                                                     await_clause)

_T = r"[0-9]{1,2}:[0-9]{2}\s*(?:am|pm)?"
CLAUSE_RE = re.compile(
    r"available\s+(?:today|tomorrow)\s+(?:at|between)\s+" + _T +
    r"(?:\s*[-\u2013]\s*" + _T + r")?"
    r"(?:\s*(?:,?\s*or)\s+" + _T + r"(?:\s*[-\u2013]\s*" + _T + r")?)?",
    re.I)
# Every office whose interview windows are on file (await_window.WINDOWS_BY_
# OFFICE). Megan 2026-10-28: all resume pushing, not only Carlos's.
OFFICES = set(WINDOWS_BY_OFFICE)
_SAID_NO_WINDOWS: set = set()

_log = print


def set_logger(fn) -> None:
    global _log
    _log = fn


def _click_text(page, pattern: str, hover_first: str = "") -> bool:
    """Click the first link/button whose text matches `pattern` (regex, any
    frame). Optionally hover a menu label first to reveal a dropdown."""
    for fr in page.frames:
        try:
            if hover_first:
                h = fr.locator(
                    "xpath=//a[contains(normalize-space(.),'%s')] "
                    "| //*[@role='button'][contains(normalize-space(.),'%s')]"
                    % (hover_first, hover_first)).first
                if h.count():
                    h.hover(timeout=4000)
                    fr.page.wait_for_timeout(600)
            loc = fr.locator("a, button, input[type=submit], [role=menuitem]")
            n = min(loc.count(), 400)
            for i in range(n):
                el = loc.nth(i)
                try:
                    t = (el.inner_text(timeout=300) or
                         el.get_attribute("value") or "").strip()
                except Exception:  # noqa: BLE001
                    continue
                if t and re.search(pattern, t, re.I):
                    el.click(timeout=6000)
                    page.wait_for_timeout(2000)
                    return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _goto_templates(page) -> bool:
    """Land on the SMS Templates list. Menu route first, with one retry."""
    for _ in range(2):
        _click_text(page, r"^SMS\s*Templates$", hover_first="SMS/Email")
        if _page_has(page, r"Await"):
            return True
        # some skins need the menu itself clicked before the submenu exists
        _click_text(page, r"SMS\s*/?\s*Email")
        page.wait_for_timeout(1200)
        if _click_text(page, r"SMS\s*Templates"):
            if _page_has(page, r"Await"):
                return True
    return _page_has(page, r"Await")


def _page_has(page, pattern: str) -> bool:
    for fr in page.frames:
        try:
            if re.search(pattern, fr.inner_text("body", timeout=2000) or "", re.I):
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _open_await_edit(page) -> bool:
    """From the templates list, click the Edit control on the Await row."""
    for fr in page.frames:
        try:
            row = fr.locator(
                "xpath=//tr[contains(translate(normalize-space(.),"
                "'AWITCL','awitcl'),'await call ai')]").first
            if row.count():
                ed = row.locator(
                    "xpath=.//a[contains(translate(.,'EDIT','edit'),'edit')] "
                    "| .//input[contains(translate(@value,'EDIT','edit'),'edit')] "
                    "| .//img[contains(translate(@alt,'EDIT','edit'),'edit')]"
                ).first
                if ed.count():
                    ed.click(timeout=6000)
                    page.wait_for_timeout(2500)
                    return True
        except Exception:  # noqa: BLE001
            continue
    # fallback: any Edit control near the word Await anywhere
    return _click_text(page, r"^Edit$")


def _fields(page):
    """Every visible input/textarea on the edit form: (frame, locator, value)."""
    out = []
    for fr in page.frames:
        try:
            loc = fr.locator("textarea, input[type=text]")
            for i in range(min(loc.count(), 60)):
                el = loc.nth(i)
                try:
                    v = el.input_value(timeout=400)
                except Exception:  # noqa: BLE001
                    continue
                out.append((fr, el, v or ""))
        except Exception:  # noqa: BLE001
            continue
    return out


def probe(page) -> None:
    """No edits: walk the route and print what each step shows."""
    _log("[await-probe] going to SMS Templates…")
    ok = _goto_templates(page)
    _log("[await-probe] templates page reached: %s | url=%s" % (ok, page.url[:90]))
    for fr in page.frames:
        try:
            t = fr.inner_text("body", timeout=2000) or ""
        except Exception:  # noqa: BLE001
            continue
        for line in t.splitlines():
            if re.search(r"await|template|activat", line, re.I):
                _log("[await-probe] text: %r" % line.strip()[:120])
    if not _open_await_edit(page):
        _log("[await-probe] could NOT open the Await edit form")
        return
    _log("[await-probe] edit form open | url=%s" % page.url[:90])
    for _fr, el, v in _fields(page):
        try:
            name = el.get_attribute("name") or el.get_attribute("id") or "?"
        except Exception:  # noqa: BLE001
            name = "?"
        _log("[await-probe] field %-24s = %r" % (name, v[:160]))
    for fr in page.frames:
        try:
            loc = fr.locator("button, input[type=submit], input[type=button], a")
            for i in range(min(loc.count(), 200)):
                el = loc.nth(i)
                try:
                    t = (el.inner_text(timeout=200) or
                         el.get_attribute("value") or "").strip()
                except Exception:  # noqa: BLE001
                    continue
                if t and re.search(r"save|update|submit|apply|done", t, re.I):
                    _log("[await-probe] control: %r (tag=%s)"
                         % (t[:60], el.evaluate("e=>e.tagName")))
        except Exception:  # noqa: BLE001
            continue


def ensure_await_template(page, office_id: str, apply: bool = True) -> bool:
    """Make the Await template's clause match the clock. True = verified
    correct (updated, or already right). Never raises."""
    if office_id not in WINDOWS_BY_OFFICE:
        if office_id and office_id not in _SAID_NO_WINDOWS:
            _SAID_NO_WINDOWS.add(office_id)
            _log("[await] no interview windows on file for office %s — "
                 "template left as-is (add them to await_window."
                 "WINDOWS_BY_OFFICE)" % office_id)
        return True
    try:
        want = await_clause(dt.datetime.now(), WINDOWS_BY_OFFICE[office_id])
        if not _goto_templates(page):
            _log("[await] SMS Templates page not reached — leaving template")
            return False
        if not _open_await_edit(page):
            _log("[await] Await edit form not reached — leaving template")
            return False
        hit = None
        for fr, el, v in _fields(page):
            if CLAUSE_RE.search(v):
                hit = (fr, el, v)
                break
        if hit is None:
            _log("[await] no field carries an 'available … ?' clause — "
                 "nothing edited (probe the form)")
            return False
        fr, el, v = hit
        new = CLAUSE_RE.sub(want, v, count=1)
        if new == v:
            _log("[await] clause already current: %s" % want)
            return True
        if not apply:
            _log("[await] WOULD set: %r" % new[:200])
            return True
        el.fill(new)
        page.wait_for_timeout(400)
        # Carlos, live 2026-10-28: the button is "Save and Activate SMS
        # Message" — it saves AND keeps the template activated.
        saved = _click_text(page, r"^Save and Activate SMS Message$")
        if not saved:
            saved = _click_text(page, r"^Save SMS Message$")
        page.wait_for_timeout(2000)
        _log("[await] clause set -> %s (save clicked: %s)" % (want, saved))
        return saved
    except Exception as e:  # noqa: BLE001
        _log("[await] failed, leaving template as-is: %s: %s"
             % (type(e).__name__, str(e)[:120]))
        return False
