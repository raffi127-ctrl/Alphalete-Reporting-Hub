"""Work out which Blue Ink form field is which -- ONCE -- and remember it.

Blue Ink's API hands back every filled field of a signed packet
(`GET /bundles/<id>/data/`), but the fields on these three templates were never
given labels: what comes back is `{"field_key": "inp007-hlXIf", "value": "..."}`
and nothing else. So the values are all there and none of them are named.

Rather than guess at runtime -- which is how a phone number ends up typed into
an SSN box -- the mapping is worked out once, from SEVERAL already-signed
packets at the same time, and written to `field_map.json`:

    "UNIVERSAL I9 MASTER FORM": {"inp001-p8vrb": "last", ...}

A key only earns a name if it means the same thing in EVERY sample it appears
in. `inp001` holding the signer's surname in eight packets out of eight is a
fact; holding it in one is a coincidence. Anything that can't clear that bar is
left unnamed and reported, so a human names it (or leaves it alone) instead of
the runner inventing an answer.

WHAT IS IN THE FILE: field keys and semantic names only. No values, ever --
this repo is public. `field_map.json` is safe to commit; the packets it was
derived from are not, and never leave the machine.

    python -m automations.apex_new_starts.fieldmap --calibrate
    python -m automations.apex_new_starts.fieldmap --show
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

MAP_PATH = Path(__file__).resolve().parent / "field_map.json"

# The semantic names Apex is filled from. Order matters only for printing.
PERSONAL = ("first", "middle", "last", "address1", "address2", "city", "state",
            "zip", "dob", "email", "phone")
# Held to a different standard everywhere downstream: never auto-typed, shown
# to the operator to enter by hand. Bank routing/account numbers are not on
# this list because they are not mapped AT ALL -- direct deposit is out of
# scope for this report (see run.py).
SENSITIVE = ("ssn",)
KNOWN = PERSONAL + SENSITIVE

_SSN = re.compile(r"^\d{3}-?\d{2}-?\d{4}$")
_ZIP = re.compile(r"^\d{5}(-\d{4})?$")
_PHONE = re.compile(r"^\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}$")
_STATE = re.compile(r"^[A-Za-z]{2}$")
_ADDRESS = re.compile(r"^\d+\s+\w")
_ROUTING = re.compile(r"^\d{9}$")
_ACCOUNT = re.compile(r"^\d{6,17}$")
_DIGITS = re.compile(r"\D")

# Kinds that never carry data worth copying: signature images, signing
# timestamps, checkboxes (Apex's equivalents are set from the sheet, not the
# packet).
IGNORE_KINDS = {"sig", "ini", "tms", "snm", "chk", "att"}


def _norm(s) -> str:
    return " ".join(str(s if s is not None else "").split()).strip()


def _fold(s) -> str:
    return _norm(s).lower()


def _is_i9(doc_name: str) -> bool:
    low = (doc_name or "").lower().replace("-", "")
    return "i9" in low


def classify(value: str, kind: str, packet_name: str,
             doc_name: str = "") -> Optional[str]:
    """The semantic name this ONE value looks like, or None.

    Deliberately narrow. Only shapes that can't be mistaken for each other get
    a name here (an SSN cannot be read as a ZIP); the shapes that CAN --
    first vs last name, city vs middle name -- are settled by `_by_position`
    against anchors this function is sure about.
    """
    v = _norm(value)
    if not v or kind in IGNORE_KINDS:
        return None
    parts = [p for p in _norm(packet_name).split() if p]
    first = parts[0] if parts else ""
    last = parts[-1] if len(parts) > 1 else ""
    if _SSN.match(v):
        return "ssn"
    if "@" in v:
        return "email"
    if _PHONE.match(v) and len(_DIGITS.sub("", v)) == 10:
        return "phone"
    if _ZIP.match(v):
        return "zip"
    if kind == "dat":
        # ONLY the I-9 asks for a date of birth. The W-4 and the direct-deposit
        # form each carry one date box and it is the date they SIGNED -- reading
        # that as a birthday would put today's date in Apex's DOB field for
        # anyone whose I-9 field ever goes missing.
        return "dob" if _is_i9(doc_name) else None
    if _fold(v) == _fold(packet_name):
        return "full_name"          # a 'print your name' box, not a name field
    # Name match is by TOKENS, not string equality: the board and Blue Ink
    # disagree about middle names and two-word surnames all the time. 'Urbina
    # Finol' on the form against a packet addressed to 'Jean Urbina Finol' is
    # the surname; equality would have called it nothing at all.
    vt = set(_fold(v).split())
    pt = [t for t in _fold(packet_name).split() if t]
    if len(pt) > 1 and vt and vt.issubset(set(pt)):
        if pt[-1] in vt:
            return "last"
        if pt[0] in vt:
            return "first"
    if last and _fold(v) == _fold(last):
        return "last"
    if first and _fold(v) == _fold(first):
        return "first"
    if _ADDRESS.match(v):
        return "address1"
    if _STATE.match(v):
        return "state"
    return None


def _by_position(doc_map: Dict[str, str], keys: List[str]) -> None:
    """Name the fields regex can't tell apart, using the ones it can.

    Two ambiguities, both settled by where the field sits in the document's own
    key order (Blue Ink numbers fields in the order they were placed, top to
    bottom, so this is the reading order of the form):

      * CITY is the last unnamed text field BEFORE 'state'. On the I-9 that is
        inp007, between the address and the two-letter state -- the only thing
        that can sit there.
      * MIDDLE is an unnamed field between 'first'/'last' and the address.
    """
    order = {k: i for i, k in enumerate(keys)}
    state_at = min((order[k] for k, v in doc_map.items() if v == "state"),
                   default=None)
    addr_at = min((order[k] for k, v in doc_map.items() if v == "address1"),
                  default=None)
    name_at = max((order[k] for k, v in doc_map.items()
                   if v in ("first", "last")), default=None)
    if state_at is not None:
        before = [k for k in keys
                  if order[k] < state_at and k not in doc_map
                  and (addr_at is None or order[k] > addr_at)]
        if before:
            doc_map[before[-1]] = "city"
    if name_at is not None and addr_at is not None:
        between = [k for k in keys
                   if name_at < order[k] < addr_at and k not in doc_map]
        if between:
            doc_map[between[0]] = "middle"


def build(samples: List[dict]) -> tuple:
    """(map, unresolved) from a list of {doc, key, kind, value, packet_name}.

    `map` is {document name: {field key: semantic name}}; `unresolved` lists the
    keys that carried data in every sample but never agreed on what they were,
    so somebody can look.
    """
    # doc -> key -> [guess or None, one per sample the key had a value in]
    votes: Dict[str, Dict[str, list]] = defaultdict(lambda: defaultdict(list))
    order: Dict[str, list] = defaultdict(list)
    for s in samples:
        doc, key = s["doc"], s["key"]
        if key not in order[doc]:
            order[doc].append(key)
        if not _norm(s["value"]):
            continue
        votes[doc][key].append(
            classify(s["value"], s["kind"], s["packet_name"], doc))

    out: Dict[str, Dict[str, str]] = {}
    unresolved: List[tuple] = []
    for doc, keys in votes.items():
        doc_map: Dict[str, str] = {}
        for key, guesses in keys.items():
            named = [g for g in guesses if g]
            if not named:
                continue
            # The bar: every sample that COULD be read agrees, and enough of
            # them could be read. Unanimity across all samples was too strict
            # for real people -- one person in ten types a surname that isn't
            # the one their packet was addressed to (a married name, a typo),
            # and that lone unreadable value was enough to leave the I-9's
            # last-name box unnamed. What actually signals "we don't understand
            # this key" is DISAGREEMENT -- an SSN in one packet and a phone
            # number in another -- and that still rejects.
            if len(set(named)) == 1 and len(named) >= max(2, 0.6 * len(guesses)):
                if named[0] in KNOWN:
                    doc_map[key] = named[0]
                elif named[0] != "full_name":
                    unresolved.append((doc, key, named[0]))
            else:
                unresolved.append((doc, key, "/".join(sorted(set(
                    g or "blank" for g in guesses)))))
        _by_position(doc_map, order[doc])
        # A document can only hold ONE of each field. If two keys claim the same
        # name, neither is trusted -- silently picking one would pick wrong.
        counts: Dict[str, int] = defaultdict(int)
        for name in doc_map.values():
            counts[name] += 1
        for key, name in list(doc_map.items()):
            if counts[name] > 1:
                del doc_map[key]
                unresolved.append((doc, key, f"{name} (claimed by "
                                             f"{counts[name]} fields)"))
        if doc_map:
            out[doc] = doc_map
    return out, unresolved


def load() -> Dict[str, Dict[str, str]]:
    try:
        return json.loads(MAP_PATH.read_text())
    except FileNotFoundError:
        raise RuntimeError(
            "No field_map.json -- Blue Ink's fields have no labels, so the "
            "mapping has to be calibrated once on this repo:\n"
            "    python -m automations.apex_new_starts.fieldmap --calibrate")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"field_map.json is not valid JSON: {e}")


def save(mapping: Dict[str, Dict[str, str]]) -> None:
    MAP_PATH.write_text(json.dumps(mapping, indent=2, sort_keys=True) + "\n")


# ------------------------------------------------------------------ CLI

def _samples(limit: int) -> List[dict]:
    """Field rows from the `limit` most recent COMPLETED bundles.

    THE I-9 ONLY. The packet also holds a W-4 and a direct-deposit form, and
    both were mapped at first -- but the W-4 carries the EMPLOYER's address
    beside the employee's (two fields, same shape, no way to tell them apart)
    and the DD form's only date is the date they signed, not a birthday. The
    I-9 asks for every single thing Apex needs, on a federal form whose layout
    doesn't change, so the other two are not read at all. A field the I-9
    leaves blank is reported as a gap rather than guessed at from a form we
    understand less well.
    """
    from automations.apex_new_starts import blueink_data as BID
    rows = []
    for b in BID.completed_bundles(limit=limit):
        docs = {d["key"]: _norm(d.get("name")) for d in b.get("documents") or []
                if _is_i9(d.get("name"))}
        name = _norm((b.get("packets") or [{}])[0].get("name"))
        for f in BID.bundle_data(b["id"]):
            doc = docs.get(f.get("doc_key")) or ""
            if not doc:
                continue        # a field on no document -- nothing to map it to
            rows.append({"doc": doc, "key": f.get("field_key"),
                         "kind": f.get("kind"), "value": f.get("value"),
                         "packet_name": name})
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--calibrate", action="store_true",
                    help="re-derive the map from recent signed packets")
    ap.add_argument("--samples", type=int, default=8,
                    help="how many signed packets to agree across (default 8)")
    ap.add_argument("--show", action="store_true", help="print the saved map")
    ap.add_argument("--write", action="store_true",
                    help="with --calibrate, save the result over field_map.json")
    args = ap.parse_args(argv)

    if args.show:
        for doc, m in sorted(load().items()):
            print(f"\n{doc}")
            for key, name in sorted(m.items(), key=lambda kv: kv[1]):
                print(f"  {name:12} {key}")
        return 0
    if not args.calibrate:
        ap.print_help()
        return 0

    print(f"reading {args.samples} recent signed packet(s)...", flush=True)
    mapping, unresolved = build(_samples(args.samples))
    for doc, m in sorted(mapping.items()):
        print(f"\n{doc}")
        for key, name in sorted(m.items(), key=lambda kv: kv[1]):
            flag = "  ← sensitive, never auto-typed" if name in SENSITIVE else ""
            print(f"  {name:12} {key}{flag}")
    if unresolved:
        print(f"\nUNNAMED ({len(unresolved)}) — left out on purpose:")
        for doc, key, why in unresolved[:25]:
            print(f"  {doc[:26]:28} {key:16} {why}")
    if args.write:
        save(mapping)
        print(f"\nsaved -> {MAP_PATH.name} (keys only, no values)")
    else:
        print("\n(nothing saved — rerun with --write once this looks right)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
