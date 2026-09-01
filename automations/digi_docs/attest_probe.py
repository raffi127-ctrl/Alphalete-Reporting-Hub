"""READ-ONLY: does the Set Status modal still open its attestation sections?

Run:  lucy --machine "Lucy 3" rerun digi_docs_attest_probe --only "Some Name"

WHY (2026-08-31). DRUG TEST stopped expanding and every rep in two runs failed
there, so nobody's Background Check / Drug Test / Service boxes were ticked all
day. _force_expand now works through the plausible toggles instead of guessing
one — but that fix is unit-tested against a fake page, and a fake page cannot
tell us whether it opens the REAL one.

Proving it the ordinary way is not available: the send phase only reaches the
attestation step for someone in REQUIRED ACTION, and after a day of manual
sends nearly everyone is COMPLETED or PENDING. So this opens the modal for one
named person and asks the question directly.

IT SENDS NOTHING AND CLICKS NOTHING THAT MATTERS. It never opens the documents
portal, never generates a bundle, and calls tick_attestations in DRY MODE,
which expands the sections and waits for the boxes without clicking them. Safe
to point at anybody, including people who already have their documents.
"""
from __future__ import annotations

import argparse

from automations.digi_docs import roster, run as _run


def main(argv=None) -> int:
    from automations.digi_docs import ownerville as ov

    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="",
                    help="the one person whose Set Status modal to open. "
                         "Required — this is a probe, not a batch.")
    ap.add_argument("--tab", default=None)
    args = ap.parse_args(argv)
    if not args.only:
        print("⛔ --only <name> is required: this probe opens ONE person's "
              "modal on purpose.")
        return 1

    ws, values = _run._open_tab(args.tab)
    cands = roster.to_send(roster.candidates(values, ws.title))
    want = args.only.strip().lower()
    hits = [c for c in cands if want in c.name.lower()]
    if len(hits) != 1:
        print(f"⛔ --only {args.only!r} matched {len(hits)} people "
              f"({[c.name for c in hits][:4]}) — expected exactly one.")
        return 1
    person = hits[0]
    print(f"{ws.title}: probing {person.name} (READ-ONLY — nothing is sent)\n")

    with ov.session(headless=True) as page:
        modal, matched = ov.open_set_status(page, person.name)
        state = ov.docs_row_state(modal)
        print(f"Onboarding Documents: {state or 'unreadable'}")
        print(f"matched in OwnerVille as: {matched}\n")
        try:
            # dry_run=True expands each section and waits for its boxes, and
            # clicks none of them. Exactly the step that has been failing.
            ticked = ov.tick_attestations(page, modal, dry_run=True)
        except Exception as e:                          # noqa: BLE001
            print(f"\n⛔ STILL BROKEN — {type(e).__name__}: "
                  f"{str(e).splitlines()[0][:160]}")
            print("   The sections above show how far it got.")
            return 2
    print(f"\n✅ every attestation section opened and all {len(ticked)} box(es) "
          f"were found:")
    for t in ticked:
        print(f"   · {t}")
    print("\nNothing was ticked and nothing was sent — this only proves the "
          "sections open.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
