"""Data layer for the "Up and Coming RCs and NCs" infographic (part 2, sent right
after the DD bulletin — email only, no Slack).

Two inputs, both already in the DD workbook:
  * the "Org Tree" tab (gid 2106936862) — a generational indent grid (col A = Gen 1
    at the root, B = Gen 2, ... each person OWNS the people in the next column whose
    rows fall under them). We parse it into a real tree and count, per leader:
      - First Gen  = number of DIRECT reports (the next generation under them)
      - Total Org  = every descendant (NCs) — adoptions excluded, Cody Cannon's two
                     "(1/2)" halves counted once
      - Depth      = descendants BELOW the first generation (RCs) = total − first-gen
  * the DD bulletin's own leader figures (dd_data) for the weekly WIRE $ — Rafael's
    wire is the whole-org headline, everyone else's is their podium week figure.

Goals are FIXED per person (Megan 2026-07-31 — "fixed per person for now"). A metric
that EXCEEDS its goal renders red (see the build layer).
"""
from __future__ import annotations

from automations.override_bulletin import fill as F

ORG_TREE_GID = 2106936862
# The three adoptions live under Colten but are NOT part of the org — excluded from
# a leader's Total (same names dd_data tracks as special cases).
ADOPTIONS = {"milan godbolt", "karrington moody", "marcos barbosa"}
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


def _parse_tree(vals):
    """Grid rows -> nodes with parent/kids. A name at column c is a child of the
    most recent name seen at column c-1 (scanning top-to-bottom, left-to-right)."""
    nodes, last = [], {}
    for row in vals:
        for ci, cell in enumerate((row + [""] * 5)[:5]):
            c = (cell or "").strip()
            if not c or c.lower() in _LEGEND:
                continue
            cody = "(1/2)" in c
            nm = c.replace("(1/2)", "").strip()
            idx = len(nodes)
            parent = last.get(ci - 1)
            nodes.append({"col": ci, "name": nm, "adopt": nm.lower() in ADOPTIONS,
                          "cody": cody, "parent": parent, "kids": []})
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

    first_gen = weighted direct reports; total = weighted descendants EXCLUDING
    adoptions; depth = weighted descendants below the first generation
    (total − first-gen). Weights handle the Cody-once-on-Carlos rule.
    """
    i = next((k for k, n in enumerate(nodes) if n["name"].lower() == name.lower()), None)
    if i is None:
        return None
    kids = nodes[i]["kids"]
    desc = _subtree(nodes, i)

    def w(j):
        return nodes[j]["w"]

    first_gen = sum(w(j) for j in kids)
    total = sum(w(j) for j in desc if not nodes[j]["adopt"])
    depth = (sum(w(j) for j in desc if not nodes[j]["adopt"])
             - sum(w(j) for j in kids if not nodes[j]["adopt"]))
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
    nodes = _parse_tree(vals)
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
