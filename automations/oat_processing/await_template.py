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

from automations.oat_processing.await_window import (DAYS, WINDOWS_BY_OFFICE,
                                                     await_clause,
                                                     clause_from_schedule,
                                                     parse_span)

_T = r"[0-9]{1,2}:[0-9]{2}\s*(?:am|pm)?"
# "TODAY, Wednesday" (Megan 10/28) -- and the bare weekday for 2+ days out.
_WD = r"(?:sunday|monday|tuesday|wednesday|thursday|friday|saturday)"
# The day word: what we write (TODAY / TOMORROW / a weekday) or AppStream's own
# fill-in "currentInterviewDay" (24065: "Are you available currentInterviewDay
# 12:45 pm - 3:45 pm for a quick ZOOM…"). "at/between" optional for the same
# reason.
CLAUSE_RE = re.compile(
    r"available\s+(?:(?:today|tomorrow)(?:\s*,?\s*" + _WD + r")?|" + _WD +
    r"|currentInterviewDay)\s+(?:(?:at|between)\s+)?" + _T +
    r"(?:\s*[-\u2013]\s*" + _T + r")?"
    r"(?:\s*(?:,?\s*or|/)\s*" + _T + r"(?:\s*[-\u2013]\s*" + _T + r")?)?",
    re.I)
# A template that asks with no time at all (23965 10/28: "…a quick 20-minute
# Zoom Interview. Are you available?"). For the chosen offices the clause goes
# in right there, and from then on CLAUSE_RE finds and updates it.
BARE_ASK_RE = re.compile(r"Are you available\?")
# THE STANDARD TEXT for Raf's 23965 + 24065 (Megan 2026-10-28: "we want it to
# mimic this" -- Jacob's 23607 Await Call AI, sent 132x). Both boxes are set to
# it; only the day + times in box 2 change from run to run. The one change from
# Jacob's: a space after "applicantFirstName,".
STANDARD_OFFICES = {"23965", "24065"}
STANDARD_BODY1 = ("Hi applicantFirstName, We reviewed your application for the "
                  "adPostingTitle role on Indeed / Full time and On site and "
                  "would like to schedule a brief 20 minute Zoom interview to "
                  "discuss your experience and the position.")
STANDARD_BODY2 = "Are you %s for a quick ZOOM to go over the position?"
# WHICH OFFICES' Await text is retuned. Only these -- every other office's
# template is never opened (Megan 2026-10-28: "just apply it to accounts 24065
# and 23965 for raf"; Raf's main 11280, Atef and Khalil stay as they are).
# 11580 uses Carlos's stated windows; the rest read their own AppStream
# schedule (Settings > Office Level Settings).
OFFICES = {"11580", "23965", "24065"}
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


# --- the office's own schedule (Megan 2026-10-28) ---------------------------
# Settings > Office Level Settings: "Current Active Interview Slots" (a row per
# slot, a column per weekday, "8:00 AM - 4:00 PM") and "Calendar Time
# Increment". Read once a day per office and kept, so a push pass does not
# reopen Settings every 10 minutes.
_SCHED_JS = r"""() => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const days = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
  const out = {slots: {}, step: null, source: ''};
  // 1) The ExtJS page (seen live 10/28 on 23965 + 24065): tabs "1st Interview",
  //    "2nd Interview", "3rd Interview", "FDOT / BOB", one grid + one
  //    increment radio set per tab. The Await text is the 1st-round invite.
  const tabs = [...document.querySelectorAll('.x-tab-strip-text')].map(t => norm(t.textContent));
  const panels = [...document.querySelectorAll('.x-tab-panel-body > .x-panel')];
  let pi = tabs.findIndex(t => /^1st\s*Interview$/i.test(t));
  if (pi < 0 && panels.length) pi = 0;
  if (pi >= 0 && panels[pi]) {
    const p = panels[pi];
    const g = p.querySelector('.x-grid3');
    if (g) {
      const heads = [...g.querySelectorAll('.x-grid3-header td.x-grid3-hd')].map(td => norm(td.innerText));
      for (const r of g.querySelectorAll('.x-grid3-body .x-grid3-row')) {
        [...r.querySelectorAll('td.x-grid3-cell')].forEach((td, i) => {
          const d = heads[i], v = norm(td.innerText);
          if (days.includes(d) && v) (out.slots[d] = out.slots[d] || []).push(v);
        });
      }
      const rad = [...p.querySelectorAll('input[type=radio]')].find(e => e.checked);
      if (rad && /^\d+$/.test(rad.value || '')) out.step = parseInt(rad.value);
      out.source = 'tab:' + (tabs[pi] || '?');
    }
  }
  if (Object.keys(out.slots).length && out.step) return out;
  // 2) A plain HTML table, as a fallback.
  for (const t of document.querySelectorAll('table')) {
    const rows = [...t.rows];
    const hi = rows.findIndex(r => [...r.cells].some(c => norm(c.innerText) === 'Sunday')
                                 && [...r.cells].some(c => norm(c.innerText) === 'Monday'));
    if (hi < 0) continue;
    const head = [...rows[hi].cells].map(c => norm(c.innerText));
    for (const r of rows.slice(hi + 1)) {
      [...r.cells].forEach((c, i) => {
        const d = head[i]; const v = norm(c.innerText);
        if (days.includes(d) && v) (out.slots[d] = out.slots[d] || []).push(v);
      });
    }
    out.source = 'table';
    break;
  }
  if (!out.step) {
    for (const e of document.querySelectorAll('input[type=radio]:checked')) {
      if (/^\d+$/.test(e.value || '')) { out.step = parseInt(e.value); break; }
    }
  }
  return out;
}"""

