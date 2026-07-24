"""Row hygiene for the DD sources — the cleanup the VA does by hand.

Both DD inputs arrive dirty in the same ways (DD_SOURCES.md, "Row hygiene"):
the Tableau DD crosstab and the Credico pull. So the rules live here once and
both callers use them.

  1. ONE PERSON, SEVERAL LINES. A named row, a `… LEDGER` / `… Ledger` row, and
     a BLANK-NAME continuation row belonging to the owner above are all the same
     person and must be summed. Seen in her file: `Selena Powers` +
     `Selena Powers LEDGER`, and Amjad Malhas across three rows.
  2. A +150 / −150 PAIR IS A CANCELLATION — drop BOTH lines. (The sum is the
     same either way; we do it explicitly so the run can report what vanished
     instead of a number quietly shrinking.)
  3. CREDICO REPORTS BY COMPANY, not person — map company → owner. Anything we
     can't map is REPORTED, never dropped: an unmapped company is money that
     silently goes missing from someone's week.
  4. Credico's date runs ONE WEEK FORWARD — for week ending 3.22 you pull
     Saturday the 28th. `credico_saturday()` does that.

The "$-format" trap from her notes (pasted numbers without a $ are skipped by
the SUM) can't happen here — `money()` parses the text either way.

    python -m automations.override_bulletin.dd_rows      # runs the worked examples
"""
from __future__ import annotations

import collections
import datetime as dt
import re

from automations.override_bulletin.dd_data import money

# Credico bills under a company name; these are the owners behind them. The
# first two keys are the EXACT strings in Credico's own "Select Office" dropdown,
# read off the live screen 2026-07-23 — DD_SOURCES had them as "Able
# Acquisitions" / "Phoenix Acquisitions", which would never have matched. The
# looser spellings are kept so either form resolves. Owner names are spelled as
# the DD tab spells them, then resolved through ICD Aliases like every other name.
COMPANY_TO_OWNER = {
    "abyl acquisition group inc": "Abel Draper",
    "phoenix acquisition": "Jahvid Thompson",
    "able acquisitions": "Abel Draper",
    "abyl acquisitions": "Abel Draper",
    "phoenix acquisitions": "Jahvid Thompson",
}

_LEDGER_RE = re.compile(r"[\s,\-–—]*\bledgers?\b\s*$", re.I)
_WEEK_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{2,4})$")


def credico_saturday(week_label):
    """The Credico report date for a sheet week — the FOLLOWING Saturday.

    Credico's dates run one week forward: week ending 3.22 is pulled as Saturday
    the 28th, NOT the 21st. Sheet weeks end on a Sunday, so this is +6 days, but
    it is computed as "the next Saturday strictly after" so an odd label can't
    silently land on the wrong week."""
    m = _WEEK_RE.match((week_label or "").strip())
    if not m:
        raise ValueError(f"not a week label: {week_label!r} (expected e.g. 7.19.26)")
    mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    date = dt.date(y + 2000 if y < 100 else y, mo, d)
    return date + dt.timedelta(days=((5 - date.weekday()) % 7) or 7)


def _base_name(raw):
    """Strip a trailing LEDGER marker — `Selena Powers LEDGER` is Selena Powers."""
    return _LEDGER_RE.sub("", (raw or "").strip()).strip(" ,-–—")


def _key(name):
    return re.sub(r"[^a-z0-9 ]+", "", (name or "").lower()).strip()


def _cancel(amounts):
    """Drop every exact +x/−x pair. Returns (kept, [(abs_value, n_pairs)]).

    Greedy on absolute value, so +150, +150, −150 cancels ONE pair and keeps a
    +150 — not all three."""
    pos = collections.Counter(a for a in amounts if a > 0)
    neg = collections.Counter(-a for a in amounts if a < 0)
    pairs = pos & neg
    kept = [a for a in amounts if a == 0]
    for v, n in (pos - pairs).items():
        kept += [v] * n
    for v, n in (neg - pairs).items():
        kept += [-v] * n
    return kept, sorted(pairs.items(), reverse=True)


