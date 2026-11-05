"""A new owner who starts earning DD goes on the bulletin by himself.

Eve 2026-11-05 (WE 11.1.26): Omar Mohamad earned his first $228.00, the headline
had it, but Salik's and Hammad's figures did not, because a leader's figure is
the sum of a hand-kept list (PODIUM ORG LISTS on 'Lucy Org Tree'). Same miss as
Samuel Acay (9/24) and Nicolas Murrugarra (10/29). "Cuando agregamos nuevos
owners ... detectar cuando empiezan a cobrar dd en program summary y agregarlos
directamente a este bulletin."

Two steps, both driven by the 'Org Tree' tab, which says whose org someone is in:

  from_pull   (needs Program Summary, runs inside dd_populate)
      on the tree, money this week, Active NO  -> Active YES
      on the tree, money this week, no DD row  -> a new row above the total
      NOT on the tree, money, no DD row        -> reported, nothing written: we
                                                  cannot know whose org it is
  sync_lists  (needs only the Sheet, also runs before the review link is built)
      Active YES, money this week, on the tree -> a row on the list of every
      leader above them, and that leader's Expected ICDs goes up by one

Never added: adoptions (their own block), the 'Cody Cannon (1/2)' split, and
NEVER_LISTED. Existing owners' ORG and Campaign cells are never touched.

    python -m automations.override_bulletin.dd_new_owner          # dry run
    python -m automations.override_bulletin.dd_new_owner --write
    python -m unittest automations.override_bulletin.test_dd_new_owner
"""
from __future__ import annotations

import re
import sys

from automations.override_bulletin import dd_data as D
from automations.override_bulletin import fill as F
from automations.override_bulletin import rcs_ncs_data as R

# On the tree under Hammad, but left off Salik's and Hammad's lists on purpose:
# excluding him is what makes both land on the published figures (Megan
# 2026-07-23, DD_SOURCES.md).
NEVER_LISTED = ("Jacob Dover",)

# Nearest leader above a NEW row -> the tab's ORG word. Only used on rows this
# module creates. Anyone with none of these above them is Raf's.
ORG_WORD = {"eveliz wright": "Eveliz", "jairo ruiz": "Jairo",
            "khalil mansour": "Khalil", "salik malick": "Salik",
            "salik mallick": "Salik", "hammad haque": "Salik",
            "colten wright": "Colten", "carlos hidalgo": "Carlos"}


def _tree_people(org_vals, adoptions, key):
    """{key: {'name', 'ancestors'}} for everyone the rules may add."""
    nodes = R._parse_tree(org_vals, adoptions)
    out = {}
    for n in nodes:
        if n["cody"] or n["adopt"]:
            continue
        anc, p = [], n["parent"]
        while p is not None:
            anc.append(nodes[p]["name"])
            p = nodes[p]["parent"]
        out[key(n["name"])] = {"name": n["name"], "ancestors": anc}
    return out


def _owner_rows(dd_vals):
    """(sheet row, cells) for each owner row, stopping at the total rows."""
    for i, r in enumerate(dd_vals[1:], start=2):
        nm = (r[0] or "").strip() if r else ""
        if nm.lower().startswith("total"):
            return
        if nm:
            yield i, r


def _special_names(dd_vals):
    """The 'ICD (Special Cases)' block: adoptions, kept apart from the lists."""
    out, on = [], False
    for r in dd_vals:
        a = (r[0] or "").strip() if r else ""
        if not on:
            on = a.lower().startswith("icd (special cases)")
        elif not a:
            break
        else:
            out.append(a)
    return out


def _week_col(dd_vals):
    return next(i for i, h in enumerate(dd_vals[0]) if D._WEEK_RE.match((h or "").strip()))


def _excluded(dd_vals, key):
    return {key(n) for n in list(NEVER_LISTED) + _special_names(dd_vals)}


