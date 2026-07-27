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
    """Remove-for-duplicate: check removApp, set rmvReason to a '…duplicate…'
    option, click 'Save Applicant'. Returns True if submitted. Auto-remove was
    authorized by Megan (2026-07-27). Never removes if the 'duplicate' reason
    option isn't found (fails safe)."""
    try:
        cb = page.locator("[name='removApp']").first
        if cb.count():
            cb.check(timeout=4000)
        picked = page.evaluate(
            """() => { const s=document.querySelector("select[name='rmvReason']");
               if(!s) return '';
               const o=[...s.options].find(o=>/duplicate/i.test(o.text));
               if(!o) return '';
               s.value=o.value; s.dispatchEvent(new Event('change',{bubbles:true}));
               return o.text; }""")
        if not picked:
            _log("    remove: no '…duplicate…' rmvReason option — NOT removing")
            return False
        # Click Save Applicant. Prefer the input by NAME (submitSaveApplicant) —
        # more robust than text after the block state; scroll it into view first.
        btn = page.locator(
            "[name='submitSaveApplicant'], input[value='Save Applicant'], "
            "input[value='Save Applicant ']").first
        try:
            if btn.count() > 0:
                btn.scroll_into_view_if_needed(timeout=3000)
                btn.click(timeout=6000, no_wait_after=True)
            elif not _click_first(page, ["Save Applicant"]):
                _log("    remove: 'Save Applicant' control not found")
                return False
        except Exception as e:  # noqa: BLE001
            _log(f"    remove: Save click failed ({type(e).__name__}) — not removed")
            return False
        page.wait_for_timeout(2200)
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
    auto-sent yet) — written to output/oat-retext-queue.csv."""
    _RETEXT_ROWS.append([dt.date.today().isoformat(), a.first_name, a.last_name,
                         a.email, a.position, days if days is not None else ""])


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
    # genuinely can't send → >1wk re-text (flag) else auto-remove (recent dup).
    lc = _parse_last_corr(_body(page))
    days = (dt.date.today() - lc).days if lc else None
    if days is not None and days > config.RETEXT_MIN_DAYS:
        _log(f"    ⚑ FLAG re-text: {a.first_name} {a.last_name} (last contact {days}d)")
        _flag_retext(a, days)
        return "flag_retext"
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


def do_retext_then_remove(page, a: Applicant, live: bool) -> str:
    """Re-text (>1wk) — FLAG only for now (sends a real message; validate first)."""
    _would(live, "flag re-text")
    if live:
        _flag_retext(a, None)
        _log(f"    ⚑ FLAG re-text: {a.first_name} {a.last_name}")
    return "flag_retext"


_NO_PHONE_ROWS: list = []


def flag_no_phone(page, a: Applicant, live: bool) -> str:
    """Parked branch: record the applicant so a human (or a later Octo/Indeed
    lookup) can get their number. This write is SAFE (local CSV) so it runs in
    dry-run too."""
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
                "days_since_contact"], _RETEXT_ROWS, "re-text applicant(s)")
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


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def run(live: bool = False, limit: int = None, debug: bool = False,
        headed: bool = False, max_actions: int = None, _attempt: int = 1) -> int:
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
            if not fetch_office._switch_office(page, config.OFFICE_ID,
                                               config.OFFICE_HINT):
                _log(f"[oat] FATAL: office switch to {config.OFFICE_ID} failed")
                return 2
            _log(f"[oat] on office {config.OFFICE_ID} ({config.OFFICE_HINT})")

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
                return 0

            if not open_oat(page):
                _log("[oat] FATAL: could not open the One-App-at-a-time page")
                return 2

            processed = 0
            actions = 0                 # live mutations (sent/removed) this run
            MUTATIONS = ("sent", "sent_override", "removed")
            counts: dict = {}
            seen: set = set()          # applicant keys we've already processed
            while processed < limit:
                a = read_current_applicant(page, today)
                # End-of-queue / cycle detection: the pager "Next" stays on the
                # last applicant at the end, so stop once we re-see one (identity =
                # email + name; falls back to name when email is blank).
                key = f"{a.email}|{a.first_name} {a.last_name}".strip().lower()
                if key and key != "|" and key in seen:
                    _log(f"[oat] re-reached {a.first_name} {a.last_name} — end of "
                         f"queue after {processed}")
                    break
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
                # Advance to the next applicant. CONFIRMED 2026-07-27: the OAT page
                # does NOT auto-load the next app after a send/remove (the loop
                # stopped early assuming it did), so always page Next — even after a
                # mutation. Cycle-detection at the top stops us at end-of-queue.
                if outcome in MUTATIONS:
                    page.wait_for_timeout(1200)
                if not advance_to_next(page):
                    break

            _flush_queues()
            _log(f"\n[oat] done — {processed} applicant(s) this run: "
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
    args = p.parse_args(argv)

    live = args.live and not args.dry_run
    return run(live=live, limit=args.limit, debug=args.debug, headed=args.headed,
               max_actions=args.max_actions)


if __name__ == "__main__":
    sys.exit(main())
