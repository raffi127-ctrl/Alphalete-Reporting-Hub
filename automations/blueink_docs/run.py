"""Send Blue Ink onboarding docs to this week's new starts.

    # who would get docs this week, and who wouldn't and why (writes nothing)
    python -m automations.blueink_docs.run

    # the envelope templates on the account, with their signer role keys
    python -m automations.blueink_docs.run --list-templates

    # one real send, to prove the template and the email look right
    python -m automations.blueink_docs.run --send --limit 1

    # the week's batch
    python -m automations.blueink_docs.run --send

    # refresh 'sent' -> 'complete' in the log as people sign
    python -m automations.blueink_docs.run --sync-status

Dry-run is the default and --send is the only thing that mails anybody.
Creating a Blue Ink bundle launches it immediately -- there is no unsend --
so the ledger is written for each person BEFORE the next one goes out, and a
crash mid-batch can never re-send the people already done.
"""
from __future__ import annotations

import argparse
import sys
from typing import List

from automations.blueink_docs import (blueink, completed, config, ledger,
                                      session_alert,
                                      mark, recent, slack_post,
                                      recent_ui)
from automations.blueink_docs import session as bi_session
from automations.blueink_docs import ui_send
from automations.blueink_docs.roster import (NewStart, current_tab,
                                             final_status_is_unrecognised,
                                             collapse_duplicates, parse_tab,
                                             describe_other_week_charts,
                                             unparsed_email_rows)
from automations.recruiting_report import fill


def _workbook():
    return fill._client().open_by_key(config.SHEET_ID)


def _print_templates() -> int:
    templates = blueink.list_envelope_templates()
    if not templates:
        print("No envelope templates on this Blue Ink account.")
        return 1
    print(f"{len(templates)} envelope template(s) on the account:\n")
    for t in templates:
        print(f"  id:      {t.get('id')}")
        print(f"  name:    {t.get('name')}")
        if t.get("description"):
            print(f"  about:   {t['description']}")
        signers = t.get("signers") or []
        keys = ", ".join(f"{s.get('key')} ({s.get('label')})" for s in signers)
        print(f"  signers: {keys or '-'}")
        docs = ", ".join(d.get("name", "") for d in (t.get("documents") or []))
        print(f"  docs:    {docs or '-'}")
        print()
    print("Put the right id in blueink-creds.json as \"envelope_template_id\", "
          f"and if the signer key isn't {config.SIGNER_KEY!r} update "
          "config.SIGNER_KEY to match.")
    return 0


def _test_send(email: str, name: str, send: bool,
               headless: bool = True) -> int:
    """One packet to a chosen address -- how you check the template, the email
    and the signing flow WITHOUT mailing a real new start.

    Goes through the WEB APP, like every other send here. It used to call the
    API, which needs blueink-creds.json and 403s on this plan anyway -- so the
    one safe way to rehearse a send was itself the only path that couldn't
    run (found 2026-08-24, while trying to prove the send chain before arming
    the Monday job).

    Without --send this still drives the whole wizard and stops at the Send
    button, which is the cheapest way to prove the flow after a Blue Ink UI
    change. The draft it leaves behind delivers nothing.

    Deliberately not logged in the ledger: a test isn't a person's real packet,
    and a stray row there would make the batch skip somebody.
    """
    parts = (name or "").split()
    first = parts[0] if parts else "Test"
    last = " ".join(parts[1:]) or "Signer"
    print(f"Template {config.TEMPLATE_NAME!r} -> {first} {last} <{email}>")
    with bi_session._sync_api()() as p:
        browser, ctx = ui_send.open_browser(p, headless=headless)
        page = ctx.new_page()
        try:
            r = ui_send.send_one(page, first=first, last=last, email=email,
                                 template_name=config.TEMPLATE_NAME,
                                 really_send=send)
        finally:
            browser.close()
    if send:
        print(f"\nSent. Bundle {r.bundle_id} ({r.status}). "
              "Not written to the log -- this was a test.")
    else:
        print(f"\nWalked the whole wizard and stopped at Send "
              f"(bundle {r.bundle_id}). NOTHING WAS SENT. "
              "Add --send to mail this one packet.")
    return 0


