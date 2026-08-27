"""Data layer for the "Up and Coming RCs and NCs" infographic (part 2, sent right
after the DD bulletin — email only, no Slack).

Two inputs, both already in the DD workbook:
  * the "Org Tree" tab (gid 2106936862) — a generational indent grid (col A = Gen 1
    at the root, B = Gen 2, ... each person OWNS the people in the next column whose
    rows fall under them). We parse it into a real tree and count, per leader:
      - First Gen  = number of DIRECT reports (the next generation under them)
      - Total Org  = the leader THEMSELVES plus everyone under them (NCs);
                     adoptions count for their own org but not for the root;
                     Cody Cannon's two "(1/2)" halves counted once
      - Depth      = descendants BELOW the first generation (RCs), leader NOT
                     counted (it is a count of owners under the first gen)
  * the DD bulletin's own leader figures (dd_data) for the weekly WIRE $ — Rafael's
    wire is the whole-org headline, everyone else's is their podium week figure.

Goals are FIXED per person (Megan 2026-07-31 — "fixed per person for now"). A metric
that EXCEEDS its goal renders red (see the build layer).
"""
from __future__ import annotations

from automations.override_bulletin import fill as F

ORG_TREE_GID = 2106936862

# HOW TOTAL ORG IS COUNTED — set by Eve 2026-08-27 against her own markup of the
# Org Tree, and reproduced by the three figures at the bottom of this comment.
#
# 1. THE LEADER COUNTS THEMSELVES. "How many people are in Colten's org" includes
#    Colten. The tree only holds the people BELOW someone, so one is added.
# 2. ADOPTIONS COUNT FOR THEIR OWN ORG, NOT FOR THE ROOT. Raf, 2026-03-10:
#    *"When adding up total units for 'My org' don't count adoptions that aren't
#    mine, only count them for the person receiving the double override."* The
#    adoptions sit under Colten, so they are Colten's and they are Jairo's — and
#    they are NOT Rafael's, because he is the one they are not "mine" for. Only
#    the root of the tree drops them; every org inside it keeps them.
# 3. And counting them at all is the other half of the same email, the half that
#    governs a QUALIFICATION board like this one: *"the adoption will count
#    towards the qualifications for regional or national consultant."* The money
#    half — SCI "does not count adoption headcount or sales" — still governs the
#    DD bulletin's figures, which are untouched. See DD_SOURCES.md.
#
# The tab itself says who is an adoption: it paints them with the fill its own
# legend row calls "Adoptions". `adoptions_on_tab` reads that back rather than
# keeping a list here — a hardcoded one had already drifted, never naming Justin
# Fermin, who has been painted red and flagged `Adoption? YES` in dd_data since
# July.
#
# WE 8.23.26, the numbers this has to reproduce:
#   Rafael  9 / 48 / $958k     (50 under him, less the 3 adoptions, plus himself)
#   Colten  8 / 17 / $386k     (16 under him, adoptions in, plus himself)
#   Carlos 10 / 22 / $325k     (21 under him, plus himself)
ADOPTION_FILL = (1.0, 0.0, 0.0)      # the legend's "Adoptions" swatch
# Cody Cannon is on the tree twice as "(1/2)" (once under Carlos, once under
# Colten) so he's not double-counted org-wide. Megan 2026-07-31: attribute him
# FULLY to Carlos — his Carlos-side node counts 1, his Colten-side node counts 0.
CODY_OWNER = "carlos hidalgo"
# Rows that are the tab's colour legend, not tree nodes.
_LEGEND = {"generation", "org heads", "adoptions", "no dd"}

