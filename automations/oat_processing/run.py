#!/usr/bin/env python3
"""OAT Processing — automate the "One App at a time" leftovers queue.

Runs on Lucy 2 (Carlos's account / office 11580). Rides the SAME holder-warmed
patchright session resume_pushing uses (`appstream_direct_session` — seeded from
the exported ownerville session, so NO service-account key and NO Cloudflare
login form), switches to office 11580 via `fetch_office._switch_office`, then
walks the classic OAT queue under Applicants -> Process Emails -> One App at a
time, classifying each applicant (see classify.py) and carrying out the action.

(The classic `applicant_tracker` driver was the first cut, but its
service-account-reads-creds-from-a-Sheet path is a Lucy-1 thing — that key is
deliberately absent on Lucy 2. The AppStream session is already warm here.)

SAFETY MODEL
------------
This report SENDS REAL TEXTS/EMAILS to applicants and REMOVES records — both
are outward, effectively irreversible actions. So, unlike most reports:

  * DRY-RUN IS THE DEFAULT. Without --live the run reads the queue, classifies
    every applicant, and prints exactly what it WOULD do — it never clicks a
    send/remove/override control.
  * --live is required to actually act, and only after Megan/Carlos confirm the
    dry-run output looks right.

FLAGS
  (default)   Dry-run: read + classify + print planned actions. No clicks.
  --live      Actually perform the send/remove/override clicks.
  --limit N   Process at most N applicants this run (default config.MAX_PER_RUN).
  --debug     Land on the OAT page, print a health check (which controls/labels
              are visible), then STOP. Run this FIRST on Lucy 2 to capture the
              selectors the stubbed helpers below still need.
  --headed    Force a visible browser (overrides HEADLESS).

STATUS: the page-READING (read_current_applicant, advance_to_next) and page-
ACTING (do_*) helpers below are marked `# >>> VERIFY on Lucy 2` where the
classic OAT DOM hasn't been confirmed yet. The decision core (classify.py) and
the no-phone flagging are complete and tested. Run `--debug` on Lucy 2 to fill
the remaining selectors.
"""
from __future__ import annotations  # Lucy 2 / mini run Python 3.9

import argparse
import csv
import datetime as dt
import re
import os
import sys

from automations.shared.tableau_patchright import (
    appstream_direct_session, AppStreamBusy)
from automations.recruiting_report import fetch_office

from . import config
from .classify import Applicant, Action, Decision, classify


def _log(msg: str) -> None:
    print(msg, flush=True)