def _report(people: List[NewStart], sent_map: dict, tab_title: str):
    """Print the full roll -- who's getting docs, who isn't, why.

    Returns (people to send, people we have ALREADY sent in an earlier week).
    That second list used to be printed here and then dropped on the floor, so
    somebody carried over from last week's tab left no mark anywhere: no green
    on their row, no line in Slack. Their row looked exactly like a row nobody
    had touched, which is what had Megan asking why Le'derius Arnold wasn't
    marked as sent (2026-09-14) -- the same question Jose Laureano prompted on
    2026-08-31, from the other half of the same hold.
    """
    to_send, skipped, dupes = [], [], []
    for p in people:
        if not p.eligible:
            skipped.append(p)
        elif ledger.seen(sent_map, p):
            dupes.append(p)
        else:
            to_send.append(p)

    print(f"Source: 'All in One Local Office - Raf' -> tab {tab_title!r} "
          f"({len(people)} people across "
          f"{max((p.section for p in people), default=0)} section(s))\n")

    print(f"WILL SEND -- {len(to_send)}")
    for p in to_send:
        print(f"  {p.name:<28} {p.email:<38} row {p.row} (sec {p.section})")

    if dupes:
        print(f"\nALREADY SENT -- {len(dupes)} (in {config.LEDGER_TAB})")
        for p in dupes:
            print(f"  {p.name:<28} bundle {ledger.seen(sent_map, p)}")

    if skipped:
        print(f"\nNOT SENDING -- {len(skipped)}")
        for p in skipped:
            print(f"  {p.name:<28} {p.skip_reason}  (row {p.row})")

    unknown = [p for p in to_send
               if final_status_is_unrecognised(p.final_status)]
    if unknown:
        print(f"\n⚠️  {len(unknown)} person(s) have a Final Status nobody has "
              "taught this report about. They ARE in the send list above -- "
              "check that's right before --send:")
        for p in unknown:
            print(f"  {p.name:<28} Final Status: {p.final_status!r}  "
                  f"(row {p.row})")
        print("  If any of these means they're NOT starting, add a marker to "
              "config.FINAL_STATUS_BLOCK_MARKERS; if it's fine, add it to "
              "config.FINAL_STATUS_KNOWN_OK to silence this.")

    no_email = [p for p in skipped if "email" in p.skip_reason]
    if no_email:
        print(f"\n⚠️  {len(no_email)} person(s) have no usable email on the "
              "sheet and can't be sent anything until that's filled in.")
    return to_send, dupes


def _flag_terminated(people: List[NewStart]) -> None:
    """Advisory only -- surface anyone on the shared terminated list before we
    mail them, and never let the check itself take a run down."""
    if not people:
        return
    try:
        from automations.shared import terminated_icds as ti
        _, flag = ti.alert_terminated([p.name for p in people],
                                      report_label="Blue Ink New Start Docs")
        if flag:
            print(f"\n{flag}")
    except Exception:
        pass


REPORT_ID = "blueink_docs"          # the schedule_config key, and the incident
                                    # key (`failure-blueink_docs`). delivery_check
                                    # also tries the dashed spelling by itself.


def _record_run(sent_names, failed_names, *, dry_run: bool) -> None:
    """Tell the Hub -- and delivery_check -- what this run actually DELIVERED.

    WHY (2026-09-14). This report wrote no manifest and had no `verify` wired,
    so delivery_check could only ever answer UNKNOWN, and UNKNOWN is explicitly
    not allowed to close a ticket. Its corrections-channel incident therefore
    stayed :pending: no matter what happened: a CLEAN rerun at 9:17 posted
    "ran clean, but nothing can confirm it DELIVERED, so this stays open".
    Megan saw a pending ticket for a report that had already delivered.

    A manifest is the honest answer, not `close_on: exit_zero` -- this report
    CAN prove delivery, because it writes a ledger row per person as it goes.
    So: who went out, who didn't, and the args that retry only the stragglers.

    retry_args is a bare --send on purpose. The ledger already makes a rerun
    skip everyone who has a bundle id, so "run it again" IS "retry only the
    failures" here -- and it stays right for any number of them, which
    `--only <name>` (one person) could not.
    """
    try:
        from automations.shared import run_manifest
        run_manifest.write_manifest(
            REPORT_ID,
            kind="new start",
            failed=list(failed_names),
            succeeded=list(sent_names),
            retry_args=["--send"],
            note=("%d sent, %d failed" % (len(sent_names), len(failed_names))),
            dry_run=dry_run)
    except Exception as exc:                       # noqa: BLE001
        # Bookkeeping. It must never be the reason a run that mailed the right
        # people reports itself as broken.
        print(f"\n(couldn't write the run manifest: {exc})")


def _one_line(exc: Exception) -> str:
    """The sentence a human needs, without Playwright's log dump.

    A browser timeout stringifies as its message plus twenty lines of
    "=========== logs ===========" internals. That went into the ledger note
    AND into Slack, so the 2026-09-14 post spent three paragraphs saying
    "Timeout 90000ms exceeded" three times. The first line carries all of it.
    """
    first = str(exc).strip().splitlines()
    return first[0].strip() if first else exc.__class__.__name__