def normalize(rows):
    """Collapse dirty source rows into one entry per person.

    `rows` is [{'name': str, 'amount': str|float}] IN SOURCE ORDER — order is
    load-bearing, because a blank-name row belongs to the row above it.

    Returns (entries, report). Each entry is
    {'name', 'key', 'amount', 'lines', 'variants', 'cancelled'}.
    `report` carries what a human needs to see: merges, cancellations, orphans.
    """
    entries, index, current = [], {}, None
    merges, orphans = [], []
    for r in rows:
        raw = (r.get("name") or "").strip()
        amt = money(r.get("amount"))
        if not raw:
            if current is None:
                # A continuation row with nothing above it — we cannot guess who
                # it belongs to, so it is reported rather than silently dropped.
                orphans.append(amt)
                continue
            g = current
            g["variants"].append("(blank continuation row)")
        else:
            base = _base_name(raw)
            k = _key(base)
            g = index.get(k)
            if g is None:
                g = {"name": base, "key": k, "amounts": [], "lines": 0,
                     "variants": [], "cancelled": []}
                index[k] = g
                entries.append(g)
            g["variants"].append(raw)
            current = g
        g["amounts"].append(amt)
        g["lines"] += 1

    for g in entries:
        kept, pairs = _cancel(g["amounts"])
        g["cancelled"] = pairs
        g["amount"] = round(sum(kept), 2)
        if g["lines"] > 1:
            merges.append((g["name"], g["lines"], g["variants"]))
        del g["amounts"]
    return entries, {"merges": merges, "orphans": orphans,
                     "cancellations": [(g["name"], g["cancelled"])
                                       for g in entries if g["cancelled"]]}


def to_owners(entries, aliases=None, companies=None):
    """Map normalized entries onto canonical owner keys.

    Credico names companies, so each entry is tried as a company first, then as
    a person. Returns ({owner_key: amount}, unmapped) — `unmapped` is every
    entry we could not place, and it must never be swallowed: an unmapped
    company is somebody's missing money."""
    from automations.override_bulletin import fill as F
    aliases = F.load_alias_map() if aliases is None else aliases
    companies = COMPANY_TO_OWNER if companies is None else companies
    out, unmapped = {}, []
    for g in entries:
        owner = companies.get(g["key"])
        if owner is None and re.search(r"\b(acquisitions?|marketing|llc|inc|group"
                                       r"|enterprises?|solutions?)\b", g["name"], re.I):
            # Looks like a company but isn't in the map — do NOT guess it is a
            # person, or it lands under a made-up owner and reconciles to nothing.
            unmapped.append(g)
            continue
        k = F.canon(owner or g["name"], aliases)
        out[k] = round(out.get(k, 0.0) + g["amount"], 2)
    return out, unmapped


def summarize(entries, report, unmapped=()):
    """Plain-English lines for the run output / email. Nothing is hidden."""
    out = []
    for name, n, variants in report["merges"]:
        out.append(f"merged {n} lines into one for {name} "
                   f"({', '.join(variants[:3])}{'…' if len(variants) > 3 else ''})")
    for name, pairs in report["cancellations"]:
        for v, n in pairs:
            out.append(f"cancelled {n}× ${v:,.2f} +/- pair for {name} — both "
                       f"lines dropped")
    for amt in report["orphans"]:
        out.append(f"⚠ a blank-name row of ${amt:,.2f} had no owner above it — "
                   f"NOT counted; check the source")
    for g in unmapped:
        out.append(f"⚠ '{g['name']}' (${g['amount']:,.2f}) looks like a company "
                   f"with no owner mapping — NOT counted; add it to "
                   f"COMPANY_TO_OWNER")
    return out


def _selftest():
    """The worked examples straight out of DD_SOURCES.md."""
    rows = [
        {"name": "Selena Powers", "amount": "$1,000.00"},
        {"name": "Selena Powers LEDGER", "amount": "250"},
        {"name": "Amjad Malhas", "amount": "$500.00"},
        {"name": "", "amount": "$125.50"},              # continuation row
        {"name": "Amjad Malhas Ledger", "amount": "$74.50"},
        {"name": "Able Acquisitions", "amount": "$2,000.00"},
        {"name": "Able Acquisitions", "amount": "150"},
        {"name": "Able Acquisitions", "amount": "-150"},   # cancels the line above
        {"name": "Sunrise Acquisitions", "amount": "$900.00"},  # unmapped company
    ]
    entries, report = normalize(rows)
    got = {g["name"]: g["amount"] for g in entries}
    want = {"Selena Powers": 1250.00, "Amjad Malhas": 700.00,
            "Able Acquisitions": 2000.00, "Sunrise Acquisitions": 900.00}
    assert got == want, f"{got} != {want}"
    assert credico_saturday("3.22.26") == dt.date(2026, 3, 28)
    assert credico_saturday("7.19.26") == dt.date(2026, 7, 25)
    owners, unmapped = to_owners(entries, aliases={})
    assert [g["name"] for g in unmapped] == ["Sunrise Acquisitions"], unmapped
    assert owners.get("abel draper") == 2000.00, owners
    print("normalized:")
    for g in entries:
        print(f"   {g['name']:24} ${g['amount']:>10,.2f}   {g['lines']} line(s)")
    print("\nowners:", owners)
    print("\nwhat the run would report:")
    for line in summarize(entries, report, unmapped):
        print("  ·", line)
    print("\n✓ selftest passed")


if __name__ == "__main__":
    _selftest()