def plan_lists(dd_vals, tree_vals, org_vals, adoptions, aliases):
    """Who is missing from which leader's list. Reads only."""
    key = lambda s: D._key(s, aliases)  # noqa: E731
    people = _tree_people(org_vals, adoptions, key)
    skip = _excluded(dd_vals, key)
    leaders = [(r[0] or "").strip()
               for r in D._labelled_block(tree_vals, D.LEADERS_LABEL, skip=1)
               if (r[0] or "").strip() and not (len(r) > 2 and (r[2] or "").strip())]
    listed = {}
    for r in D._labelled_block(tree_vals, D.LISTS_LABEL, skip=1):
        if len(r) > 1 and (r[1] or "").strip():
            listed.setdefault((r[0] or "").strip(), set()).add(key(r[1]))
    wk = _week_col(dd_vals)
    out = []
    for _, r in _owner_rows(dd_vals):
        nm = r[0].strip()
        k = key(nm)
        if len(r) < 2 or r[1].strip().upper() != "YES" or k in skip or k not in people:
            continue
        amount = D.money(r[wk]) if wk < len(r) else 0.0
        if amount <= 0:
            continue
        above = {key(a) for a in people[k]["ancestors"]}
        add_to = [l for l in leaders
                  if key(l) in above and k not in listed.get(l, set())]
        if add_to:
            out.append({"name": nm, "amount": amount, "add_to": add_to})
    return out


def plan_pull(dd_vals, org_vals, adoptions, aliases, pull, norm):
    """What Program Summary says the DD tab is missing. Reads only.

    `pull` is {norm(name): dollars}; `norm` is the same key dd_search matches
    the tab on. Returns activate / insert / unplaced lists."""
    people = _tree_people(org_vals, adoptions, norm)
    skip = _excluded(dd_vals, norm)
    rows = {norm(r[0].strip()): (i, r) for i, r in _owner_rows(dd_vals)}
    activate, insert, unplaced = [], [], []
    for k, amount in (pull or {}).items():
        if (amount or 0) <= 0 or k in skip:
            continue
        found = rows.get(k)
        if found:
            i, r = found
            if k in people and (len(r) < 2 or r[1].strip().upper() != "YES"):
                activate.append({"row": i, "name": r[0].strip(), "amount": amount})
            continue
        if k not in people:
            unplaced.append({"name": k, "amount": amount})
            continue
        anc = people[k]["ancestors"]
        org = next((ORG_WORD[a.lower()] for a in anc if a.lower() in ORG_WORD), "Raf")
        insert.append({"name": people[k]["name"], "amount": amount, "org": org})
    return {"activate": activate, "insert": insert, "unplaced": unplaced}


def _workbook():
    from automations.recruiting_report import fill as _fill
    sh = _fill._client().open_by_key(D.WORKBOOK_ID)
    org_ws = next(w for w in sh.worksheets() if w.id == R.ORG_TREE_GID)
    return sh, org_ws


def _insert_row(ws, dd_vals, item):
    """A new owner row, INSIDE the range every total sums so they all stretch."""
    total_at = next(i for i, r in enumerate(dd_vals, start=1)
                    if r and (r[0] or "").strip().lower().startswith("total - raf"))
    at = total_at - 2                    # inside F2:F133 and D2:D132 alike
    ws.insert_row([item["name"], "YES", "", item["org"]], index=at,
                  value_input_option="USER_ENTERED", inherit_from_before=True)
    above = ws.cell(at - 1, 5, value_render_option="FORMULA").value or ""
    formula = re.sub(r"(?<=[A-Z])%d\b" % (at - 1), str(at), above)
    ws.update_cell(at, 5, formula)


def from_pull(ws, dd_vals, pull, aliases, norm, write=False, org_ws=None):
    """Put new earners on the DD tab before the week column is filled.

    Returns the plan plus 'changed', True when rows moved so the caller has to
    re-read the tab."""
    if org_ws is None:
        _, org_ws = _workbook()
    plan = plan_pull(dd_vals, org_ws.get_all_values(), R.adoptions_on_tab(org_ws),
                     aliases, pull, norm)
    for a in plan["activate"]:
        print(f"new DD: {a['name']} ${a['amount']:,.2f} -> Active YES "
              f"{'' if write else '(dry run)'}")
        if write:
            ws.update_cell(a["row"], 2, "YES")
    for a in plan["insert"]:
        print(f"new DD: {a['name']} ${a['amount']:,.2f} -> new row, ORG {a['org']} "
              f"{'' if write else '(dry run)'}")
        if write:
            _insert_row(ws, dd_vals, a)
            dd_vals = ws.get_all_values()
    for a in plan["unplaced"]:
        print(f"new DD, NOT on the Org Tree, nothing written: {a['name']} "
              f"${a['amount']:,.2f}")
    plan["changed"] = bool(write and (plan["activate"] or plan["insert"]))
    return plan