def _send_one_with_retry(page, person, template, really_send):
    """One person, with a second attempt at anything that failed before Send.

    Every failure short of the Send click leaves the envelope a DRAFT, and a
    draft mails nobody -- so a retry costs one stranded draft and buys back a
    person who would otherwise be on the "send these by hand" list. The one
    exception is SendUncertain: Send was already clicked there, and a retry is
    the only mistake in this file that cannot be taken back.
    """
    try:
        return ui_send.send_one(page, first=person.first, last=person.last,
                                email=person.email, template_name=template,
                                really_send=really_send)
    except ui_send.SendUncertain:
        raise
    except Exception as exc:                       # noqa: BLE001
        print(f"     (first attempt failed: {_one_line(exc)} -- retrying once)")
        return ui_send.send_one(page, first=person.first, last=person.last,
                                email=person.email, template_name=template,
                                really_send=really_send)


def _send_via_ui(workbook, worksheet, people: List[NewStart],
                 really_send: bool, headless: bool = True) -> int:
    """The live path. One browser for the whole batch -- relaunching per person
    would roughly double a run that already takes ~a minute each."""
    rows, failures, sent = [], 0, []
    problems: List[tuple] = []
    sent_failed: List[str] = []        # send failures ONLY -- `problems` later
                                       # collects skips and held-backs too, and
                                       # neither of those is a failed delivery
    template = config.TEMPLATE_NAME
    with bi_session._sync_api()() as p:
        browser, ctx = ui_send.open_browser(p, headless=headless)
        page = ctx.new_page()
        try:
            for i, person in enumerate(people, 1):
                try:
                    r = _send_one_with_retry(page, person, template, really_send)
                    print(f"  [{i}/{len(people)}] {r.status:<26} "
                          f"{person.name:<26} {person.email:<36} {r.bundle_id}")
                    if really_send:
                        rows.append(ledger.row_for(person, r.bundle_id, r.status))
                        sent.append(person)
                except Exception as exc:          # one bad row can't stop the batch
                    failures += 1
                    why = _one_line(exc)
                    problems.append((person.name, why[:160]))
                    sent_failed.append(person.name)
                    print(f"  [{i}/{len(people)}] FAILED  {person.name:<26} {why}")
                    if really_send:
                        rows.append(ledger.row_for(person, "", "failed", why[:200]))
                finally:
                    # Per-person, before the next one starts: a crash mid-batch
                    # must never leave a sent person looking unsent.
                    if really_send and rows:
                        ledger.record(workbook, rows[-1:])
        finally:
            browser.close()

    if really_send:
        try:
            tinted = mark.highlight(worksheet, sent)
            if tinted:
                print(f"\nColoured {tinted} Blue Ink cell(s) light blue on "
                      f"{worksheet.title!r}.")
        except Exception as exc:
            print(f"\nSends went out, but the green highlight failed: {exc}\n"
                  "Nothing to re-send -- rerun with --highlight-only to tint.")
    # The NAMES, not just a count: the manifest has to say who delivered and
    # who didn't, and a count can only be turned back into names by slicing
    # to_send -- which silently attributes the wrong people, because the ones
    # that failed are scattered through the batch, not at the end of it.
    return failures, len(sent), problems, [p.name for p in sent], sent_failed


def _send(workbook, worksheet, people: List[NewStart], is_test: bool) -> int:
    rows, failures, sent = [], 0, []
    template = config.template_id()
    for p in people:
        try:
            bundle = blueink.send_from_template(
                name=p.name, email=p.email, phone=p.phone,
                template_id_=template, is_test=is_test)
            print(f"  sent  {p.name:<28} {p.email:<38} bundle {bundle.bundle_id}")
            rows.append(ledger.row_for(p, bundle.bundle_id, bundle.status,
                                       "test bundle" if is_test else ""))
            sent.append(p)
        except Exception as exc:                      # keep the batch going
            failures += 1
            print(f"  FAIL  {p.name:<28} {exc}")
            rows.append(ledger.row_for(p, "", "failed", str(exc)[:200]))
        finally:
            # Written per-person, not at the end: a crash halfway through must
            # not leave already-sent people looking unsent on the next run.
            ledger.record(workbook, rows[-1:])

    # Light green on the first name of everyone who actually got docs -- only
    # after the sends, and only for the ones that succeeded, so the tint on the
    # sheet always means "this person has their packet".
    try:
        tinted = mark.highlight(worksheet, sent)
        if tinted:
            print(f"\nColoured {tinted} Blue Ink cell(s) light blue on "
                  f"{worksheet.title!r}.")
    except Exception as exc:
        print(f"\nSends went out, but the green highlight failed: {exc}\n"
              "Nothing to re-send -- the log is the record; just tint by hand "
              "or rerun with --highlight-only.")
    return failures