_HDR_TIME = re.compile(r"Time:\s*([A-Za-z]{3,9}),?\s*(\d{1,2})\s+(\d{1,2}):(\d{2})\s*(AM|PM)", re.I)


def office_now(page):
    """The office's own clock off AppStream's header ('Time: Oct, 28 02:16 PM
    - Central …'), so an office in another time zone gets its own hours.
    Falls back to this computer's clock."""
    now = dt.datetime.now()
    for fr in page.frames:
        try:
            m = _HDR_TIME.search(fr.inner_text("body", timeout=2000) or "")
        except Exception:  # noqa: BLE001
            continue
        if m:
            try:
                mon = dt.datetime.strptime(m.group(1)[:3], "%b").month
                h = int(m.group(3)) % 12 + (12 if m.group(5).upper() == "PM" else 0)
                year = now.year + (1 if (mon == 1 and now.month == 12) else 0)
                return dt.datetime(year, mon, int(m.group(2)), h, int(m.group(4)))
            except Exception:  # noqa: BLE001
                pass
    return now


def _sched_path(office_id: str):
    import os
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    os.makedirs(os.path.join(root, "output"), exist_ok=True)
    # "-v2": the 10/28 afternoon reader (ExtJS 1st Interview tab). A copy
    # saved by the first reader may hold the wrong grid, so it is not reused.
    return os.path.join(root, "output", "await-schedule-v2-%s-%s.json"
                        % (office_id, dt.date.today().isoformat()))


