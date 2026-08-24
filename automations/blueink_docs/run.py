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

from automations.blueink_docs import blueink, config, ledger, mark, recent
from automations.blueink_docs import session as bi_session
from automations.blueink_docs import ui_send
from automations.blueink_docs.roster import (NewStart, current_tab,
                                             final_status_is_unrecognised,
                                             parse_tab)
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


def _test_send(email: str, name: str, send: bool) -> int:
    """One packet to a chosen address -- how you check the template, the
    subject line and the signing flow WITHOUT mailing a real new start.

    Deliberately not logged in the ledger: a test isn't a person's real packet,
    and a stray row there would make the batch skip somebody.
    """
    tid = config.template_id()
    print(f"Template {tid} -> {name} <{email}>")
    if not send:
        print("\nDRY RUN -- nothing sent. Add --send to mail this one packet.")
        return 0
    bundle = blueink.send_from_template(name=name, email=email, template_id_=tid)
    print(f"\nSent. Bundle {bundle.bundle_id} ({bundle.status}). "
          "Not written to the log -- this was a test.")
    return 0


def _report(people: List[NewStart], sent_map: dict, tab_title: str) -> List[NewStart]:
    """Print the full roll -- who's getting docs, who isn't, why -- and return
    the people to send to."""
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
    return to_send


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


def _send_via_ui(workbook, worksheet, people: List[NewStart],
                 really_send: bool, headless: bool = True) -> int:
    """The live path. One browser for the whole batch -- relaunching per person
    would roughly double a run that already takes ~a minute each."""
    rows, failures, sent = [], 0, []
    template = config.TEMPLATE_NAME
    with bi_session._sync_api()() as p:
        browser, ctx = ui_send.open_browser(p, headless=headless)
        page = ctx.new_page()
        try:
            for i, person in enumerate(people, 1):
                try:
                    r = ui_send.send_one(page, first=person.first, last=person.last,
                                         email=person.email, template_name=template,
                                         really_send=really_send)
                    print(f"  [{i}/{len(people)}] {r.status:<26} "
                          f"{person.name:<26} {person.email:<36} {r.bundle_id}")
                    if really_send:
                        rows.append(ledger.row_for(person, r.bundle_id, r.status))
                        sent.append(person)
                except Exception as exc:          # one bad row can't stop the batch
                    failures += 1
                    print(f"  [{i}/{len(people)}] FAILED  {person.name:<26} {exc}")
                    if really_send:
                        rows.append(ledger.row_for(person, "", "failed", str(exc)[:200]))
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
                print(f"\nTinted {tinted} first name(s) light green on "
                      f"{worksheet.title!r}.")
        except Exception as exc:
            print(f"\nSends went out, but the green highlight failed: {exc}\n"
                  "Nothing to re-send -- rerun with --highlight-only to tint.")
    return failures


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
            print(f"\nTinted {tinted} first name(s) light green on "
                  f"{worksheet.title!r}.")
    except Exception as exc:
        print(f"\nSends went out, but the green highlight failed: {exc}\n"
              "Nothing to re-send -- the log is the record; just tint by hand "
              "or rerun with --highlight-only.")
    return failures


def _highlight_only(workbook, worksheet, people: List[NewStart]) -> int:
    """Back-fill the green on everyone the log says already has their docs --
    for when a batch sent fine but the tint didn't land."""
    sent_map = ledger.already_sent(workbook)
    done = [p for p in people if ledger.seen(sent_map, p)]
    if not done:
        print("Nobody on this tab is in the log yet -- nothing to tint.")
        return 0
    print(f"Tinting {len(done)} first name(s) light green on {worksheet.title!r}:")
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
    ap.add_argument("--headed", action="store_true",
                    help="show the browser while the UI path runs")
    ap.add_argument("--no-dedupe", action="store_true",
                    help="skip the check against Blue Ink's own send history. "
                         "Only if you're certain nobody was hand-sent -- this "
                         "check is what stops duplicate packets.")
    ap.add_argument("--highlight-only", action="store_true",
                    help="send nothing; just light-green the first name of "
                         "everyone the log already shows as sent")
    args = ap.parse_args(argv)

    if args.list_templates:
        return _print_templates()

    if args.test_to:
        return _test_send(args.test_to, args.test_name, args.send)

    workbook = _workbook()
    if args.sync_status:
        return _sync_status(workbook)

    ws = current_tab(workbook, args.tab)
    people = parse_tab(ws.get_all_values(), ws.title)
    if args.only:
        want = args.only.strip().lower()
        people = [p for p in people if want in p.name.lower()]
        if not people:
            print(f"Nobody matching {args.only!r} on {ws.title!r}.")
            return 1

    if args.highlight_only:
        return _highlight_only(workbook, ws, people)

    to_send = _report(people, ledger.already_sent(workbook), ws.title)

    # Blue Ink's OWN history, not just our log: the team hand-sends too, and a
    # person with a live packet must not get a second one whoever sent the
    # first. This is why Angelica Pedroza got two on 2026-08-24.
    if not args.no_dedupe and to_send:
        print(f"\nChecking Blue Ink for packets already sent to these "
              f"{len(to_send)} (last {recent.LOOKBACK_DAYS} days)...")
        try:
            blocked = recent.screen(to_send)
        except Exception as exc:
            # Only a REAL send has anything to lose here. A dry run mails
            # nobody, so there is no duplicate to prevent and no reason to
            # fail -- on 2026-08-24 a --dry-run on Lucy 2 came back FAILED on
            # the Hub purely because that machine has no blueink-creds.json,
            # which the preview itself never needed.
            print(f"\nCouldn't check Blue Ink's history ({exc}).")
            if args.send:
                print("REFUSING to send -- without that check this could "
                      "duplicate packets your team already sent by hand. "
                      "Rerun when Blue Ink responds, or pass --no-dedupe if "
                      "you're certain.")
                return 2
            print("Not fatal on a dry run -- nothing is being sent. But the "
                  "WILL SEND list above is UNSCREENED: some of those people "
                  "may already have a packet the team sent by hand, and this "
                  "has to work before --send will do anything.")
            blocked = {}
        if blocked:
            print(f"\nALREADY HAVE A PACKET -- {len(blocked)} (skipping)")
            for pp in to_send:
                bid = blocked.get(pp.email.strip().lower())
                if bid:
                    print(f"  {pp.name:<28} bundle {bid}")
            to_send = [pp for pp in to_send
                       if pp.email.strip().lower() not in blocked]
            print(f"\nStill to send: {len(to_send)}")

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
        return 0

    if args.via == "api":
        print(f"\nSENDING to {len(to_send)} people via the API"
              f"{' (test bundles)' if args.test_bundle else ''}...")
        failures = _send(workbook, ws, to_send, args.test_bundle)
    else:
        print(f"\nSENDING to {len(to_send)} people through the web app "
              f"(~1 min each, so roughly {max(1, len(to_send))} minutes)...")
        failures = _send_via_ui(workbook, ws, to_send, really_send=True,
                                headless=not args.headed)
    print(f"\nDone: {len(to_send) - failures} sent, {failures} failed. "
          f"Logged in the {config.LEDGER_TAB!r} tab.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