def _handle_held(worksheet, to_send_all: List[NewStart], held: dict,
                 carried: List[tuple] = None):
    """Deal with everyone Blue Ink already shows a packet for.

    They split in two, because a reader needs opposite things from them:

      "same name ..."  an ambiguous match nobody has confirmed. That IS a
                       problem -- it gets tagged for a human, same as a failure.
      everything else  a clean hit on the person's own address. Not a failure:
                       they already have their paperwork, and there is nothing
                       for anyone to do.

    The clean ones get a DEEPER green than a fresh send. Without any mark their
    row looks identical to somebody nobody touched, which is exactly what had
    Megan asking why Jose Laureano was skipped (2026-08-31); and the shade
    differs from the send tint because a packet from an earlier week usually
    means a rescheduled start date.

    `carried` is the same thing reached by the other road: [(person, verdict)]
    for people OUR OWN ledger already has a send for, from an earlier week.
    Blue Ink's lookup never sees them -- they are dropped before the screen
    runs -- so without this they were the one kind of hold that stayed
    invisible, which is the bug Megan hit on 2026-09-14.

    Returns ([(name, verdict)] for the clean ones, [(name, why)] to add to
    problems).
    """
    ok, problems, verdict = [], [], {}
    for pp in to_send_all:
        why = held.get(pp.email.strip().lower(), "")
        if not why:
            continue
        if why.startswith("same name"):
            problems.append((pp.name, why))
        else:
            ok.append(pp)
            verdict[id(pp)] = why
    for pp, why in (carried or []):
        ok.append(pp)
        verdict[id(pp)] = why
    if ok:
        try:
            tinted = mark.highlight(worksheet, ok, color=mark.CARRIED_BLUE)
            if tinted:
                print(f"\nTinted {tinted} carried-over packet(s) deeper blue "
                      f"on {worksheet.title!r}.")
        except Exception as exc:
            # Cosmetic. Never worth failing a run that mailed the right people.
            print(f"\nCouldn't tint the carried-over packets: {exc}")
    return ([(pp.name, verdict.get(id(pp), "")) for pp in ok], problems)


def _repaint(workbook, worksheet, people: List[NewStart]) -> int:
    """Re-apply the Blue Ink colours to the whole tab, by rule, every sweep:

      box ticked                          green        (signed)
      we sent it off THIS tab             light blue   (waiting on them)
      we sent it in an EARLIER week       deeper blue  (carried over, waiting --
                                                     only if still starting)
      anyone else                         left exactly as it is

    WHY every sweep and not just at send time (2026-09-21): Google silently
    SKIPS formatting on rows a filter has hidden -- the request succeeds and
    the cell doesn't change. The 9.21 tab had 22 rows filtered out, so 14
    cells kept the old colour through a repaint that reported 49 done. The
    sweep can't clear the team's filter and shouldn't, so it just re-applies
    the rule; a hidden row catches up on the first sweep after it's shown.
    Idempotent and one batch, so running it every two hours costs one write.
    """
    done, sent, carried = _colour_groups(workbook, worksheet, people)
    return (mark.green(worksheet, done) + mark.highlight(worksheet, sent)
            + mark.highlight(worksheet, carried, color=mark.CARRIED_BLUE))


def _colour_groups(workbook, worksheet, people: List[NewStart]):
    """(signed, sent off this tab, carried over) -- who gets which colour."""
    rows = ledger.read(workbook)
    sent_map = ledger.already_sent(workbook, rows=rows)
    this_tab = {r[ledger.COL_NAME].strip().lower() for r in rows
                if len(r) > ledger.COL_BUNDLE and r[ledger.COL_WEEK].strip() == worksheet.title
                and r[ledger.COL_BUNDLE].strip()}
    done, sent, carried = [], [], []
    for pp in people:
        if not (pp.row and pp.blueink_col):
            continue
        if mark.is_ticked(pp):
            done.append(pp)
        elif pp.name.strip().lower() in this_tab:
            sent.append(pp)
        elif pp.eligible and ledger.seen(sent_map, pp):
            # eligible: an OLD packet on someone who has since declined or quit
            # is not "waiting on them" -- Antashia Rich, 9.21, sent 9/7 and
            # Declined on Friday. Their row keeps whatever it has.
            carried.append(pp)
    return done, sent, carried