# --------------------------------------------------------------------------- #
# Navigation to the classic OAT screen
# --------------------------------------------------------------------------- #
def open_oat(page) -> bool:
    """Applicants -> Process Emails -> "One App at a time" (classic surface).

    Text/label-based (no hardcoded p= page number): open the "Applicants" top-nav
    (its Process Emails submenu holds the link), then click "One App at a time".
    Returns True if we landed on it.
    # >>> VERIFY on Lucy 2: confirm the nav labels + that this is the right page.
    """
    # 1) reveal the Applicants menu (hover, then click as fallback).
    for how in ("hover", "click"):
        try:
            loc = page.locator(
                "xpath=//a[normalize-space(.)='Applicants'] "
                "| //*[self::button or @role='button'][normalize-space(.)='Applicants']"
            ).first
            if loc.count() == 0:
                break
            getattr(loc, how)(timeout=5000)
            page.wait_for_timeout(800)
        except Exception:  # noqa: BLE001
            pass
    # 2) click the OAT link (a/link/menu item), tolerating minor label variants.
    oat_xp = ("xpath=//a[contains(normalize-space(.),'One App at a time')] "
              "| //*[@role='menuitem'][contains(normalize-space(.),'One App at a time')] "
              "| //a[contains(normalize-space(.),'One App at a Time')]")
    try:
        page.locator(oat_xp).first.click(timeout=8000)
        page.wait_for_timeout(1500)
        if "p=604" in (page.url or ""):
            return True
    except Exception as e:  # noqa: BLE001
        _log(f"[oat] menu click missed ({type(e).__name__}); trying direct nav")

    # Fallback: the OAT page is index.cfm?p=604 (confirmed 2026-07-27). Navigate
    # straight there, reusing the session's rqst token from the current URL.
    import re
    m = re.search(r"rqst=([A-F0-9-]+)", page.url or "", re.I)
    if not m:
        _log("[oat] no rqst token in URL — cannot direct-nav to p=604")
        return False
    page.goto(f"https://applicantstream.com/index.cfm?p=604&rqst={m.group(1)}",
              wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    return "p=604" in (page.url or "")


# --------------------------------------------------------------------------- #
# Reading one applicant off the OAT screen  # >>> VERIFY on Lucy 2
# --------------------------------------------------------------------------- #
# One text-based extraction of every signal off the OAT panel (p=604). Text-based
# (find the dup table by its "Status"/"Duplicate Type" header; search body text for
# the red-message patterns) because the model was built from the Loom's pixels, not
# the DOM — so it's robust to exact ids. See FINDINGS.md for the state model.
_EXTRACT_JS = r"""() => {
  const val = n => { const e=document.querySelector(`[name='${n}']`);
    if(!e) return '';
    // for a <select>, return the visible option text, not the numeric value
    if(e.tagName==='SELECT') return (e.options[e.selectedIndex]?.text||'').trim();
    return (e.value||'').trim(); };
  const body = (document.body.innerText||'');
  // --- the duplicate table: header row has both "Status" and "Duplicate Type" ---
  let dupRows = [];
  for (const t of document.querySelectorAll('table')) {
    const head = (t.querySelector('tr')?.innerText||'').toLowerCase();
    if (head.includes('status') && head.includes('duplicate type')) {
      const trs=[...t.querySelectorAll('tr')];
      const cols=[...trs[0].children].map(c=>c.innerText.trim().toLowerCase());
      const ci=name=>cols.findIndex(c=>c.includes(name));
      const iStatus=ci('status'), iType=ci('duplicate type'),
            iDate=ci('date entered'), iApp=ci('applicant');
      for (let i=1;i<trs.length;i++){ const td=[...trs[i].children];
        if(!td.length) continue;
        dupRows.push({
          applicant: iApp>=0 ? (td[iApp]?.innerText||'').trim() : '',
          dateEntered: iDate>=0 ? (td[iDate]?.innerText||'').trim() : '',
          status: iStatus>=0 ? (td[iStatus]?.innerText||'').trim() : '',
          dupType: iType>=0 ? (td[iType]?.innerText||'').trim() : '',
        });
      }
      break;
    }
  }
  // --- red inline messages ---
  const cannotOverride = /cannot override this applicant/i.test(body);
  const corrM = body.match(/last correspondence was on\s+([0-9]{1,2}\/[0-9]{1,2}\/[0-9]{2,4})/i);
  // --- overwrite+send button present? ---
  const btnText = [...document.querySelectorAll('button,input[type=button],input[type=submit],a')]
    .map(e=>(e.innerText||e.value||'')).join(' | ').toLowerCase();
  const overrideBtn = btnText.includes('overwrite') && btnText.includes('send to ai');
  // --- pager: "<page> of <N> Emails" ---
  const pm = body.match(/of\s+([0-9]+)\s+emails/i);
  return {
    fname: val('fname'), lname: val('lname'), phone: val('phone'),
    cellPhone: val('cellPhone'), email: val('email'), jBoard: val('jBoard'),
    subject: val('emailApplicantSubject'),
    dupRows, cannotOverride, lastCorrespondence: corrM ? corrM[1] : '',
    overrideBtn, total: pm ? parseInt(pm[1],10) : null,
  };
}"""


def _parse_us_date(s: str):
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return dt.datetime.strptime(s.strip(), fmt).date()
        except Exception:  # noqa: BLE001
            continue
    # "Thursday, July 23, 2026 02:23 PM" style (dup-table Date Entered)
    for fmt in ("%A, %B %d, %Y", "%B %d, %Y"):
        try:
            return dt.datetime.strptime(s.split(" 0")[0].strip().rstrip(","), fmt).date()
        except Exception:  # noqa: BLE001
            continue
    try:
        return dt.datetime.strptime(s.strip().split(",")[1].strip() + s.strip().split(",")[2].split()[0],
                                    "%B %d %Y").date()
    except Exception:  # noqa: BLE001
        return None


def read_current_applicant(page, today: dt.date = None) -> Applicant:
    """Read the applicant panel (p=604) + duplicate table + red messages into an
    Applicant, deriving the state signals classify() needs. See FINDINGS.md."""
    today = today or dt.date.today()
    try:
        d = page.evaluate(_EXTRACT_JS)
    except Exception as e:  # noqa: BLE001
        _log(f"[oat] extract failed: {type(e).__name__}: {e}")
        d = {}

    dup_rows = d.get("dupRows") or []
    statuses = " || ".join(r.get("status", "") for r in dup_rows)

    # interview signals from the dup-table Status column
    interview_future = False
    interview_past_noshow = False
    for r in dup_rows:
        st = (r.get("status") or "").lower()
        if "interview assigned" in st or "interview" in st:
            if "unmarked show" in st or "no show" in st or "no-show" in st:
                interview_past_noshow = True
            else:
                # a future/scheduled interview shows a date; treat any non-no-show
                # "interview assigned" as an active (future) booking.
                interview_future = True

    # sent-to-call-list-today: a dup row "Sent to Call List" dated today
    sent_today = False
    for r in dup_rows:
        if "sent to call list" in (r.get("status") or "").lower():
            de = _parse_us_date(r.get("dateEntered") or "")
            if de == today:
                sent_today = True

    last_corr = _parse_us_date(d.get("lastCorrespondence") or "") if d.get("lastCorrespondence") else None

    a = Applicant(
        first_name=d.get("fname", ""), last_name=d.get("lname", ""),
        phone=d.get("phone", ""), cell_phone=d.get("cellPhone", ""),
        email=d.get("email", ""), job_board=d.get("jBoard", ""),
        position=(d.get("subject", "") or "").strip(),
        override_button=bool(d.get("overrideBtn")),
        correspondence_blocked=bool(d.get("cannotOverride")),
        last_correspondence=last_corr,
        interview_future=interview_future,
        interview_past_noshow=interview_past_noshow,
        sent_to_call_list_today=sent_today,
        raw_status=statuses[:300],
    )
    a._total = d.get("total")  # type: ignore[attr-defined]  # queue size, for advance
    return a


def advance_to_next(page) -> bool:
    """Advance the OAT pager ("<page> of <N> Emails", top-right of the dup area)
    to the next applicant. Returns False when there's no next control (end of
    queue). # >>> VERIFY on Lucy 2: confirm the next-arrow locator."""
    # The pager Next control is an <img alt="Next"> (confirmed 2026-07-27). Click
    # the image itself (its click handler is jQuery-bound, no inline onclick).
    candidates = [
        "xpath=//img[translate(@alt,'NEXT','next')='next']",
        "xpath=//img[contains(translate(@alt,'NEXT','next'),'next')]",
        "xpath=//img[contains(translate(@alt,'NEXT','next'),'next')]/ancestor::a[1]",
        "xpath=//a[normalize-space(.)='►' or normalize-space(.)='>']",
    ]
    for xp in candidates:
        try:
            loc = page.locator(xp).first
            if loc.count() == 0:
                continue
            loc.click(timeout=5000, no_wait_after=True)
            page.wait_for_timeout(1800)
            return True
        except Exception:  # noqa: BLE001
            continue
    _log("[oat] no next-pager control found — treating as end of queue")
    return False


# --------------------------------------------------------------------------- #
# Actions  (all clicks are # >>> VERIFY on Lucy 2 and gated behind --live)
# --------------------------------------------------------------------------- #
def _would(live: bool, what: str) -> None:
    _log(f"    {'[LIVE] ' if live else '[dry-run] would '}{what}")


# Confirmed OAT controls (Lucy 2 --debug, 2026-07-27), for when these get armed:
#   "Send to AI" button · removApp checkbox + rmvReason <select> (pick the option
#   whose text contains "duplicate") + "Save Applicant" (submitSaveApplicant) ·
#   "Email Applicant" button + emailApplicantSubject / emailApplicantMessage
#   (textarea) + qNotes Quick-Note <select>. What's NOT yet observed: the
#   overwrite/duplicate confirm DIALOG that appears when you Send to AI on a dup,
#   the "Interview Assigned" status line, and how the page ADVANCES to the next
#   applicant. So the clicks stay gated until those states are seen live.
def _click_first(page, labels, timeout: int = 6000) -> bool:
    """Click the first visible button/link/submit whose text (or value) contains
    one of `labels`. Returns True if something was clicked."""
    for label in labels:
        loc = page.locator(
            f"xpath=//button[contains(normalize-space(.),'{label}')]"
            f" | //a[contains(normalize-space(.),'{label}')]"
            f" | //input[@type='submit' or @type='button'][contains(@value,'{label}')]"
            f" | //*[@role='button'][contains(normalize-space(.),'{label}')]")
        try:
            if loc.count() > 0:
                loc.first.click(timeout=timeout, no_wait_after=True)
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _has_dup_signal(x: Applicant) -> bool:
    return bool(x.override_button or x.correspondence_blocked or x.interview_future
                or x.interview_past_noshow or x.sent_to_call_list_today)


def _body(page) -> str:
    try:
        return (page.inner_text("body") or "").lower()
    except Exception:  # noqa: BLE001
        return ""


def _parse_last_corr(body: str):
    m = re.search(r"last correspondence was on\s+([0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4})",
                  body)
    return _parse_us_date(m.group(1)) if m else None


def _perform_remove(page) -> bool:
    """Remove-for-duplicate (Carlos's flow, confirmed by Megan 2026-07-27): check
    'Remove Applicant?' (removApp) + set the Remove Reason to the '…Duplicate…'
    option + click 'Save Applicant' (submitSaveApplicant). Done in ONE in-page
    step so it isn't tripped up by the post-block panel's actionability quirks.
    Fails safe (returns False, logs why) if the Duplicate reason or Save button
    isn't found."""
    try:
        # 1) CHECK "Remove Applicant?" — a real check so the ATS reveals the Remove
        #    Reason dropdown + the "Remove Applicant" button (Megan 7/27).
        cb = page.locator("[name='removApp']").first
        if cb.count() == 0:
            _log("    [remove] FAIL: no 'Remove Applicant?' checkbox")
            return False
        try:
            cb.check(timeout=4000)
        except Exception:  # noqa: BLE001
            cb.click(force=True, timeout=4000)
        page.wait_for_timeout(700)
        # 2) pick the '…Duplicate…' remove reason.
        picked = page.evaluate(r"""() => {
            const s = document.querySelector("select[name='rmvReason']");
            if (!s) return '';
            const o = [...s.options].find(o => /duplicate/i.test(o.text));
            if (!o) return '';
            s.value = o.value; s.dispatchEvent(new Event('change',{bubbles:true}));
            return o.text;
        }""")
        if not picked:
            _log("    [remove] FAIL: no '…Duplicate…' reason on the page")
            return False
        # 3) Click the "REMOVE APPLICANT" button — NOT "Save Applicant" (that one is
        #    BLOCKED for dupes: "Cannot Save this Applicant"). Real click + nav wait
        #    so the form actually POSTs; the dialog handler accepts any confirm.
        btn = page.locator(
            "[name='submitRemoveApplicant'], input[value='Remove Applicant']").first
        if btn.count() == 0:
            btn = page.locator(
                "xpath=//input[@type='submit'][contains(@value,'Remove Applicant')]"
                " | //button[contains(normalize-space(.),'Remove Applicant')]").first
        if btn.count() == 0:
            _log("    [remove] FAIL: no 'Remove Applicant' button")
            return False
        try:
            with page.expect_navigation(timeout=8000):
                btn.click(timeout=6000)
        except Exception:  # noqa: BLE001
            try:
                btn.click(timeout=6000, force=True, no_wait_after=True)
            except Exception as e2:  # noqa: BLE001
                _log(f"    [remove] FAIL: Remove click ({type(e2).__name__})")
                return False
        page.wait_for_timeout(2500)
        _log(f"    [remove] REMOVED (reason: {picked})")
        return True
    except Exception as e:  # noqa: BLE001
        _log(f"    remove error: {type(e).__name__}: {e}")
        return False


def _try_overwrite_send(page) -> bool:
    """Push to AI via 'Overwrite Old Applicants (Send to AI)' when the ATS allows
    it (button present, no 'Cannot override'). The ATS still blocks a recent
    contact, so this only sends when legitimately allowed. Send-maximizer."""
    body = _body(page)
    if "overwrite" not in body or "cannot override this applicant" in body:
        return False
    if not _click_first(page, ["Overwrite Old Applicants (Send to AI)",
                               "Overwrite Old Applicants", "Overwrite"]):
        return False
    page.wait_for_timeout(2500)
    return "cannot send to ai" not in _body(page)


_RETEXT_ROWS: list = []


def _flag_retext(a: Applicant, days) -> None:
    """Re-text (>1wk) sends a real message, so it's FLAGGED for review (not
    auto-sent yet) — written to output/oat-retext-queue.csv. Phone is recorded so
    a send (manual --retext-send-live or armed auto) can bind the thread exactly."""
    _RETEXT_ROWS.append([dt.date.today().isoformat(), a.first_name, a.last_name,
                         a.email, a.position, a.cell_phone or a.phone,
                         days if days is not None else ""])


def do_send_ai(page, a: Applicant, live: bool) -> str:
    """GOAL = get to AI. Attempt Send, then handle the ATS's post-click reveal:
    SEND > overwrite+SEND > (>1wk) flag re-text > auto-remove. Returns an outcome
    tag for the run summary."""
    _would(live, "click 'Send to AI'")
    if not live:
        return "dry"
    guard = read_current_applicant(page)
    if _has_dup_signal(guard):
        # a dup that WAS visible on load slipped in as SEND_AI — route it.
        return _handle_visible_dup(page, guard, live)
    if not _click_first(page, ["Send to AI", "Send To AI"]):
        _log("    'Send to AI' button not found — skipped")
        return "no_button"
    page.wait_for_timeout(2500)
    if "cannot send to ai" not in _body(page):
        _log(f"    ✅ SENT to AI: {a.first_name} {a.last_name}")
        return "sent"
    # blocked by prior correspondence — first try to send anyway via overwrite.
    if _try_overwrite_send(page):
        _log(f"    ✅ SENT via overwrite: {a.first_name} {a.last_name}")
        return "sent_override"
    # genuinely can't send → >1wk re-text (armed: text+remove, else flag) else
    # auto-remove (recent dup).
    lc = _parse_last_corr(_body(page))
    days = (dt.date.today() - lc).days if lc else None
    if days is not None and days > config.RETEXT_MIN_DAYS:
        return _armed_retext(page, a, days, live)
    if _perform_remove(page):
        _log(f"    🗑 auto-removed (dup, last contact "
             f"{days if days is not None else '?'}d): {a.first_name} {a.last_name}")
        return "removed"
    return "left"


def _handle_visible_dup(page, a: Applicant, live: bool) -> str:
    """Route a dup that classify() saw on page load, prioritizing a send."""
    if a.override_button:
        return do_override_send_ai(page, a, live)
    if a.interview_future or a.sent_to_call_list_today:
        return do_remove_duplicate(page, a, live)      # already booked / sent today
    if (a.last_correspondence
            and (dt.date.today() - a.last_correspondence).days > config.RETEXT_MIN_DAYS):
        _flag_retext(a, (dt.date.today() - a.last_correspondence).days)
        return "flag_retext"
    return do_remove_duplicate(page, a, live)


def do_override_send_ai(page, a: Applicant, live: bool) -> str:
    _would(live, "Overwrite Old Applicants (Send to AI)")
    if not live:
        return "dry"
    if _try_overwrite_send(page):
        _log(f"    ✅ SENT via overwrite: {a.first_name} {a.last_name}")
        return "sent_override"
    _log(f"    overwrite-send unavailable/blocked — left: {a.first_name} {a.last_name}")
    return "left"


def do_remove_duplicate(page, a: Applicant, live: bool) -> str:
    _would(live, "remove for duplicate")
    if not live:
        return "dry"
    if _perform_remove(page):
        _log(f"    🗑 auto-removed for duplicate: {a.first_name} {a.last_name}")
        return "removed"
    return "left"


_TEMPLATE_NAME = "FOR LUCY"


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _role_from_position(position: str) -> str:
    """Short role for the template's 'xxxx' slot, e.g.
    'Event Marketing & Sales Assistant (Spanish Needed), 2 locations'
    -> 'Event Marketing & Sales Assistant'."""
    p = (position or "").strip()
    for cut in ("(", ",", " - ", " – "):
        i = p.find(cut)
        if i > 3:
            p = p[:i].strip()
    return p or "open"


def _close_sms_panel(page) -> None:
    for xp in ("xpath=(//*[normalize-space(.)='Close'])[1]",
               "xpath=//a[normalize-space(.)='×']",
               "xpath=//*[normalize-space(.)='×'][1]"):
        try:
            loc = page.locator(xp).first
            if loc.count() > 0:
                loc.click(timeout=2000, no_wait_after=True)
                page.wait_for_timeout(500)
                return
        except Exception:  # noqa: BLE001
            continue


def _sms_widget_frame(page, timeout_ms: int = 30000):
    """Find the frame that holds the Bandwidth SMS widget — identified by its Name
    filter. The widget injects SLOWLY (~15-20s after the SMS click), so poll
    patiently (detected via fr.evaluate, same as the probe). Returns
    (frame_or_None, diag)."""
    last_exc = ""
    for k in range(max(1, timeout_ms // 500)):
        for fr in page.frames:
            try:
                if fr.evaluate("() => !!document.querySelector("
                               "\"#sms_name_filter, [name='sms_name_filter']\")"):
                    _log(f"    [retext] widget appeared at ~{k * 0.5:.0f}s")
                    return fr, ""
            except Exception as e:  # noqa: BLE001
                last_exc = type(e).__name__
                continue
        page.wait_for_timeout(500)
    diag = [f"lastExc={last_exc}"] if last_exc else []
    for fr in page.frames:
        try:
            names = fr.evaluate(
                "() => [...document.querySelectorAll('input,select,textarea')]"
                ".map(e=>e.name||e.id||'').filter(n=>/sms/i.test(n)).slice(0,8)")
            diag.append(f"{(fr.url or '')[-24:]}|sms:{names}")
        except Exception as e:  # noqa: BLE001
            diag.append(f"err:{type(e).__name__}")
    return None, " ; ".join(diag)


def _xframe(page, selector):
    """First (frame, locator) across all frames where `selector` matches >=1."""
    for fr in page.frames:
        try:
            loc = fr.locator(selector).first
            if loc.count() > 0:
                return fr, loc
        except Exception:  # noqa: BLE001
            continue
    return None, None


def retext_applicant(page, first, last, phone, role, *, do_send: bool):
    """Send the 'FOR LUCY' re-engagement text to ONE applicant through the Bandwidth
    SMS widget, then report (status, detail). Choreography confirmed with Megan
    2026-07-28 (screenshots): open SMS widget -> Date filter 'This Month' -> type
    applicant NAME in the widget Name box -> Search -> click the matching
    conversation (binds the recipient) -> Load Template -> Search 'FOR LUCY' ->
    Select -> replace NAME/xxxx in the compose box -> (Send).

    Fails SAFE: never sends unless do_send=True; if the recipient thread can't be
    uniquely matched (no thread that far back, or ambiguous), returns 'no_thread'
    WITHOUT sending so the caller flags it for a human instead of guessing."""
    name = f"{first} {last}".strip()
    want = _digits(phone)[-10:]
    if not _open_sms_panel(page):
        return "sms_panel_fail", "could not open SMS widget"
    # The Bandwidth widget injects its DOM asynchronously and may live in a child
    # iframe — resolve the actual frame that holds it before driving anything.
    w, diag = _sms_widget_frame(page, 30000)
    if w is None:
        _log(f"    [retext] widget frame not found — frames: {diag}")
        _close_sms_panel(page)
        return "sms_panel_fail", f"SMS widget did not load; frames=[{diag[:180]}]"
    _log(f"    [retext] widget frame ok (url …{(w.url or '')[-30:]})")
    page.wait_for_timeout(800)

    # 1)+2) Set Date='This Month' + a search term via JS (fill/select timed out
    #    mid-animation even though visible), then click Search (#sms_filter_search).
    #    Prefer the PHONE filter when we have a number (exact, unlike a messy
    #    multi-word last name); otherwise the Name filter (Megan's manual method).
    set_ok = w.evaluate(
        r"""(args) => {
            const nm = args[0], phone = args[1];
            const out = {date:false, term:false, by:''};
            const d = document.querySelector("#sms_date_filter, [name='sms_date_filter']");
            if (d) { const o = [...d.options].find(o => /this month/i.test(o.text));
                     if (o) { d.value = o.value;
                              d.dispatchEvent(new Event('change',{bubbles:true}));
                              out.date = true; } }
            const setF = (sel, val) => {
                const e = document.querySelector(sel);
                if (!e) return false;
                e.value = val;
                e.dispatchEvent(new Event('input',{bubbles:true}));
                e.dispatchEvent(new Event('change',{bubbles:true}));
                return true;
            };
            // clear both, then set the one we're searching by
            setF("#sms_name_filter, [name='sms_name_filter']", "");
            setF("#sms_phone_filter, [name='sms_phone_filter']", "");
            if (phone && setF("#sms_phone_filter, [name='sms_phone_filter']", phone)) {
                out.term = true; out.by = 'phone';
            } else if (setF("#sms_name_filter, [name='sms_name_filter']", nm)) {
                out.term = true; out.by = 'name';
            }
            return out;
        }""", [last or name, want])
    if not set_ok.get("term"):
        _close_sms_panel(page)
        return "retext_err", "sms name/phone/date filter not found in widget frame"
    searched = False
    try:
        w.locator("#sms_filter_search").first.click(timeout=4000, no_wait_after=True)
        searched = True
    except Exception:  # noqa: BLE001
        searched = w.evaluate(
            "() => { const b = document.querySelector('#sms_filter_search');"
            " if (b) { b.click(); return true; } return false; }")
    _log(f"    [retext] filters set date={set_ok.get('date')} "
         f"by={set_ok.get('by')} searched={searched}")
    page.wait_for_timeout(2600)

    # 3) Pick the conversation: prefer the row whose number matches the applicant's
    #    phone; else a single result; else the single name match. Never guess among
    #    several.
    picked = w.evaluate(
        r"""(args) => {
            const want = args[0], name = (args[1]||'').toLowerCase();
            const norm = s => (s||'').replace(/\D/g,'');
            const all = [...document.querySelectorAll('div,li,a,tr')];
            const rows = all.filter(e => {
                const t = e.innerText || '';
                return t.length < 200 && norm(t).length >= 10 &&
                       /\+?1?\d{10}/.test(norm(t)) &&
                       e.querySelectorAll('*').length < 25;
            });
            const cand = rows.filter(e => !rows.some(o => o !== e && e.contains(o)));
            window.__oat_rows = cand;
            const scored = cand.map((e, i) => {
                const t = e.innerText || '', d = norm(t);
                return { i, hasPhone: !!(want && d.includes(want)),
                         hasName: !!(name && t.toLowerCase().includes(name)),
                         text: t.replace(/\s+/g,' ').slice(0,60) };
            });
            const byPhone = scored.find(s => s.hasPhone);
            const named = scored.filter(s => s.hasName);
            const choice = byPhone || (named.length === 1 ? named[0]
                         : (cand.length === 1 ? scored[0] : null));
            return { count: cand.length, choice, sample: scored.slice(0, 6) };
        }""", [want, name])
    _log(f"    [retext] search '{last or name}' -> results={picked.get('count')} "
         f"sample={[s.get('text') for s in picked.get('sample', [])]}")
    choice = picked.get("choice")
    if not choice:
        _close_sms_panel(page)
        return "no_thread", f"no unique thread for {name} ({want or 'no-phone'})"
    try:
        w.evaluate("(i) => window.__oat_rows[i].click()", choice["i"])
        page.wait_for_timeout(1800)
    except Exception as e:  # noqa: BLE001
        _close_sms_panel(page)
        return "retext_err", f"thread click: {type(e).__name__}"
    _log(f"    [retext] bound thread: {choice.get('text')} "
         f"(byPhone={choice.get('hasPhone')})")

    # 4) Load Template -> modal -> filter to 'FOR LUCY' -> Select. The modal can
    #    render in the widget frame OR the main page, so locate across frames.
    _, lt = _xframe(page,
                    "xpath=//button[contains(normalize-space(.),'Load Template')]"
                    " | //a[contains(normalize-space(.),'Load Template')]"
                    " | //input[@type='button'][contains(@value,'Load Template')]")
    if lt is None:
        _close_sms_panel(page)
        return "retext_err", "Load Template button not found"
    lt.click(timeout=4000, no_wait_after=True)
    page.wait_for_timeout(1600)
    mf, msearch = _xframe(page,
                          "xpath=//*[contains(normalize-space(.),'Loading SMS "
                          "Template')]/following::input[@type='text'][1]")
    if msearch is not None:
        try:
            msearch.fill(_TEMPLATE_NAME, timeout=4000)
            page.wait_for_timeout(800)
        except Exception as e:  # noqa: BLE001
            _log(f"    [retext] template search fill failed: {type(e).__name__}")
    _, sel = _xframe(page,
                     "xpath=//tr[.//*[normalize-space(.)='FOR LUCY']]"
                     "//a[normalize-space(.)='Select']"
                     " | //tr[contains(.,'FOR LUCY')]//a[normalize-space(.)='Select']")
    if sel is None:
        _close_sms_panel(page)
        return "retext_err", "FOR LUCY Select link not found"
    sel.click(timeout=4000, no_wait_after=True)
    page.wait_for_timeout(1300)

    # 5) Replace NAME + xxxx in the compose box (search frames for ta_smsChat).
    cf, _ = _xframe(page, "#ta_smsChat, textarea[name='ta_smsChat']")
    cf = cf or w
    filled = cf.evaluate(
        r"""(args) => {
            const first = args[0], role = args[1];
            const ta = document.querySelector("#ta_smsChat, textarea[name='ta_smsChat']")
                    || [...document.querySelectorAll('textarea')]
                         .find(t => /Write message/i.test(t.placeholder||''))
                    || [...document.querySelectorAll('textarea')]
                         .find(t => /NAME|Vantura/.test(t.value||''));
            if (!ta) return '';
            let v = (ta.value || '').replace(/\bNAME\b/g, first).replace(/xxxx/g, role);
            ta.value = v; ta.dispatchEvent(new Event('input', { bubbles: true }));
            return v;
        }""", [first, role])
    if not filled:
        _close_sms_panel(page)
        return "retext_err", "compose box not found after template load"
    _log(f"    [retext] composed -> {filled[:130]!r}")
    if "NAME" in filled or "xxxx" in filled:
        _log("    [retext] WARN: placeholder still present after fill")

    if not do_send:
        _close_sms_panel(page)
        return "retext_dry", filled

    # 6) Send.
    sfr, sbtn = _xframe(page, "#btn-sms-send")
    try:
        (sbtn or w.locator("#btn-sms-send").first).click(timeout=5000,
                                                         no_wait_after=True)
        page.wait_for_timeout(2200)
    except Exception as e:  # noqa: BLE001
        _close_sms_panel(page)
        return "retext_err", f"send click: {type(e).__name__}"
    _close_sms_panel(page)
    return "retext_sent", filled


def _name_matches(a: Applicant, first: str, last: str) -> bool:
    who = f"{a.first_name} {a.last_name}".strip().lower()
    tgt = f"{first} {last}".strip().lower()
    return who == tgt or (bool(first) and bool(last)
                          and first.lower() in who and last.lower() in who)


def _walk_to_and_remove(page, first, last, max_hops: int = 80) -> str:
    """Walk the OAT queue to the applicant matching (first,last) and remove them
    (Duplicate reason). Used to finish a re-texted applicant when we're not already
    sitting on their record. Returns 'removed' / 'not_found' / 'left'."""
    seen: set = set()
    hops = 0
    for hops in range(max_hops):
        a = read_current_applicant(page)
        who = f"{a.first_name} {a.last_name}".strip().lower()
        _log(f"    [remove-one] hop {hops}: {a.first_name!r} {a.last_name!r}")
        if _name_matches(a, first, last):
            _log(f"    [remove-one] found {a.first_name} {a.last_name} — removing")
            return "removed" if _perform_remove(page) else "left"
        key = f"{a.email}|{who}"
        if key in seen:
            _log(f"    [remove-one] re-seen {who!r} — treating as end of queue")
            break
        seen.add(key)
        if not advance_to_next(page):
            _log("    [remove-one] no next control — end of queue")
            break
    _log(f"    [remove-one] not found after {hops + 1} hops")
    return "not_found"


def _armed_retext(page, a: Applicant, days, live: bool) -> str:
    """Shared re-text handler for BOTH re-text paths (do_retext_then_remove AND
    do_send_ai's >1wk block). Armed (live + config.RETEXT_ARMED): text the quiet
    applicant via the SMS widget, then remove the current record
    ('re-texted & removed'). Not armed, or no reachable SMS thread: FLAG (no
    send/remove) — never guesses/spams."""
    if not (live and getattr(config, "RETEXT_ARMED", False)):
        _flag_retext(a, days)
        tail = f" (last contact {days}d)" if days is not None else ""
        _log(f"    ⚑ FLAG re-text: {a.first_name} {a.last_name} "
             f"[{a.cell_phone or a.phone or 'no-phone'}]{tail}")
        return "flag_retext"
    role = _role_from_position(a.position)
    phone = a.cell_phone or a.phone
    status, detail = retext_applicant(page, a.first_name, a.last_name, phone, role,
                                      do_send=True)
    if status == "retext_sent":
        _log(f"    \U0001f4f2 re-texted: {a.first_name} {a.last_name} -> {detail[:80]}")
        if _perform_remove(page):
            _log(f"    \U0001f5d1 re-texted & removed: {a.first_name} {a.last_name}")
            return "retext_removed"
        return "retext_sent"
    # couldn't uniquely reach them — flag for a human, don't guess/spam.
    _flag_retext(a, days)
    _log(f"    ⚑ re-text fell back to FLAG ({status}: {detail}): "
         f"{a.first_name} {a.last_name}")
    return "flag_retext"


def do_retext_then_remove(page, a: Applicant, live: bool) -> str:
    """Re-text a quiet applicant (>1wk, past-interview path) then remove them."""
    _would(live, "re-text then remove")
    if not live:
        return "dry"
    return _armed_retext(page, a, None, live)


def probe_search(page, term: str) -> None:
    """Diagnostic: map the AS search (Megan uses Home→Search→first name), then run a
    search for `term` and dump the results structure so we can wire retext_by_name."""
    first = term.split()[0] if term else ""
    last = term.split()[-1] if term else ""
    # what search inputs / nav exist?
    info = page.evaluate(
        """() => ({
            url: location.href.slice(-46),
            nav: [...document.querySelectorAll('a')].map(e=>(e.innerText||'').trim())
                 .filter(t=>t && t.length<22).slice(0,34),
            searchInputs: [...document.querySelectorAll('input')]
                .filter(e=>/search|srch|name|fname|lname/i.test((e.name||'')+(e.placeholder||'')+(e.id||'')))
                .map(e=>`${e.name||e.id||'?'}|ph:${(e.placeholder||'').slice(0,18)}`).slice(0,16)
        })""")
    _log(f"[search] url={info.get('url')}")
    _log(f"[search] nav={info.get('nav')}")
    _log(f"[search] searchInputs={info.get('searchInputs')}")
    # try the global top-nav search by last name, dump results
    try:
        page.fill("input[name='globalSrchFor']", last, timeout=5000)
        for sel in ("#glblSrchSbmt", "input[name='glblSrchSbmt']",
                    "xpath=//*[normalize-space(.)='Go']"):
            b = page.locator(sel).first
            if b.count() > 0:
                b.click(timeout=4000, no_wait_after=True); break
        page.wait_for_timeout(3200)
        res = page.evaluate(
            """(full) => ({
                url: location.href.slice(-46),
                links: [...document.querySelectorAll('a')]
                    .map(e=>((e.innerText||'').trim().slice(0,26))+' -> '+(e.getAttribute('href')||'').slice(0,30))
                    .filter(t=>t.length>4).slice(0,24),
                rowsWithName: [...document.querySelectorAll('tr,li,div')]
                    .filter(e=>(e.innerText||'').toLowerCase().includes(full) && (e.innerText||'').length<120)
                    .map(e=>(e.innerText||'').replace(/\\s+/g,' ').slice(0,70)).slice(0,8)
            })""", f"{first} {last}".lower())
        _log(f"[search] after-search url={res.get('url')}")
        for i, l in enumerate(res.get("links", [])):
            _log(f"[search] link {i}: {l}")
        for i, r in enumerate(res.get("rowsWithName", [])):
            _log(f"[search] nameRow {i}: {r}")
    except Exception as e:  # noqa: BLE001
        _log(f"[search] probe err: {type(e).__name__}: {e}")


def retext_by_name(page, first, last, phone=""):
    """Re-text an applicant who has already LEFT the OAT queue: global-search AS by
    last name (Home→Search), open their record to read the role they applied for,
    then re-text via the SMS widget. Returns (status, detail)."""
    last = last or first
    try:
        page.fill("input[name='globalSrchFor']", last, timeout=6000)
        clicked = False
        for sel in ("#glblSrchSbmt", "input[name='glblSrchSbmt']",
                    "xpath=//input[@value='Go']", "xpath=//*[normalize-space(.)='Go']"):
            try:
                b = page.locator(sel).first
                if b.count() > 0:
                    b.click(timeout=4000, no_wait_after=True)
                    clicked = True
                    break
            except Exception:  # noqa: BLE001
                continue
        if not clicked:
            page.press("input[name='globalSrchFor']", "Enter")
        page.wait_for_timeout(3200)
    except Exception as e:  # noqa: BLE001
        return "search_err", f"{type(e).__name__}"
    # Open the matching applicant from the results.
    full = f"{first} {last}".lower()
    opened = page.evaluate(
        """(full) => {
            const a = [...document.querySelectorAll('a')].find(e =>
                (e.innerText||'').toLowerCase().includes(full));
            if (a) { a.click(); return (a.innerText||'').trim().slice(0,40); }
            return null; }""", full)
    if not opened:
        return "not_found", f"no search result for {full!r}"
    page.wait_for_timeout(2500)
    a = read_current_applicant(page)
    role = _role_from_position(a.position)
    ph = phone or a.cell_phone or a.phone
    _log(f"    [retext-name] opened {a.first_name} {a.last_name} role={role!r} "
         f"phone={ph!r}")
    if not ph:
        return "no_phone", f"{first} {last} has no phone on record"
    status, detail = retext_applicant(page, first, last, ph, role, do_send=True)
    _log(f"    [retext-name] {first} {last} -> {status} :: {detail[:70]}")
    return status, f"{detail} (role={role})"


_NO_PHONE_ROWS: list = []


def _fill_phone_field(page, phone: str) -> bool:
    """Fill the AS Phone + Cell Phone fields by REAL keystrokes — the way a human
    does it. (JS-setting the value + firing 'change' makes AS re-render and drop
    the 'Send to AI' button; typing keeps it — Megan 2026-07-28.)"""
    d = re.sub(r"\D", "", phone or "")
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    if len(d) != 10:
        return False
    ok = False
    for sel in ("input[name='phone']", "input[name='cellPhone']"):
        try:
            loc = page.locator(sel).first
            if loc.count() == 0:
                continue
            loc.click(timeout=4000)
            loc.fill("")                       # clear any partial
            loc.press_sequentially(d, delay=35)  # type the 10 digits, human-like
            ok = True
        except Exception:  # noqa: BLE001
            continue
    try:
        page.keyboard.press("Tab")             # blur the last field
    except Exception:  # noqa: BLE001
        pass
    return ok


def flag_no_phone(page, a: Applicant, live: bool) -> str:
    """No phone on file → first try to pull the real number off the applicant's
    Indeed resume (Megan's 'View resume' method, 2026-07-28). If found, fill it in
    and Send to AI (turns a dead-end into a real send). Only when the resume has no
    phone either do we flag as 'need to get number from Indeed'."""
    if live and getattr(config, "AUTOMATE_PHONE_LOOKUP", False):
        phone, detail = lookup_resume_phone(page)
        if phone and _fill_phone_field(page, phone):
            _log(f"    \U0001f4de resume phone {phone} → filled + sending: "
                 f"{a.first_name} {a.last_name}")
            try:
                page.bring_to_front()
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(1500)   # let AS settle after the phone change
            # The holder-warmed session can leave the SMS widget open from a prior
            # re-text run, overlaying the panel so 'Send to AI' can't be clicked.
            # Close it before sending.
            _close_sms_panel(page)
            page.wait_for_timeout(600)
            try:
                diag = page.evaluate(
                    "() => ({ url: location.href.slice(-42),"
                    " smsOpen: !!document.querySelector('#sms_name_filter'),"
                    " hasSendToAI: /send to ai/i.test(document.body.innerText||''),"
                    " btns: [...document.querySelectorAll("
                    "'button,input[type=submit],input[type=button]')]"
                    ".map(e=>(e.innerText||e.value||'').trim()).filter(Boolean).slice(0,22) })")
                _log(f"    [phones] after-fill url=…{diag.get('url')} "
                     f"smsOpen={diag.get('smsOpen')} hasSendToAI={diag.get('hasSendToAI')} "
                     f"btns={diag.get('btns')}")
            except Exception as e:  # noqa: BLE001
                _log(f"    [phones] diag err: {type(e).__name__}")
            return do_send_ai(page, a, live)
        _log(f"    no resume phone ({detail}) → flag: "
             f"{a.first_name} {a.last_name}")
    _NO_PHONE_ROWS.append([
        dt.date.today().isoformat(), a.first_name, a.last_name,
        a.email, a.job_board, a.position,
    ])
    _log(f"    flagged no-phone -> {config.NO_PHONE_FLAG_CSV}")
    return "flag_no_phone"


def _flush_csv(path, header, rows, label) -> None:
    if not rows:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(header)
        w.writerows(rows)
    _log(f"[oat] wrote {len(rows)} {label} to {path}")


_ACTIVITY_ROWS: list = []


def _activity_csv(today: dt.date = None) -> str:
    today = today or dt.date.today()
    return f"output/oat-activity-{today.isoformat()}.csv"


def _flush_queues() -> None:
    _flush_csv(config.NO_PHONE_FLAG_CSV,
               ["flagged_date", "first_name", "last_name", "email", "job_board",
                "position"], _NO_PHONE_ROWS, "no-phone applicant(s)")
    _flush_csv("output/oat-retext-queue.csv",
               ["flagged_date", "first_name", "last_name", "email", "position",
                "phone", "days_since_contact"], _RETEXT_ROWS, "re-text applicant(s)")
    # Daily activity log — accumulates across every run of the day; the scorecard
    # reads the whole file and tallies.
    _flush_csv(_activity_csv(),
               ["time", "applicant", "source", "position", "action", "outcome",
                "reason"], _ACTIVITY_ROWS, "activity row(s)")


_DISPATCH = {
    Action.SEND_AI: do_send_ai,
    Action.OVERRIDE_SEND_AI: do_override_send_ai,
    Action.REMOVE_DUPLICATE: do_remove_duplicate,
    Action.REMOVE_FUTURE_INTERVIEW: do_remove_duplicate,  # same "remove" control
    Action.RETEXT_THEN_REMOVE: do_retext_then_remove,
    Action.FLAG_NO_PHONE: flag_no_phone,
}


# --------------------------------------------------------------------------- #
# Debug health check
# --------------------------------------------------------------------------- #
def health_check(page) -> None:
    """Dump the controls on the OAT page so we can fill the stubbed selectors.

    The remote `logtail` reader caps each read at ~470 chars, so we DON'T print a
    tall tree. Each category is joined with ' | ', split into <=380-char chunks,
    and every chunk gets a UNIQUE greppable tag ('HC BTN 0:', 'HC SEL 0:', ...).
    From the laptop: `lucy logtail oat_processing "HC INDEX"` for the counts, then
    `... "HC BTN 0"`, `"HC SEL 0"`, etc. to page each category cleanly."""
    info = page.evaluate(
        """() => {
            const txt = el => (el.innerText||el.value||'').replace(/\\s+/g,' ').trim();
            const uniq = a => [...new Set(a.filter(Boolean))];
            const btns = uniq([...document.querySelectorAll(
                "button, input[type=button], input[type=submit], a")]
                .map(e => txt(e).slice(0,45)).filter(t => t && t.length<=45));
            const sels = [...document.querySelectorAll('select')].map(s => {
                const opts = [...s.options].slice(0,12).map(o => txt(o).slice(0,30));
                return (s.name||s.id||'?') + '=[' + opts.join(',') + ']';
            });
            const inps = [...document.querySelectorAll('input,textarea')].map(i =>
                (i.name||i.id||'?') + ':' + (i.type||'text')
                + (i.value ? '(has-val)' : ''));
            // label -> the input in its row: the map read_current_applicant needs.
            const rows = [];
            [...document.querySelectorAll('td,th,label')].forEach(n => {
                const t = txt(n); if (!t || t.length>28) return;
                const row = n.closest('tr') || n.parentElement;
                const inp = row && row.querySelector('input,select,textarea');
                if (inp) rows.push(t.replace(/:$/,'') + '->' + (inp.name||inp.id||inp.type||'?'));
            });
            return {url: location.href, buttons: btns, selects: sels,
                    inputs: inps, rows: uniq(rows)};
        }"""
    )

    def emit(tag, items):
        joined = " | ".join(str(x) for x in items) or "(none)"
        chunks, cur = [], ""
        for piece in joined.split(" | "):
            if len(cur) + len(piece) + 3 > 380 and cur:
                chunks.append(cur); cur = ""
            cur += (" | " if cur else "") + piece
        if cur:
            chunks.append(cur)
        for i, ch in enumerate(chunks):
            _log(f"HC {tag} {i}: {ch}")
        return len(chunks)

    _log("=== OAT page health check ===")
    _log(f"HC url: {info.get('url')}")
    nb = emit("BTN", info.get("buttons", []))
    ns = emit("SEL", info.get("selects", []))
    ni = emit("INP", info.get("inputs", []))
    nr = emit("ROW", info.get("rows", []))
    _log(f"HC INDEX: BTN={nb} SEL={ns} INP={ni} ROW={nr} "
         f"(counts: buttons={len(info.get('buttons',[]))} "
         f"selects={len(info.get('selects',[]))} inputs={len(info.get('inputs',[]))} "
         f"rows={len(info.get('rows',[]))})")


_PHONE_RE = re.compile(r"\+?1?[\s\-.]*\(?\d{3}\)?[\s\-.]*\d{3}[\s\-.]*\d{4}")


def _view_resume_href(page):
    """Find the 'View resume →' link (in the Resume panel / embedded Indeed email,
    which may be an iframe) and return its href — the signed employers.indeed.com
    resume URL that shows the applicant's real phone (Megan 2026-07-28)."""
    for fr in page.frames:
        try:
            h = fr.evaluate(
                "() => { const a = [...document.querySelectorAll('a')].find("
                "e => /view\\s*resume/i.test(e.innerText||'') && /indeed/i.test(e.href||''));"
                " return a ? a.href : null; }")
            if h:
                return h
        except Exception:  # noqa: BLE001
            continue
    # fallback: any indeed candidates/resume link on the page
    for fr in page.frames:
        try:
            h = fr.evaluate(
                "() => { const a = [...document.querySelectorAll('a')].find("
                "e => /candidates\\/resume/i.test(e.href||'')); return a ? a.href : null; }")
            if h:
                return h
        except Exception:  # noqa: BLE001
            continue
    return None


def lookup_resume_phone(page):
    """Open the applicant's Indeed resume (signed URL from 'View resume') in a new
    page and pull the first phone number. Returns (phone_or_None, detail). No Indeed
    login needed — the URL token authorizes it (Megan confirmed)."""
    href = _view_resume_href(page)
    if not href:
        return None, "no view-resume link"
    newpg = None
    try:
        newpg = page.context.new_page()
        newpg.goto(href, wait_until="domcontentloaded", timeout=30000)
        newpg.wait_for_timeout(2500)
        body = newpg.evaluate("() => (document.body.innerText || '')")
        # The resume header shows name / email / phone / city. Take the first phone
        # that looks real (>= 10 digits), skipping the office callback numbers.
        for m in _PHONE_RE.finditer(body[:2500]):
            digits = re.sub(r"\D", "", m.group(0))
            if len(digits) >= 10:
                return m.group(0).strip(), f"from resume ({newpg.url[:50]})"
        return None, f"no phone on resume (title={newpg.title()[:40]!r})"
    except Exception as e:  # noqa: BLE001
        return None, f"resume open err: {type(e).__name__}"
    finally:
        if newpg:
            try:
                newpg.close()
            except Exception:  # noqa: BLE001
                pass
        # Restore the OAT tab to the foreground — the new resume tab backgrounded
        # it, which left 'Send to AI' unclickable afterward.
        try:
            page.bring_to_front()
        except Exception:  # noqa: BLE001
            pass


def probe_resume(page) -> None:
    """Diagnostic: on the current (no-phone) applicant, find the View-resume link,
    open the resume, and dump what we can pull — to validate the phone-lookup."""
    a = read_current_applicant(page)
    _log(f"[resume] current: {a.first_name} {a.last_name} phone={a.phone!r} "
         f"cell={a.cell_phone!r}")
    href = _view_resume_href(page)
    _log(f"[resume] view-resume href: {str(href)[:110]}")
    if not href:
        # dump anchor texts across frames for diagnosis
        for i, fr in enumerate(page.frames):
            try:
                anchors = fr.evaluate(
                    "() => [...document.querySelectorAll('a')].map(e=>"
                    "(e.innerText||'').trim().slice(0,24)).filter(Boolean).slice(0,20)")
                if anchors:
                    _log(f"[resume] frame {i} anchors: {anchors}")
            except Exception:  # noqa: BLE001
                continue
        return
    phone, detail = lookup_resume_phone(page)
    _log(f"[resume] RESULT phone={phone!r} :: {detail}")


def _open_sms_panel(page) -> bool:
    """Click the always-on 'SMS' button (top-right). Its text is 'SMS' + an unread
    badge number ('SMS\\n13'), so match the anchor whose text is 'SMS' once digits
    are stripped — excludes 'SMS/Email', 'SMS Templates', 'SMS List Report'."""
    _excl = ("not(contains(.,'/')) and not(contains(.,'List')) and "
             "not(contains(.,'Templates')) and not(contains(.,'Report')) and "
             "not(contains(.,'Email'))")
    for xp in (f"xpath=//a[starts-with(normalize-space(.),'SMS') and {_excl}]",
               f"xpath=//span[starts-with(normalize-space(.),'SMS') and {_excl}]/ancestor::a[1]",
               f"xpath=//*[@role='button'][starts-with(normalize-space(.),'SMS') and {_excl}]"):
        try:
            loc = page.locator(xp).first
            if loc.count() > 0:
                loc.click(timeout=6000, no_wait_after=True)
                _log(f"[sms] opened SMS panel via {xp[:55]}")
                page.wait_for_timeout(4000)
                return True
        except Exception as e:  # noqa: BLE001
            _log(f"[sms] click attempt failed: {type(e).__name__}")
            continue
    return False


def probe_sms(page) -> None:
    """Open the always-on SMS panel (top-right 'SMS' button — a Bandwidth widget)
    and dump its structure (frames, inputs, buttons, textareas) so we can wire the
    re-text send flow: search phone -> Load Template 'FOR LUCY' -> fill -> Send."""
    clicked = _open_sms_panel(page)
    if not clicked:
        try:
            cands = page.evaluate(
                "() => [...document.querySelectorAll('a,button,div,span')]"
                ".filter(e=>/^SMS/i.test((e.innerText||'').trim()))"
                ".map(e=>e.tagName+\":'\"+(e.innerText||'').trim().slice(0,20)+\"'\").slice(0,20)")
            _log(f"[sms] SMS button not found; candidates: {cands}")
        except Exception as e:  # noqa: BLE001
            _log(f"[sms] SMS button not found; probe err {e}")
        return
    page.wait_for_timeout(4500)
    _log(f"[sms] frames after open: {len(page.frames)}")
    for i, fr in enumerate(page.frames):
        try:
            info = fr.evaluate(
                """() => ({
                    url: (location.href||'').slice(0,90),
                    inputs: [...document.querySelectorAll('input')]
                        .map(e=>(e.name||e.id||e.placeholder||e.type||'?')).slice(0,30),
                    buttons: [...document.querySelectorAll('button,input[type=button],input[type=submit],a')]
                        .map(e=>(e.innerText||e.value||'').trim()).filter(t=>t&&t.length<28).slice(0,30),
                    textareas: [...document.querySelectorAll('textarea')]
                        .map(e=>(e.name||e.id||e.placeholder||'?')),
                })""")
            if info.get("inputs") or info.get("textareas") or (
                    info.get("buttons") and any("Send" in b or "Template" in b
                                                for b in info.get("buttons", []))):
                _log(f"SMS FRAME {i} url={info.get('url')}")
                _log(f"SMS FRAME {i} inputs={info.get('inputs')}")
                _log(f"SMS FRAME {i} buttons={info.get('buttons')}")
                _log(f"SMS FRAME {i} textareas={info.get('textareas')}")
                # Focused, short-line dump of the send-flow controls (logtail
                # caps ~470 chars/read, so keep each line small & greppable).
                try:
                    # Try to expand a "Load Template" control first so the
                    # template list (where 'FOR LUCY' lives) enters the DOM.
                    for tsel in ("a", "button"):
                        el = fr.query_selector(
                            f"xpath=//{tsel}[contains(translate(.,"
                            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),"
                            "'template')]")
                        if el:
                            try:
                                el.click(timeout=2500)
                                page.wait_for_timeout(1200)
                            except Exception:  # noqa: BLE001
                                pass
                            break
                    focus = fr.evaluate(
                        """() => {
                            const g = s => (s.name||s.id||s.placeholder||'?');
                            return {
                              sels: [...document.querySelectorAll('select')].map(s =>
                                g(s)+':['+[...s.options].map(o=>(o.text||'').trim())
                                .filter(Boolean).slice(0,15).join('|')+']').slice(0,8),
                              tmpl: [...document.querySelectorAll('a,button,li,option,div')]
                                .map(e=>(e.innerText||e.value||'').trim())
                                .filter(t=>/lucy|template/i.test(t)&&t.length<40).slice(0,15),
                              send: [...document.querySelectorAll(
                                'a,button,input[type=submit],input[type=button]')]
                                .filter(e=>/^send/i.test((e.innerText||e.value||'').trim()))
                                .map(e=>e.tagName+':'+(e.name||e.id||'')+':'
                                  +(e.innerText||e.value||'').trim()).slice(0,8),
                              msg: [...document.querySelectorAll('textarea,[contenteditable]')]
                                .map(e=>(e.name||e.id||e.placeholder||e.tagName||'?')).slice(0,8),
                            };
                        }""")
                    _log(f"SMSF sels={focus.get('sels')}")
                    _log(f"SMSF tmpl={focus.get('tmpl')}")
                    _log(f"SMSF send={focus.get('send')}")
                    _log(f"SMSF msg={focus.get('msg')}")
                except Exception as e:  # noqa: BLE001
                    _log(f"SMSF focus err: {type(e).__name__}")
        except Exception as e:  # noqa: BLE001
            _log(f"SMS FRAME {i} err: {type(e).__name__}")

    # The name= fields (sms_name_filter/sms_date_filter) turned out to be HIDDEN
    # backing fields (page.fill timed out on them). Dump the VISIBLE widget
    # controls (what a user actually types into) so we target those instead.
    try:
        vis = page.evaluate(
            r"""() => {
                const seen = e => { const r = e.getBoundingClientRect();
                    return e.offsetParent !== null && r.width > 2 && r.height > 2; };
                const lbl = e => {
                    let p = e.previousElementSibling;
                    let t = (p && (p.innerText||'').trim()) || '';
                    if (!t && e.closest('label')) t = e.closest('label').innerText||'';
                    return t.replace(/\s+/g,' ').slice(0, 18);
                };
                const inps = [...document.querySelectorAll('input')].filter(seen)
                    .filter(e => !/hidden/.test(e.type))
                    .map(e => `${e.type}|${e.name||e.id||'?'}|ph:${(e.placeholder||'').slice(0,14)}|L:${lbl(e)}`)
                    .slice(0, 16);
                const sels = [...document.querySelectorAll('select')].filter(seen)
                    .map(e => `${e.name||e.id||'?'}|L:${lbl(e)}|opts:${[...e.options].map(o=>(o.text||'').trim()).slice(0,7).join(',')}`)
                    .slice(0, 8);
                const tas = [...document.querySelectorAll('textarea')].filter(seen)
                    .map(e => `${e.name||e.id||'?'}|ph:${(e.placeholder||'').slice(0,20)}`).slice(0, 6);
                const btns = [...document.querySelectorAll('button,input[type=button],input[type=submit],a')]
                    .filter(seen).map(e => `${(e.innerText||e.value||'').trim().slice(0,20)}#${e.id||''}`)
                    .filter(t => t && t.length < 26).slice(0, 24);
                return {inps, sels, tas, btns};
            }""")
        for tag, arr in (("VISW inp", vis.get("inps")), ("VISW sel", vis.get("sels")),
                         ("VISW ta", vis.get("tas")), ("VISW btn", vis.get("btns"))):
            for item in (arr or []):
                _log(f"{tag} :: {item}")
    except Exception as e:  # noqa: BLE001
        _log(f"VISW dump err: {type(e).__name__}")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def run(live: bool = False, limit: int = None, debug: bool = False,
        headed: bool = False, max_actions: int = None, probe_sms_flag: bool = False,
        probe_resume_flag: bool = False,
        retext_test: str = None, retext_send: str = None,
        remove_applicant: str = None, retext_names: str = None,
        probe_search_term: str = None, _attempt: int = 1) -> int:
    limit = limit if limit is not None else config.MAX_PER_RUN
    today = dt.date.today()

    mode = "LIVE" if live else "DRY-RUN"
    _log(f"[oat] OAT Processing — office {config.OFFICE_ID} "
         f"({config.OFFICE_HINT}) — {mode}")

    try:
        # Same holder-warmed AppStream session resume_pushing rides. No
        # extensions needed (OAT doesn't use the resume-extractor plugin).
        # yield_if_busy so we step aside if another Carlos-session run holds it.
        with appstream_direct_session(yield_if_busy=True) as page:
            # ApplicantStream pops a JS confirm() on Save/remove/send; patchright
            # auto-DISMISSES dialogs by default, which CANCELLED our removes/sends
            # (they logged 'done' but the queue count never dropped — Megan 7/27).
            # Accept every confirm so the actions actually persist. Applies to any
            # popup opened in this context too.
            page.on("dialog", lambda d: d.accept())
            page.context.on("page", lambda p: p.on("dialog", lambda d: d.accept()))
            if not fetch_office._switch_office(page, config.OFFICE_ID,
                                               config.OFFICE_HINT):
                _log(f"[oat] FATAL: office switch to {config.OFFICE_ID} failed")
                return 2
            _log(f"[oat] on office {config.OFFICE_ID} ({config.OFFICE_HINT})")

            if probe_sms_flag:
                open_oat(page)
                probe_sms(page)
                return 0

            if probe_resume_flag:
                open_oat(page)
                probe_resume(page)
                return 0

            if probe_search_term:
                open_oat(page)
                probe_search(page, probe_search_term)
                return 0

            if retext_names:
                # Re-text applicants who've left the OAT queue. Semicolon list of
                # 'First Last|Phone' (phone optional — read from their record).
                open_oat(page)
                for spec in retext_names.split(";"):
                    parts = [p.strip() for p in spec.split("|")]
                    nm = parts[0].split()
                    if not nm:
                        continue
                    first = nm[0]
                    last = " ".join(nm[1:]) if len(nm) > 1 else ""
                    ph = parts[1] if len(parts) > 1 else ""
                    st, det = retext_by_name(page, first, last, ph)
                    _log(f"[oat] RETEXT-BY-NAME {first} {last!r} -> {st} :: {det[:90]}")
                    open_oat(page)  # back to a clean OAT page for the next one
                return 0

            if retext_test or retext_send:
                # Validate the FULL re-text chain on ONE named person. --retext-test
                # stops before Send (dry); --retext-send-live actually sends ONE real
                # message (controlled Send-button validation). 'First Last' or
                # 'First Last|Role|Phone'.
                spec = retext_send or retext_test
                do_send = bool(retext_send)
                parts = [p.strip() for p in spec.split("|")]
                nm = parts[0].split()
                first = nm[0] if nm else ""
                last = " ".join(nm[1:]) if len(nm) > 1 else ""
                role = parts[1] if len(parts) > 1 and parts[1] else "Event Marketing"
                phone = parts[2] if len(parts) > 2 else ""
                open_oat(page)  # land on p=604 — the SMS widget injects there
                _log(f"[oat] RETEXT-{'SEND-LIVE' if do_send else 'TEST(no send)'} "
                     f"name={first} {last!r} role={role!r} phone={phone!r}")
                status, detail = retext_applicant(page, first, last, phone, role,
                                                  do_send=do_send)
                _log(f"[oat] RETEXT result: {status} :: {detail[:160]!r}")
                # Mirror the real flow: after a live send, remove that applicant
                # (walk to their record — the SMS widget left us elsewhere).
                if do_send and status == "retext_sent":
                    rr = _walk_to_and_remove(page, first, last)
                    _log(f"[oat] RETEXT post-send remove: {rr}")
                return 0

            if remove_applicant:
                # Utility: walk OAT to a named applicant and remove them (no text).
                open_oat(page)
                nm = remove_applicant.split()
                first = nm[0] if nm else ""
                last = " ".join(nm[1:]) if len(nm) > 1 else ""
                rr = _walk_to_and_remove(page, first, last)
                _log(f"[oat] REMOVE-APPLICANT {first} {last!r} -> {rr}")
                return 0

            if debug:
                # Dump the LANDING console first (shows the real nav anchors),
                # then attempt OAT and dump that page too if we get there.
                _log("[oat] --- health check: LANDING console ---")
                health_check(page)
                opened = open_oat(page)
                _log(f"[oat] open_oat -> {opened}")
                if opened:
                    _log("[oat] --- health check: OAT page ---")
                    health_check(page)
                    # Validate the read/classify layer on the current applicant.
                    a = read_current_applicant(page, today)
                    d = classify(a, today)
                    _log(f"HC STATE: name={a.first_name} {a.last_name!r} "
                         f"phone={a.phone!r} cell={a.cell_phone!r} jb={a.job_board!r} "
                         f"pos={a.position[:40]!r}")
                    _log(f"HC STATE2: override_btn={a.override_button} "
                         f"corr_blocked={a.correspondence_blocked} "
                         f"last_corr={a.last_correspondence} "
                         f"intv_future={a.interview_future} "
                         f"intv_noshow={a.interview_past_noshow} "
                         f"sent_today={a.sent_to_call_list_today} "
                         f"total={getattr(a,'_total',None)}")
                    _log(f"HC STATE3: status={a.raw_status[:200]!r}")
                    _log(f"HC DECISION: {d.action.value} — {d.reason}")
                    # Diagnostic: is the state content actually on the page, and
                    # is our parser missing it, or is it genuinely absent?
                    try:
                        mk = page.evaluate(r"""() => {
                          const b=(document.body.innerText||'');
                          const has=s=>b.toLowerCase().includes(s.toLowerCase());
                          return {
                            following: has('Following Applicants'),
                            cannotOverride: has('Cannot override'),
                            overwrite: has('Overwrite Old Applicants'),
                            lastCorr: has('last correspondence was on'),
                            emails: (b.match(/of\s+\d+\s+emails/i)||[''])[0],
                            heads: [...document.querySelectorAll('table')]
                              .map(t=>(t.querySelector('tr')?.innerText||'').replace(/\s+/g,' ').slice(0,70))
                              .filter(Boolean).slice(0,18),
                            // pager controls: anything clickable/selectable whose
                            // text or nearby text mentions Emails/page navigation.
                            pager: (()=>{
                              const out=[];
                              document.querySelectorAll('a,input,select,img,button').forEach(e=>{
                                const t=(e.innerText||e.value||e.alt||e.title||'').trim();
                                const oc=(e.getAttribute('onclick')||'').slice(0,50);
                                const nm=e.name||e.id||'';
                                if(/next|prev|page|email|›|»|◄|►|>|</i.test(t+' '+oc+' '+nm) && (t.length<25))
                                  out.push(`${e.tagName}<${nm}> '${t}' oc=${oc}`);
                              });
                              return [...new Set(out)].slice(0,20);
                            })(),
                          };
                        }""")
                        _log(f"HC MARK: following={mk.get('following')} "
                             f"cannotOverride={mk.get('cannotOverride')} "
                             f"overwrite={mk.get('overwrite')} lastCorr={mk.get('lastCorr')} "
                             f"emails={mk.get('emails')!r}")
                        for i, h in enumerate(mk.get("heads", [])):
                            _log(f"HC THEAD {i}: {h}")
                        for i, pg in enumerate(mk.get("pager", [])):
                            _log(f"HC PAGER {i}: {pg}")
                    except Exception as e:  # noqa: BLE001
                        _log(f"HC MARK failed: {e}")
                    # Resume probe: is a missing phone recoverable from the resume
                    # panel / email on-page (across iframes)? Answers "can we fill
                    # the number ourselves and send them through?".
                    try:
                        phones = set()
                        for fr in page.frames:
                            try:
                                txt = fr.inner_text("body")
                            except Exception:  # noqa: BLE001
                                continue
                            for m in re.findall(
                                    r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", txt or ""):
                                phones.add(m.strip())
                        _log(f"HC RESUME: phones found across {len(page.frames)} "
                             f"frame(s): {sorted(phones)[:8]}")
                    except Exception as e:  # noqa: BLE001
                        _log(f"HC RESUME failed: {e}")
                    # Remove mechanism: dump ALL rmvReason options (is there a
                    # 'Duplicate'?) + the Save/remove-related controls, so we wire
                    # the RIGHT "remove for duplicate" action. Read-only.
                    try:
                        rm = page.evaluate(r"""() => {
                          const s=document.querySelector("select[name='rmvReason']");
                          const opts = s ? [...s.options].map(o=>o.text.trim()) : [];
                          const save = [...document.querySelectorAll('button,input,a')]
                            .filter(e=>/save applicant|remove|overwrite|duplicate/i.test(e.innerText||e.value||''))
                            .map(e=>`${e.tagName}[${e.name||e.id||''}]='${(e.innerText||e.value||'').trim().slice(0,32)}'`);
                          return {rmvReason: opts, controls: [...new Set(save)].slice(0,20),
                                  hasRemovApp: !!document.querySelector("[name='removApp']")};
                        }""")
                        _log(f"HC RMVREASON ({len(rm.get('rmvReason',[]))}): {rm.get('rmvReason')}")
                        _log(f"HC REMOVE hasRemovApp={rm.get('hasRemovApp')} controls={rm.get('controls')}")
                    except Exception as e:  # noqa: BLE001
                        _log(f"HC RMVREASON failed: {e}")
                    # Re-text/await MESSAGE templates — the exact copy that would go
                    # out, for Megan to confirm before re-text auto-send is armed.
                    try:
                        msg = page.evaluate(r"""() => {
                          const v = n => { const e=document.querySelector(`[name='${n}']`);
                            return e ? (e.value||e.innerText||'').trim() : ''; };
                          const optsOf = n => { const s=document.querySelector(`[name='${n}']`);
                            return s && s.options ? [...s.options].map(o=>o.text.trim()) : []; };
                          // 'Await Call Email' + Quick Notes may be selects; the
                          // Email-Applicant compose holds the message body.
                          const await_ = document.querySelector("[name='emailType'],[name='awaitType'],[name='awaitCallEmail']");
                          return {
                            subject: v('emailApplicantSubject'),
                            message: v('emailApplicantMessage'),
                            qNotes: optsOf('qNotes'),
                            awaitName: await_ ? (await_.name||await_.id) : '',
                            awaitOpts: await_ && await_.options ? [...await_.options].map(o=>o.text.trim()) : [],
                            sendEmail: (document.querySelector("[name='sendEmail']")||{}).checked,
                            sendSMS: (document.querySelector("[name='sendSMS']")||{}).checked,
                          };
                        }""")
                        _log(f"HC MSG subject={msg.get('subject')!r}")
                        _log(f"HC MSG body={msg.get('message')!r}")
                        _log(f"HC MSG await={msg.get('awaitName')!r} opts={msg.get('awaitOpts')}")
                        _log(f"HC MSG qNotes={msg.get('qNotes')}")
                        _log(f"HC MSG sendEmail={msg.get('sendEmail')} sendSMS={msg.get('sendSMS')}")
                    except Exception as e:  # noqa: BLE001
                        _log(f"HC MSG failed: {e}")
                return 0

            if not open_oat(page):
                _log("[oat] FATAL: could not open the One-App-at-a-time page")
                return 2

            _start_total = getattr(read_current_applicant(page, today), "_total", None)
            _log(f"[oat] QUEUE at start: {_start_total} emails")

            processed = 0
            actions = 0                 # live mutations (sent/removed) this run
            MUTATIONS = ("sent", "sent_override", "removed")
            counts: dict = {}
            seen: set = set()          # applicant keys already handled this run
            no_progress = 0            # consecutive already-seen reads (end guard)
            while processed < limit:
                a = read_current_applicant(page, today)
                key = f"{a.email}|{a.first_name} {a.last_name}".strip().lower()
                # Walk logic that survives the queue shifting under us: after a
                # REMOVE/SEND the app leaves its slot, so the NEXT app becomes
                # current (fresh key → handled below, no Next needed); after a
                # non-mutation the SAME app stays current, so we page Next to move
                # past it. Stop only when we can't reach a fresh applicant (the
                # true end), not on the first re-seen one.
                if not key or key == "|" or key in seen:
                    no_progress += 1
                    if no_progress > 3:
                        _log(f"[oat] no fresh applicants — end of queue after "
                             f"{processed} processed")
                        break
                    if not advance_to_next(page):
                        _log(f"[oat] no next control — end of queue after "
                             f"{processed} processed")
                        break
                    continue
                no_progress = 0
                seen.add(key)
                d: Decision = classify(a, today)
                sig = (f"phone={'Y' if (a.phone or a.cell_phone) else 'N'} "
                       f"ovr={int(a.override_button)} blk={int(a.correspondence_blocked)} "
                       f"intF={int(a.interview_future)} intN={int(a.interview_past_noshow)} "
                       f"sent={int(a.sent_to_call_list_today)} "
                       f"lc={a.last_correspondence or '-'}")
                _log(f"[{processed + 1}] {d.action.value.upper()} — {d.reason}  [{sig}]")
                try:
                    outcome = _DISPATCH[d.action](page, a, live)
                except Exception as e:  # noqa: BLE001
                    _log(f"    ERROR performing {d.action.value}: "
                         f"{type(e).__name__}: {e}")
                    outcome = "error"
                counts[outcome or d.action.value] = counts.get(outcome or d.action.value, 0) + 1
                # Activity log — one row per applicant, for the daily scorecard.
                if live:
                    _ACTIVITY_ROWS.append([
                        dt.datetime.now().strftime("%H:%M"),
                        f"{a.first_name} {a.last_name}".strip(),
                        a.job_board, a.position[:60],
                        d.action.value, outcome or "", d.reason[:140],
                    ])

                processed += 1
                # Throttle live mutations (a controlled test uses --max-actions 1).
                if live and outcome in MUTATIONS:
                    actions += 1
                    if max_actions is not None and actions >= max_actions:
                        _log(f"[oat] reached --max-actions {max_actions} — stopping")
                        break
                if processed >= limit:
                    break
                # Do NOT page Next here. Re-read on the next loop: a removed/sent
                # app has left its slot (a fresh app is now current → handled), and
                # an app that stayed re-reads as already-seen so the guard at the
                # top pages Next past it. This walks the WHOLE queue instead of
                # stopping after the first mutation.
                page.wait_for_timeout(1200 if outcome in MUTATIONS else 400)

            _flush_queues()
            try:
                _end_total = getattr(read_current_applicant(page, today), "_total", None)
            except Exception:  # noqa: BLE001
                _end_total = None
            _log(f"[oat] QUEUE at end: {_end_total} emails "
                 f"(was {_start_total} — a persisted send/remove drops this)")
            _log(f"[oat] done — {processed} applicant(s) this run: "
                 + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    except AppStreamBusy:
        _log("[oat] AppStream session busy (another run holds Carlos's "
             "session) — stepping aside; try again shortly")
        return 3
    except RuntimeError as e:
        # The patchright session intermittently gets a Cloudflare re-challenge
        # ("console never rendered #searchMC"). A fresh session launch self-heals
        # it (every retry has worked), so retry the whole run up to 3x before
        # giving up. This failure happens during session setup, BEFORE any
        # applicant is touched, so retrying never double-acts.
        msg = str(e).lower()
        if (("never rendered" in msg or "searchmc" in msg) and _attempt < 3):
            _log(f"[oat] session didn't establish (Cloudflare re-challenge?) — "
                 f"retry {_attempt + 1}/3 with a fresh session")
            return run(live=live, limit=limit, debug=debug, headed=headed,
                       max_actions=max_actions, _attempt=_attempt + 1)
        raise
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="OAT Processing (office 11580, Lucy 2)")
    p.add_argument("--live", action="store_true",
                   help="Actually perform send/remove/override clicks "
                        "(default is dry-run: read + classify + print only)")
    p.add_argument("--dry-run", action="store_true",
                   help="Explicit dry-run (this is already the default)")
    p.add_argument("--limit", type=int, default=None,
                   help=f"Max applicants this run (default {config.MAX_PER_RUN})")
    p.add_argument("--debug", action="store_true",
                   help="Land on the OAT page, print a health check, then stop")
    p.add_argument("--headed", action="store_true", help="Force a visible browser")
    p.add_argument("--max-actions", type=int, default=None, dest="max_actions",
                   help="Cap live mutations (send/overwrite-send/remove) this run "
                        "(safety throttle; use --max-actions 1 for a controlled test)")
    p.add_argument("--probe-sms", action="store_true", dest="probe_sms",
                   help="Open the SMS panel and dump its structure (for re-text), stop")
    p.add_argument("--probe-resume", action="store_true", dest="probe_resume",
                   help="On the current applicant, open the Indeed resume and try to "
                        "pull the phone (for the no-phone lookup), stop")
    p.add_argument("--retext-test", default=None, dest="retext_test",
                   metavar="'First Last[|Role|Phone]'",
                   help="Validate the full re-text chain on one named person "
                        "WITHOUT sending (Load Template -> FOR LUCY -> compose), stop")
    p.add_argument("--retext-send-live", default=None, dest="retext_send",
                   metavar="'First Last[|Role|Phone]'",
                   help="ACTUALLY SEND one real re-text to the named person, then "
                        "remove them (mirrors text-then-remove). Sends an SMS.")
    p.add_argument("--remove-applicant", default=None, dest="remove_applicant",
                   metavar="'First Last'",
                   help="Walk OAT to the named applicant and remove them (no text)")
    p.add_argument("--retext-by-name", default=None, dest="retext_names",
                   metavar="'First Last|Phone;First Last|Phone'",
                   help="Re-text applicants who left the queue: search AS, read their "
                        "role, and SEND the FOR LUCY text. Semicolon-separated list.")
    p.add_argument("--probe-search", default=None, dest="probe_search_term",
                   metavar="'First Last'",
                   help="Diagnostic: map AS search + dump results for a name, stop")
    args = p.parse_args(argv)

    live = args.live and not args.dry_run
    return run(live=live, limit=args.limit, debug=args.debug, headed=args.headed,
               max_actions=args.max_actions, probe_sms_flag=args.probe_sms,
               probe_resume_flag=args.probe_resume,
               retext_test=args.retext_test, retext_send=args.retext_send,
               remove_applicant=args.remove_applicant, retext_names=args.retext_names,
               probe_search_term=args.probe_search_term)


if __name__ == "__main__":
    sys.exit(main())