def _apply_lists(tree_ws, tree_vals, plan):
    """Append below the last list row and raise each leader's Expected ICDs."""
    label_at = next(i for i, r in enumerate(tree_vals)
                    if r and " ".join((r[0] or "").split()).lower() == D.LISTS_LABEL.lower())
    end = label_at + 2                   # 0-based, first row after the header
    while end < len(tree_vals) and (tree_vals[end][0] or "").strip():
        end += 1
    next_row = end + 1
    leader_row = {}
    start = next(i for i, r in enumerate(tree_vals)
                 if r and " ".join((r[0] or "").split()).lower() == D.LEADERS_LABEL.lower())
    for i in range(start + 2, len(tree_vals)):
        nm = (tree_vals[i][0] or "").strip()
        if not nm:
            break
        leader_row[nm] = i + 1
    rows, bumps = [], {}
    for p in plan:
        for leader in p["add_to"]:
            rows.append([leader, p["name"], "", "",
                         f"Added by the bot: first DD ${p['amount']:,.2f}."])
            bumps[leader] = bumps.get(leader, 0) + 1
    tree_ws.update(values=rows, range_name=f"A{next_row}:E{next_row + len(rows) - 1}",
                   value_input_option="USER_ENTERED")
    for leader, n in bumps.items():
        r = leader_row[leader]
        cur = tree_vals[r - 1][3] if len(tree_vals[r - 1]) > 3 else ""
        if (cur or "").strip().isdigit():
            tree_ws.update_cell(r, 4, int(cur) + n)


def sync_lists(write=False, aliases=None):
    """Add every missing earner to their leaders' lists. Returns the plan."""
    sh, org_ws = _workbook()
    aliases = F.load_alias_map() if aliases is None else aliases
    tree_ws = sh.worksheet(D.TREE_TAB)
    tree_vals = tree_ws.get_all_values()
    plan = plan_lists(sh.worksheet(D.DD_TAB).get_all_values(), tree_vals,
                      org_ws.get_all_values(), R.adoptions_on_tab(org_ws), aliases)
    for p in plan:
        print(f"new DD: {p['name']} ${p['amount']:,.2f} -> list of "
              f"{', '.join(p['add_to'])}{'' if write else ' (dry run)'}")
    if plan and write:
        _apply_lists(tree_ws, tree_vals, plan)
    if not plan:
        print("new DD: every earner on the tree is on their leaders' lists")
    return plan


def tell_channel(lines):
    """One note in #revision-emails, after something was really written."""
    if not lines:
        return
    from automations.override_bulletin import review_gate as G
    G._client().chat_postMessage(
        channel=G._channel(None),
        text="*New owners on the Org Bulletin*\n" + "\n".join(f"• {x}" for x in lines))


def list_lines(plan):
    return [f"{p['name']} earned their first DD (${p['amount']:,.2f}): added to "
            f"{', '.join(p['add_to'])}" for p in plan]


def pull_lines(plan):
    out = [f"{a['name']} earned DD (${a['amount']:,.2f}) and was marked Active YES"
           for a in plan["activate"]]
    out += [f"{a['name']} earned DD (${a['amount']:,.2f}): new row under {a['org']}. "
            f"Campaign is blank, please fill it in" for a in plan["insert"]]
    out += [f"{a['name']} earned DD (${a['amount']:,.2f}) but is not on the Org Tree, "
            f"so they are NOT on the bulletin. Add them to the tree"
            for a in plan["unplaced"]]
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    plan = sync_lists(write="--write" in argv)
    if "--write" in argv:
        tell_channel(list_lines(plan))
    return 0


if __name__ == "__main__":
    sys.exit(main())