def _untick_check(workbook, worksheet, people: List[NewStart]) -> List[NewStart]:
    """Clear any Blue Ink box that Blue Ink itself contradicts, and recolour it.

    Megan 2026-09-22, after the OV sweep ticked a column of boxes it never
    meant to (Jeremiah Ireland's Blue Ink read "signed", in red). A ticked box
    is a claim -- "this person signed" -- and Blue Ink is the only thing that
    can confirm it. So: ticked, but no signed packet in Blue Ink's last 45 days,
    means the tick comes off and the cell goes back to blue (still waiting) or
    white (no packet we know of). Refuses to act on a bad read -- see
    completed.wrongly_ticked for the two valves -- and prints every name it
    clears, so nobody has to wonder where a tick went.
    """
    try:
        signed = completed.signed_recently(people)
    except Exception as exc:                       # noqa: BLE001
        print(f"Untick check skipped -- couldn't read Blue Ink's signed list "
              f"({exc}). A failed read is not a reason to clear anything.")
        return []
    wrong = completed.wrongly_ticked(people, signed)
    if not wrong:
        return []
    completed.untick(worksheet, wrong)
    print(f"Unticked {len(wrong)} box(es) Blue Ink shows NOT signed:")
    for pp in wrong:
        print(f"  row {pp.row:>3}  {pp.name}")
    done, sent, carried = _colour_groups(workbook, worksheet, wrong)
    known = {id(pp) for pp in sent + carried}
    rest = [pp for pp in wrong if id(pp) not in known]
    mark.highlight(worksheet, sent)
    mark.highlight(worksheet, carried, color=mark.CARRIED_BLUE)
    mark.clear(worksheet, rest)
    return wrong


def _sync_completed(worksheet, people: List[NewStart],
                    headless: bool = True, use_api: bool = True) -> int:
    """Tick the Blue Ink checkbox -- and turn the cell green -- for anyone
    Blue Ink shows as signed. Boxes already ticked (by us earlier, or by hand)
    go green too; they're skipped by the lookup, so this is their only chance."""
    done = completed.find_completed(people, headless=headless, use_api=use_api)
    n = completed.tick(worksheet, people, done) if done else 0
    try:
        completed.green_ticked(worksheet, people)
    except Exception as exc:                       # noqa: BLE001 -- cosmetic
        print(f"Couldn't turn the already-ticked boxes green: {exc}")
    return n


def _highlight_only(workbook, worksheet, people: List[NewStart]) -> int:
    """Back-fill the blue on everyone the log says already has their docs --
    for when a batch sent fine but the colour didn't land. Anyone already
    signed goes green instead (mark.highlight decides)."""
    sent_map = ledger.already_sent(workbook)
    done = [p for p in people if ledger.seen(sent_map, p)]
    if not done:
        print("Nobody on this tab is in the log yet -- nothing to tint.")
        return 0
    print(f"Colouring {len(done)} Blue Ink cell(s) on {worksheet.title!r} (blue = sent, green = signed):")
    for p in done:
        print(f"  {p.name:<28} row {p.row}")
    mark.highlight(worksheet, done)
    return 0


def _sync_status(workbook) -> int:
    updates, checked = {}, 0
    for i, row in enumerate(ledger.read(workbook), start=2):
        row = (row + [""] * len(ledger.HEADER))[:len(ledger.HEADER)]
        bundle_id, status = row[ledger.COL_BUNDLE].strip(), row[ledger.COL_STATUS].strip()
        if not bundle_id or status in ("complete", "cancelled", "expired", "declined"):
            continue
        try:
            now = blueink.bundle_status(bundle_id)
        except Exception as exc:
            print(f"  could not read {bundle_id}: {exc}")
            continue
        checked += 1
        if now != status:
            print(f"  {row[ledger.COL_NAME]:<28} {status} -> {now}")
            updates[i] = now
    ledger.update_statuses(workbook, updates)
    print(f"\nChecked {checked} bundle(s); updated {len(updates)}.")
    return 0


def main(argv=None) -> int:
    try:
        return _main(argv)
    except (blueink.BlueInkError, RuntimeError) as exc:
        # Setup problems (no API key, no template picked, a 401) are for a
        # human to fix -- print the sentence, not a traceback.
        print(f"\n{exc}", file=sys.stderr)
        return 2