def read_office_schedule(page, office_id: str):
    """({weekday: [(start, end)]}, step) from Settings > Office Level
    Settings, or (None, None). Cached for the day."""
    import json
    import os
    path = _sched_path(office_id)
    if os.path.exists(path):
        try:
            d = json.load(open(path))
            return ({k: [tuple(x) for x in v] for k, v in d["slots"].items()},
                    d["step"])
        except Exception:  # noqa: BLE001
            pass
    got = None
    for label in (r"^Office Level Settings$", r"^Self-Schedule Setup$"):
        _click_text(page, label, hover_first="Settings")
        for fr in page.frames:
            try:
                raw = fr.evaluate(_SCHED_JS) or {}
            except Exception:  # noqa: BLE001
                continue
            if raw.get("slots"):
                got = raw
                break
        if got:
            break
    if not got:
        _log("[await] office %s: no 'Current Active Interview Slots' found "
             "in Settings" % office_id)
        return None, None
    slots = {}
    for d, cells in got["slots"].items():
        spans = [sp for sp in (parse_span(c) for c in cells) if sp]
        if spans:
            slots[d] = spans
    step = int(got.get("step") or 0) or None
    if not slots or not step:
        _log("[await] office %s: schedule unreadable (slots=%s step=%s)"
             % (office_id, bool(slots), step))
        return None, None
    try:
        json.dump({"slots": slots, "step": step}, open(path, "w"))
    except Exception:  # noqa: BLE001
        pass
    _log("[await] office %s schedule: %s, every %d min" % (
        office_id, "; ".join("%s %s" % (d[:3], ",".join(
            "%d:%02d-%d:%02d" % (a // 60, a % 60, b // 60, b % 60) for a, b in slots[d]))
            for d in DAYS if d in slots), step))
    return slots, step


def _named_field(page, name: str):
    for fr in page.frames:
        try:
            loc = fr.locator("textarea[name='%s'], input[name='%s']"
                             % (name, name)).first
            if loc.count():
                return loc
        except Exception:  # noqa: BLE001
            continue
    return None


def _set_standard(page, office_id: str, want: str, apply: bool) -> bool:
    """Both boxes to the standard text (box 1 fixed, box 2 with `want`)."""
    b1, b2 = _named_field(page, "smsBody"), _named_field(page, "smsBody2")
    if b1 is None or b2 is None:
        _log("[await] office %s: the two message boxes (smsBody/smsBody2) "
             "were not found — template left as-is" % office_id)
        return False
    new2 = STANDARD_BODY2 % want
    if len(new2) > 160:
        _log("[await] office %s: %d characters is over the 160 box -- left "
             "as-is: %r" % (office_id, len(new2), new2))
        return False
    try:
        cur1, cur2 = b1.input_value(timeout=1500), b2.input_value(timeout=1500)
    except Exception:  # noqa: BLE001
        cur1 = cur2 = None
    if cur1 == STANDARD_BODY1 and cur2 == new2:
        _log("[await] office %s: already current: %s" % (office_id, want))
        return True
    if not apply:
        _log("[await] office %s WOULD set: %r | %r"
             % (office_id, STANDARD_BODY1[:60], new2))
        return True
    b1.fill(STANDARD_BODY1)
    b2.fill(new2)
    page.wait_for_timeout(400)
    saved = (_click_text(page, r"^Save and Activate SMS Message$")
             or _click_text(page, r"^Save SMS Message$"))
    page.wait_for_timeout(2000)
    _log("[await] office %s set -> %s (save clicked: %s)"
         % (office_id, new2, saved))
    return saved


def ensure_await_template(page, office_id: str, apply: bool = True) -> bool:
    """Make the Await template's clause match the clock. True = verified
    correct (updated, or already right). Never raises."""
    if office_id not in OFFICES:
        return True
    try:
        if office_id in WINDOWS_BY_OFFICE:
            # Carlos's own stated windows (10/28) win for his office.
            want = await_clause(office_now(page), WINDOWS_BY_OFFICE[office_id])
        else:
            # Everyone else: their own AppStream schedule (Megan 10/28).
            slots, step = read_office_schedule(page, office_id)
            if not slots:
                return False
            want = clause_from_schedule(office_now(page), slots, step)
            if not want:
                _log("[await] office %s: no interview slots any day — "
                     "template left as-is" % office_id)
                return False
        if not _goto_templates(page):
            _log("[await] SMS Templates page not reached — leaving template")
            return False
        if not _open_await_edit(page):
            _log("[await] Await edit form not reached — leaving template")
            return False
        if office_id in STANDARD_OFFICES:
            return _set_standard(page, office_id, want, apply)
        hit = None
        fields = _fields(page)
        for fr, el, v in fields:
            if CLAUSE_RE.search(v):
                hit = (fr, el, v)
                break
        bare = None
        if hit is None:
            for fr, el, v in fields:
                if BARE_ASK_RE.search(v):
                    bare = (fr, el, v)
                    break
        if hit is None and bare is not None:
            fr, el, v = bare
            new = BARE_ASK_RE.sub("Are you %s?" % want, v, count=1)
            if not apply:
                _log("[await] WOULD set: %r" % new[:220])
                return True
            el.fill(new)
            page.wait_for_timeout(400)
            saved = (_click_text(page, r"^Save and Activate SMS Message$")
                     or _click_text(page, r"^Save SMS Message$"))
            page.wait_for_timeout(2000)
            _log("[await] office %s: times added to 'Are you available?' -> "
                 "%s (save clicked: %s)" % (office_id, want, saved))
            return saved
        if hit is None:
            # A different wording (Raf's 11280 lists each time: "Available
            # Zoom times are today at 8:15, 8:45 …"). Applicant-facing copy is
            # not rewritten into a new shape without Megan's OK -- say what
            # it says, once a day, and leave it.
            if office_id not in _SAID_NO_WINDOWS:
                _SAID_NO_WINDOWS.add(office_id)
                texts = [v for _f, _e, v in _fields(page)
                         if re.search(r"\d{1,2}:\d{2}", v)]
                _log("[await] office %s: wording not recognized, left as-is "
                     "(would set %r). Current text: %r"
                     % (office_id, want, (texts[0] if texts else "")[:220]))
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