# name        = the display/podium spelling; tree_name = the Org Tree spelling when
# it differs; role NC/RC picks the metric set + goals + tagline; wire "headline"
# means use the org total (Rafael, the top of the tree).
LEADERS = [
    {"name": "Rafael Hidalgo", "role": "NC", "fg_goal": 20, "second_goal": 100,
     "wire_goal": 1_000_000, "tag": "ROAD TO GREATNESS", "wire": "headline"},
    {"name": "Colten Wright", "role": "NC", "fg_goal": 20, "second_goal": 50,
     "wire_goal": 500_000, "tag": "ROAD TO GREATNESS"},
    {"name": "Carlos Hidalgo", "role": "NC", "fg_goal": 20, "second_goal": 50,
     "wire_goal": 500_000, "tag": "ROAD TO GREATNESS"},
    # Jairo Ruiz joined Road to RC 2026-08-27 (Eve), on the same goals as the
    # other four. He is Colten's first gen and carries his own five, so he was
    # already in the tree and in dd_data's podium — only this row was missing.
    {"name": "Jairo Ruiz", "role": "RC", "fg_goal": 5, "second_goal": 2,
     "wire_goal": 100_000, "tag": "ROAD TO RC"},
    {"name": "Eveliz Wright", "role": "RC", "fg_goal": 5, "second_goal": 2,
     "wire_goal": 100_000, "tag": "ROAD TO RC"},
    {"name": "Khalil Mansour", "role": "RC", "fg_goal": 5, "second_goal": 2,
     "wire_goal": 100_000, "tag": "ROAD TO RC"},
    {"name": "Salik Mallick", "role": "RC", "fg_goal": 5, "second_goal": 2,
     "wire_goal": 100_000, "tag": "ROAD TO RC", "tree_name": "Salik Malick"},
    {"name": "Hammad Haque", "role": "RC", "fg_goal": 5, "second_goal": 2,
     "wire_goal": 100_000, "tag": "ROAD TO RC"},
]

QUALIFICATIONS = {
    "REGIONAL": ["5 First Gen Owners", "2 Owners in Depth", "$100k Org wire",
                 "$20k personal wire", "*8 weeks in a row"],
    "NATIONAL": ["7 First Gen Owners", "4 Owners in Depth", "$200k Org wire",
                 "$20k personal wire", "*8 weeks in a row"],
}


def adoptions_on_tab(tree_ws):
    """The names the Org Tree itself paints as adoptions, lower-cased.

    Reads the cell FILLS, because that red is how the tab has always said it and
    its legend spells the colour out. Returns an empty set when the colours can't
    be read: no adoption flags means every org counts everyone, which is the
    reading that is wrong for exactly one card (the root's) instead of for all of
    them — and `load` says so out loud rather than publishing it quietly.
    """
    try:
        meta = tree_ws.spreadsheet.fetch_sheet_metadata({
            "includeGridData": True,
            "ranges": ["'{}'!A1:E200".format(tree_ws.title)],
            "fields": ("sheets.data.rowData.values(formattedValue,"
                       "effectiveFormat.backgroundColor)")})
        rows = meta["sheets"][0]["data"][0].get("rowData", [])
    except Exception as e:  # noqa: BLE001
        print("  !! could not read the Org Tree fills ({}) — no adoption is "
              "flagged, so the root's Total Org will read HIGH".format(
                  type(e).__name__))
        return set()
    out = set()
    for row in rows:
        for cell in row.get("values", []):
            nm = (cell.get("formattedValue") or "").replace("(1/2)", "").strip()
            if not nm or nm.lower() in _LEGEND:
                continue
            bg = ((cell.get("effectiveFormat") or {}).get("backgroundColor") or {})
            rgb = tuple(round(bg.get(k, 0.0), 2) for k in ("red", "green", "blue"))
            if rgb == ADOPTION_FILL:
                out.add(nm.lower())
    return out


def _parse_tree(vals, adoptions=()):
    """Grid rows -> nodes with parent/kids. A name at column c is a child of the
    most recent name seen at column c-1 (scanning top-to-bottom, left-to-right)."""
    nodes, last = [], {}
    for row in vals:
        for ci, cell in enumerate((row + [""] * 5)[:5]):
            c = (cell or "").strip()
            # The tab's first row is 'Generation | 1 | 2 | 3 | 4'. 'Generation'
            # is in _LEGEND but the column numbers were not, so they parsed as
            # four people and built a little 1->2->3->4 chain of their own.
            # Harmless as the tab stands — that chain's root has no parent, so it
            # never landed inside anyone's org — but it is one re-ordered row away
            # from adopting a real Gen-1 name onto a header cell. A bare number is
            # never a person.
            if not c or c.lower() in _LEGEND or c.isdigit():
                continue
            cody = "(1/2)" in c
            nm = c.replace("(1/2)", "").strip()
            idx = len(nodes)
            parent = last.get(ci - 1)
            nodes.append({"col": ci, "name": nm, "cody": cody,
                          "adopt": nm.lower() in adoptions,
                          "parent": parent, "kids": []})
            if parent is not None:
                nodes[parent]["kids"].append(idx)
            last[ci] = idx
    return nodes


