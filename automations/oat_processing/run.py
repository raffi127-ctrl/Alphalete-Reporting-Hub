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

    Text/label-based (no hardcoded p= page number): hover/click "Applicants",
    then click the "One App at a time" link. Returns True if we landed on it.
    # >>> VERIFY on Lucy 2: confirm the nav labels + that this is the right page.
    """
    try:
        page.locator(
            "xpath=//a[contains(normalize-space(.),'One App at a time')]"
        ).first.click(timeout=8000)
        page.wait_for_timeout(1500)
        return True
    except Exception as e:  # noqa: BLE001
        _log(f"[oat] could not click 'One App at a time' link: "
             f"{type(e).__name__}: {e}")
        return False


# --------------------------------------------------------------------------- #
# Reading one applicant off the OAT screen  # >>> VERIFY on Lucy 2
# --------------------------------------------------------------------------- #
def _field_value(page, label: str) -> str:
    """Best-effort read of an 'Applicant Details' field by its visible label
    (First Name / Last Name / Phone / Cell Phone / Email / Job Board). The
    classic screen renders label + input rows; we find the input nearest the
    label text. # >>> VERIFY on Lucy 2: confirm the row/input structure."""
    try:
        return page.evaluate(
            """(label) => {
                const norm = s => (s||'').replace(/\\s+/g,' ').trim().toLowerCase();
                const target = norm(label).replace(/:$/,'');
                // find a cell/label whose text matches, then the input in the
                // same row (tr) or immediately after it.
                const nodes = [...document.querySelectorAll('td,th,label,div,span')];
                for (const n of nodes) {
                    if (norm(n.innerText).replace(/:$/,'') !== target) continue;
                    const row = n.closest('tr') || n.parentElement;
                    const inp = row && row.querySelector('input,select,textarea');
                    if (inp) return (inp.value || inp.getAttribute('value') || '').trim();
                }
                return '';
            }""",
            label,
        ) or ""
    except Exception:  # noqa: BLE001
        return ""


def read_current_applicant(page) -> Applicant:
    """Read the fields we can see on the OAT screen into an Applicant.

    The name/phone/cell/email/job-board/position reads use the labels visible in
    the screenshot. The STATE flags (override_offered, sent_to_call_list_today,
    has_interview, interview_date) are LEFT UNSET here — those live in the
    duplicate dialog / status line we haven't captured yet, so classify() will
    treat an unread applicant conservatively (SEND_AI/FLAG_NO_PHONE) until the
    selectors are filled. # >>> VERIFY on Lucy 2 (see task #4)."""
    a = Applicant(
        first_name=_field_value(page, "First Name"),
        last_name=_field_value(page, "Last Name"),
        phone=_field_value(page, "Phone"),
        cell_phone=_field_value(page, "Cell Phone"),
        email=_field_value(page, "Email"),
        job_board=_field_value(page, "Job Board"),
    )
    # >>> VERIFY: position comes off the resume panel / subject ("AT&T Sales
    #     Representative ..."). override_offered / sent_to_call_list_today /
    #     has_interview / interview_date come off the duplicate dialog + status.
    return a


def advance_to_next(page) -> bool:
    """Move to the next applicant in the OAT queue. Returns False when the queue
    is empty. # >>> VERIFY on Lucy 2: the 'next'/save-and-next control."""
    _log("[oat] advance_to_next is not wired yet — stopping after one applicant")
    return False


# --------------------------------------------------------------------------- #
# Actions  (all clicks are # >>> VERIFY on Lucy 2 and gated behind --live)
# --------------------------------------------------------------------------- #
def _would(live: bool, what: str) -> None:
    _log(f"    {'[LIVE] ' if live else '[dry-run] would '}{what}")


def do_send_ai(page, a: Applicant, live: bool) -> None:
    _would(live, "send to AI (call list)")
    if live:
        raise NotImplementedError("send-to-AI click not wired — run --debug on Lucy 2")


def do_override_send_ai(page, a: Applicant, live: bool) -> None:
    _would(live, "overwrite old applicant + send to AI")
    if live:
        raise NotImplementedError("override+send click not wired — run --debug on Lucy 2")


def do_remove_duplicate(page, a: Applicant, live: bool) -> None:
    _would(live, "remove for duplicate")
    if live:
        raise NotImplementedError("remove-duplicate click not wired — run --debug on Lucy 2")


def do_retext_then_remove(page, a: Applicant, live: bool) -> None:
    _would(live, f"set Await Call Email to the '{a.position or '?'}' template, "
                 f"send email/SMS, then remove for duplicate")
    if live:
        raise NotImplementedError("re-text flow not wired — run --debug on Lucy 2")


_NO_PHONE_ROWS: list = []


def flag_no_phone(page, a: Applicant, live: bool) -> None:
    """Parked branch: record the applicant so a human (or a later Octo/Indeed
    lookup) can get their number. This write is SAFE (local CSV) so it runs in
    dry-run too."""
    _NO_PHONE_ROWS.append([
        dt.date.today().isoformat(), a.first_name, a.last_name,
        a.email, a.job_board, a.position,
    ])
    _log(f"    flagged no-phone -> {config.NO_PHONE_FLAG_CSV}")


def _flush_no_phone() -> None:
    if not _NO_PHONE_ROWS:
        return
    path = config.NO_PHONE_FLAG_CSV
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["flagged_date", "first_name", "last_name",
                        "email", "job_board", "position"])
        w.writerows(_NO_PHONE_ROWS)
    _log(f"[oat] wrote {len(_NO_PHONE_ROWS)} no-phone applicant(s) to {path}")


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
        headed: bool = False) -> int:
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

            if not open_oat(page):
                _log("[oat] FATAL: could not open the One-App-at-a-time page")
                return 2

            if debug:
                health_check(page)
                return 0

            processed = 0
            counts: dict = {}
            while processed < limit:
                a = read_current_applicant(page)
                # position/state flags come from VERIFY-pending reads; classify
                # is conservative until those land.
                d: Decision = classify(a, today)
                counts[d.action.value] = counts.get(d.action.value, 0) + 1
                _log(f"[{processed + 1}] {d.action.value.upper()} — {d.reason}")
                try:
                    _DISPATCH[d.action](page, a, live)
                except NotImplementedError as e:
                    _log(f"    (skipped: {e})")
                except Exception as e:  # noqa: BLE001
                    _log(f"    ERROR performing {d.action.value}: "
                         f"{type(e).__name__}: {e}")

                processed += 1
                if not advance_to_next(page):
                    break

            _flush_no_phone()
            _log(f"\n[oat] done — {processed} applicant(s) this run: "
                 + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    except AppStreamBusy:
        _log("[oat] AppStream session busy (another run holds Carlos's "
             "session) — stepping aside; try again shortly")
        return 3
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
    args = p.parse_args(argv)

    live = args.live and not args.dry_run
    return run(live=live, limit=args.limit, debug=args.debug, headed=args.headed)


if __name__ == "__main__":
    sys.exit(main())