def _a_logged_send(rows: list) -> str:
    """One address this report has already sent and logged -- the positive
    canary for the duplicate check (see recent_ui._canaries).

    Reads the ledger ROWS, newest first, so the canary is a packet Blue Ink is
    certainly still listing. It used to take the first key containing "@" out
    of `already_sent`, which is a dict built oldest-row-first: that address was
    always the first person this report ever sent (Angelica Pedroza, 2026-08-24)
    and it only got older. See recent_ui.found_rows for the Monday that cost.

    Empty is fine: on the very first run nothing has been logged yet, and the
    check says so.
    """
    return ledger.a_recent_send(rows, recent_ui.LOOKBACK_DAYS)


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--send", action="store_true",
                    help="actually send. Without it nothing leaves the building.")
    ap.add_argument("--dry-run", action="store_true",
                    help="explicit no-op (the default anyway)")
    ap.add_argument("--tab", default="",
                    help="a specific week's tab, e.g. 'D2D OBCL 8.24'. "
                         "Default: the newest dated tab.")
    ap.add_argument("--limit", type=int, default=0,
                    help="send to at most N people (use --limit 1 first)")
    ap.add_argument("--only", default="",
                    help="just this person, by name")
    ap.add_argument("--test-bundle", action="store_true",
                    help="mark the bundle is_test in Blue Ink (does not count "
                         "against the plan; still emails the signer)")
    ap.add_argument("--list-templates", action="store_true",
                    help="show the account's envelope templates and exit")
    ap.add_argument("--sync-status", action="store_true",
                    help="refresh bundle statuses in the log")
    ap.add_argument("--test-to", default="",
                    help="send ONE packet to this address instead of anyone on "
                         "the roster, to prove the template before a real "
                         "batch. Nothing is written to the log.")
    ap.add_argument("--test-name", default="Test Signer",
                    help="name on the --test-to packet")
    ap.add_argument("--walk", action="store_true",
                    help="on a dry run, actually drive the wizard for the first "
                         "person up to (not including) Send -- proves the UI "
                         "path still works without mailing anyone")
    ap.add_argument("--via", choices=("ui", "api"), default="ui",
                    help="'ui' (default) drives the web app and draws on the "
                         "UNLIMITED Envelopes bucket. 'api' is faster but every "
                         "bundle costs a Bulk Envelope -- 50/YEAR on this plan, "
                         "already spent, so it 403s.")
    ap.add_argument("--sweep-browser", action="store_true",
                    help="make --sync-completed read the SIGNED list off the "
                         "web app instead of the API. Debugging only: the API "
                         "is the default because it cannot be logged out, and "
                         "it already falls back here by itself if there is no "
                         "key. Nothing to do with --via, which is about "
                         "SENDING.")
    ap.add_argument("--headed", action="store_true",
                    help="show the browser while the UI path runs")
    ap.add_argument("--slack", action="store_true",
                    help="actually post the summary to Slack. Without it the "
                         "message is printed and nothing is posted.")
    ap.add_argument("--no-dedupe", action="store_true",
                    help="skip the check against Blue Ink's own send history. "
                         "Only if you're certain nobody was hand-sent -- this "
                         "check is what stops duplicate packets.")
    ap.add_argument("--probe-sent", action="store_true",
                    help="describe Blue Ink's own Sent list on this "
                         "machine and exit -- how the web-app duplicate "
                         "check gets mapped. Reads nothing else, sends "
                         "nothing, needs no API key.")
    ap.add_argument("--sync-completed", action="store_true",
                    help="send nothing; just tick the Blue Ink checkbox for "
                         "anyone whose packet is now signed")
    ap.add_argument("--highlight-only", action="store_true",
                    help="send nothing; just light-green the first name of "
                         "everyone the log already shows as sent")
    args = ap.parse_args(argv)

    if args.list_templates:
        return _print_templates()

    if args.probe_sent:
        return recent_ui.probe(email=args.only.strip(),
                               headless=not args.headed)

    if args.test_to:
        return _test_send(args.test_to, args.test_name, args.send,
                          headless=not args.headed)

    workbook = _workbook()
    if args.sync_status:
        return _sync_status(workbook)

    ws = current_tab(workbook, args.tab)
    raw_values = ws.get_all_values()
    people = parse_tab(raw_values, ws.title)
    for line in describe_other_week_charts(raw_values, ws.title):
        print(line)
    before = len(people)
    people = collapse_duplicates(people)
    if before != len(people):
        print(f"({before - len(people)} duplicate row(s) on this tab collapsed "
              f"to the person's most complete entry.)")
    if args.only:
        want = args.only.strip().lower()
        people = [p for p in people if want in p.name.lower()]
        if not people:
            print(f"Nobody matching {args.only!r} on {ws.title!r}.")
            return 1

    if args.sync_completed:
        # THE TICKING GOES THROUGH THE API, and needs no browser session at all
        # (Megan's call, 2026-09-09). The browser session on Lucy 2 expired
        # twice in a fortnight, each time silently stopping the marking, and it
        # cannot be renewed remotely -- a login is Google SSO and nothing here
        # types a password. Reads over the API don't touch the send quota, so
        # the sweep simply stops depending on the fragile thing.
        # Colours first, ticks second: _repaint works from the boxes as they
        # were read, so anything that ticks in THIS sweep must be greened after
        # it, not painted back to blue by a stale read.
        try:
            _repaint(workbook, ws, people)
        except Exception as exc:                   # noqa: BLE001 -- cosmetic
            print(f"Couldn't re-apply the Blue Ink colours: {exc}")
        try:
            n = _sync_completed(ws, people, headless=not args.headed,
                                use_api=not args.sweep_browser)
        except Exception as exc:
            # Only reachable when the API route was unavailable too (no
            # blueink-creds.json here) AND the browser fallback couldn't sign
            # in -- i.e. the machine genuinely can't see Blue Ink by any route.
            if session_alert.looks_dead(exc):
                session_alert.alert_dead(
                    exc, what_failed="the completed sweep",
                    dry_run=not args.slack)
            raise
        print(f"Checked off {n} completed packet(s) in {config.COL_BLUEINK!r} "
              f"on {ws.title!r}.")
        # AFTER the ticks, and API-only: the browser route can't read far
        # enough back to know an old tick is right, and a wrong untick fights
        # whoever ticked the box.
        if not args.sweep_browser:
            _untick_check(workbook, ws, people)

        # The browser session still matters -- but for MONDAY'S SEND, which is
        # the one thing the API can't do (its bundles bill as Bulk Envelopes,
        # 50/year, long spent). So it's checked here, ADVISORY: a dead session
        # is worth someone's attention days early, and is not a reason to fail
        # a sweep that just did its job. The alert dedupes to one post per
        # outage, so this cannot nag every two hours.
        try:
            completed.verify_ui_session(headless=not args.headed)
            session_alert.clear(dry_run=not args.slack)
        except Exception as exc:
            if session_alert.looks_dead(exc):
                print("\n⚠️  Ticking is fine, but this machine can't sign in to "
                      "Blue Ink, so MONDAY'S SEND would fail. Raising it now "
                      "rather than on Monday morning.")
                session_alert.alert_dead(
                    exc, what_failed="Monday's 7:30am send (the sweep itself "
                                     "is unaffected -- it reads via the API)",
                    send_at_risk=True, dry_run=not args.slack)
            else:
                print(f"\n(couldn't check send-readiness: {exc})")
        return 0

    if args.highlight_only:
        return _highlight_only(workbook, ws, people)

    # Anyone the parser didn't see is someone who silently gets no docs.
    stray = unparsed_email_rows(raw_values, people, ws.title)
    if stray:
        print(f"⚠️  {len(stray)} row(s) hold an email but weren't read as "
              f"people. If a section was added or reworded, they are being "
              f"MISSED -- check before trusting this list:")
        for rownum, email, label in stray[:12]:
            print(f"     row {rownum}: {email}  |  {label}")
        print()

    # One read of the ledger tab answers both questions asked of it below:
    # who has already been sent, and which address the canary should ask about.
    ledger_rows = ledger.read(workbook)
    sent_map = ledger.already_sent(workbook, rows=ledger_rows)
    to_send, already = _report(people, sent_map, ws.title)

    # Carried over from an earlier week: our ledger already has their packet,
    # so they are correctly not sent again -- but they still have to SHOW. The
    # verdict is worded like the screen's ("Sent 9/7/26") so Slack renders both
    # kinds of hold with one phrase.
    when_map = ledger.sent_when(ledger_rows)
    carried = [(pp, "Sent %s" % ledger.when(when_map, pp)) for pp in already
               if ledger.when(when_map, pp)]

    # Blue Ink's OWN history, not just our log: the team hand-sends too, and a
    # person with a live packet must not get a second one whoever sent the
    # first. This is why Angelica Pedroza got two on 2026-08-24.
    to_send_all = list(to_send)
    held: dict = {}
    if not args.no_dedupe and to_send:
        print(f"\nChecking Blue Ink's own list for packets already sent "
              f"to these {len(to_send)} (last {recent_ui.LOOKBACK_DAYS} days, "
              f"about 10s each)...")
        try:
            blocked = recent_ui.screen(
                to_send, headless=not args.headed,
                known_sent=_a_logged_send(ledger_rows))
        except Exception as exc:
            # Only a REAL send has anything to lose here. A dry run mails
            # nobody, so there is no duplicate to prevent and no reason to
            # fail -- on 2026-08-24 a --dry-run came back FAILED on the Hub
            # for a check the preview itself never needed. An expired Blue
            # Ink session or a moved search box lands here the same way.
            print(f"\nCouldn't read Blue Ink's list ({exc}).")
            if session_alert.looks_dead(exc) and args.send:
                # Worse here than in the sweep: the send REFUSES without this
                # check, so a dead session on a Monday means nobody gets docs.
                session_alert.alert_dead(
                    exc, what_failed="the Monday 7:30am send",
                    send_at_risk=True, dry_run=not args.slack)
            if args.send:
                print("REFUSING to send -- without that check this could "
                      "duplicate packets your team already sent by hand. "
                      "Rerun when Blue Ink answers, or pass --no-dedupe if "
                      "you're certain.")
                return 2
            print("Not fatal on a dry run -- nothing is being sent. But the "
                  "WILL SEND list above is UNSCREENED: some of those people "
                  "may already have a packet the team sent by hand, and this "
                  "has to work before --send will do anything.")
            blocked = {}
        held = dict(blocked)
        if blocked:
            print(f"\nALREADY HAVE A PACKET -- {len(blocked)} (skipping)")
            for pp in to_send:
                why = blocked.get(pp.email.strip().lower())
                if why:
                    print(f"  {pp.name:<28} {why}")
            to_send = [pp for pp in to_send
                       if pp.email.strip().lower() not in blocked]
            print(f"\nStill to send: {len(to_send)}")
            # Name them. The WILL SEND list above was printed BEFORE the
            # screen, so on a morning like 2026-08-24 -- 51 of 52 already
            # had packets -- a bare count leaves the reader scrolling to
            # work out who is actually left.
            for pp in to_send:
                print(f"  {pp.name:<28} {pp.email:<38} row {pp.row}")

    if args.limit:
        to_send = to_send[:args.limit]
    _flag_terminated(to_send)

    if not args.send:
        print(f"\nDRY RUN -- nothing sent. Add --send to mail these "
              f"{len(to_send)} people.")
        if args.walk and to_send:
            print("\nWalking the real wizard for the first person, stopping at "
                  "the Send button (leaves a harmless draft):")
            _send_via_ui(workbook, ws, to_send[:1], really_send=False,
                         headless=not args.headed)
        return 0
    if not to_send:
        print("\nNothing to send.")
        # A week where EVERYONE already has a packet is a real outcome, not an
        # empty one -- the 2026-08-24 screen cut 58 people to 3, so 3 to 0 is
        # one quiet Monday away. Falling straight out here would tint nothing
        # and say nothing in Slack, and a silent channel reads exactly like a
        # job that never fired. So mark them and post anyway.
        held_pairs, held_problems = _handle_held(ws, to_send_all, held, carried)
        if held_pairs or held_problems:
            try:
                _sync_completed(ws, people)
            except Exception as exc:
                print(f"Couldn't refresh completed packets: {exc}")
            try:
                slack_post.post(0, held_problems, held=held_pairs,
                                dry_run=not args.slack)
            except Exception as exc:
                print(f"\nThe Slack summary failed ({exc}).")
        # A week where everyone already has their packet IS a delivered run --
        # the same outcome as sending, reached by a shorter road. Saying so
        # here is what stops the ticket hanging open on a quiet Monday.
        _record_run([p.name for p in to_send_all], [], dry_run=not args.send)
        return 0

    if args.via == "api":
        print(f"\nSENDING to {len(to_send)} people via the API"
              f"{' (test bundles)' if args.test_bundle else ''}...")
        failures = _send(workbook, ws, to_send, args.test_bundle)
    else:
        print(f"\nSENDING to {len(to_send)} people through the web app "
              f"(~1 min each, so roughly {max(1, len(to_send))} minutes)...")
        failures, sent_count, problems, sent_names, failed_names = _send_via_ui(
            workbook, ws, to_send, really_send=True, headless=not args.headed)

        # Anyone who SHOULD have docs and doesn't. Deliberate exclusions (quit,
        # failed background, declined) are the report working correctly, so
        # they stay out -- listing 14 of those every Monday would bury the one
        # or two names that actually need somebody.
        for pp in people:
            if pp.eligible or "email" not in pp.skip_reason:
                continue
            problems.append((pp.name, pp.skip_reason))
        held_pairs, held_problems = _handle_held(ws, to_send_all, held, carried)
        problems += held_problems

        # The Blue Ink column is where the green tint and the signed checkbox
        # go. Missing means those marks can't be written -- worth saying out
        # loud, but never a reason to withhold somebody's paperwork.
        warnings = []
        if any(not pp.blueink_col for pp in to_send):
            warnings.append(
                "No *%s* column on `%s`, so sent packets could not be marked "
                "green or checked off. The sends themselves went out fine."
                % (config.COL_BLUEINK, ws.title))

        # Tick anyone whose packet Blue Ink now shows as SIGNED. Advisory: a
        # failure here leaves the sheet a little stale, nothing worse.
        try:
            ticked = _sync_completed(ws, people)
            if ticked:
                print(f"Checked off {ticked} completed packet(s) in "
                      f"{config.COL_BLUEINK!r}.")
        except Exception as exc:
            print(f"Couldn't refresh completed packets: {exc}")
            warnings.append("Couldn't refresh the signed/completed checkboxes: "
                            "%s" % str(exc)[:120])

        try:
            slack_post.post(sent_count, problems, warnings=warnings,
                            held=held_pairs, dry_run=not args.slack)
        except Exception as exc:
            print(f"\nThe Slack summary failed ({exc}). The sends themselves "
                  "are fine and logged -- this is only the notification.")
    if args.via != "api":
        _record_run(sent_names, failed_names, dry_run=False)
    print(f"\nDone: {len(to_send) - failures} sent, {failures} failed. "
          f"Logged in the {config.LEDGER_TAB!r} tab.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