def _subtree(nodes, i):
    out, stack = [], list(nodes[i]["kids"])
    while stack:
        j = stack.pop()
        out.append(j)
        stack += nodes[j]["kids"]
    return out


def _assign_weights(nodes):
    """Per-node count weight. Everyone counts 1, EXCEPT a Cody '(1/2)' node counts
    1 only inside CODY_OWNER's (Carlos's) subtree and 0 anywhere else — so Cody is
    a full first-gen/total for Carlos and invisible under Colten, while Rafael
    (who contains both) still counts him exactly once."""
    ci = next((k for k, n in enumerate(nodes)
               if n["name"].lower() == CODY_OWNER), None)
    owner_sub = set(_subtree(nodes, ci)) if ci is not None else set()
    for j, n in enumerate(nodes):
        n["w"] = (1.0 if j in owner_sub else 0.0) if n["cody"] else 1.0


def _metrics(nodes, name):
    """(first_gen, total, depth) for a leader by tree name.

    first_gen = weighted direct reports. total = every weighted descendant PLUS
    the leader themselves, and an adoption is dropped only when the leader is the
    ROOT of the tree (rule 2 at the top of this file). depth = descendants below
    the first generation, and does NOT count the leader — it answers "how many
    owners in depth", which is a different question from org size.
    """
    i = next((k for k, n in enumerate(nodes) if n["name"].lower() == name.lower()), None)
    if i is None:
        return None
    kids = nodes[i]["kids"]
    desc = _subtree(nodes, i)

    def w(j):
        return nodes[j]["w"]

    is_root = nodes[i]["parent"] is None
    first_gen = sum(w(j) for j in kids)
    under = sum(w(j) for j in desc if not (is_root and nodes[j]["adopt"]))
    total = under + 1.0                      # the leader is in their own org
    depth = under - first_gen
    return first_gen, total, depth


def _wire(leader, dd, podium_by_name):
    if leader.get("wire") == "headline":
        return dd.get("headline") or 0.0
    p = podium_by_name.get(leader["name"].lower())
    return (p.get("week") if p else 0.0) or 0.0


def load(tree_ws=None, dd=None):
    """One list of card dicts + the qualifications block. `dd` is a dd_data.load()
    result (reused for the wire figures + the week label); pulled if not passed."""
    from automations.override_bulletin import dd_data as D
    if dd is None:
        dd = D.load()
    if tree_ws is None:
        from automations.recruiting_report import fill as _fill
        sh = _fill._client().open_by_key(D.WORKBOOK_ID)
        tree_ws = next(w for w in sh.worksheets() if w.id == ORG_TREE_GID)

    vals = tree_ws.get_all_values()
    nodes = _parse_tree(vals, adoptions_on_tab(tree_ws))
    _assign_weights(nodes)
    podium_by_name = {p["name"].lower(): p for p in dd.get("podium", [])}

    cards = []
    for lead in LEADERS:
        tname = lead.get("tree_name", lead["name"])
        m = _metrics(nodes, tname)
        if m is None:
            m = (0, 0, 0)
        first_gen, total, depth = m
        wire = _wire(lead, dd, podium_by_name)
        second = total if lead["role"] == "NC" else depth
        cards.append({
            "name": lead["name"], "role": lead["role"], "tag": lead["tag"],
            "first_gen": first_gen, "fg_goal": lead["fg_goal"],
            "second": second, "second_goal": lead["second_goal"],
            "second_label": "Total Org" if lead["role"] == "NC" else "Depth",
            "wire": wire, "wire_goal": lead["wire_goal"],
        })
    # Ranked by this week's wire, highest to lowest (Megan 2026-07-31). The NCs
    # naturally lead since their wires dwarf the RCs'.
    cards.sort(key=lambda c: -(c["wire"] or 0))
    return {"week": dd["weeks"][0] if dd.get("weeks") else "",
            "cards": cards, "qualifications": QUALIFICATIONS}
