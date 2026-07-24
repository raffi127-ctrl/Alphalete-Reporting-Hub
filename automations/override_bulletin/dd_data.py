"""DD Bulletin data layer — everything the render needs, from the Sheet.

Rules live in DD_SOURCES.md. In short:
  * active ICDs = `Active ICD` YES on `Org DDs Ongoing Report`
  * the podium is a DOWNLINE roll-up over the `Org Tree` tab, NOT the flat ORG
    column; Cody Cannon is SPLIT (his "(1/2)" marks count him half to each org)
  * ADOPTIONS (Karrington Moody, Milan Godbolt) and JACOB DOVER are EXCLUDED from
    the roll-up but still pulled and reported — their numbers must never vanish
  * Raf's podium figure is "total outside Carlos & Colten"
  * headline total, AVG DD and Active Owners are ALREADY computed in the tab
    (rows 132 / 135-153 / 155-173) — read them, never recompute
  * every name on both sides resolves through the shared ICD Aliases tab
"""
from __future__ import annotations

import collections
import re

from automations.override_bulletin import fill as F

WORKBOOK_ID = "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E"
DD_TAB = "Org DDs Ongoing Report"
TREE_TAB = "Org Tree"
WOW_WEEKS = 4

# Excluded from the ORG roll-up, still reported (see DD_SOURCES.md).
ADOPTIONS = ["Karrington Moody", "Milan Godbolt"]
SPECIAL = ["Jacob Dover"]

# Podium leaders, in the roles the bulletin uses. `outside` subtracts those
# subtrees (Raf's figure is explicitly "total outside Carlos and Colten").
LEADERS = [
    {"name": "Colten Wright", "loc": "Miami, Florida"},
    {"name": "Carlos Hidalgo", "loc": "Dallas, Texas"},
    {"name": "Rafael Hidalgo", "loc": "Dallas, Texas",
     "outside": ["Carlos Hidalgo", "Colten Wright"]},
    {"name": "Eveliz Wright", "loc": "Miami, Florida"},
    {"name": "Khalil Mansour", "loc": "Dallas, Texas"},
    {"name": "Salik Mallick", "loc": "Detroit, Michigan"},
    {"name": "Hammad Haque", "loc": "Detroit, Michigan"},
]
_WEEK_RE = re.compile(r"^\d{1,2}\.\d{1,2}\.\d{2,4}$")
_SPLIT_RE = re.compile(r"\(\s*(\d)\s*/\s*(\d)\s*\)")


def money(s):
    s = (s or "").replace("$", "").replace(",", "").strip()
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except ValueError:
        return 0.0


def _key(s, aliases):
    """Canonical match key: strip any '(1/2)' marker, resolve through ICD
    Aliases, then drop a trailing state suffix ('Carlos Hidalgo TX')."""
    s = _SPLIT_RE.sub("", s or "")
    n = F.canon(s, aliases)
    return re.sub(r"\b(tx|fl|mi)\b\s*$", "", n).strip()


def _labelled_block(vals, start_label, stop_labels=()):
    """Rows of a pre-computed block, found BY LABEL in column A (never by index —
    inserting a week column or a row must not move it)."""
    out, on = [], False
    for r in vals:
        a = " ".join((r[0] or "").split()).lower() if r else ""
        if not on:
            if a == start_label.lower():
                on = True
                continue
        else:
            if not a or any(a == s.lower() for s in stop_labels):
                break
            out.append(r)
    return out


def load(ws=None, tree_ws=None, aliases=None):
    """Everything the DD render needs. Returns a dict — see module docstring."""
    from automations.recruiting_report import fill as _fill
    if ws is None or tree_ws is None:
        sh = _fill._client().open_by_key(WORKBOOK_ID)
        ws = ws or sh.worksheet(DD_TAB)
        tree_ws = tree_ws or sh.worksheet(TREE_TAB)
    aliases = F.load_alias_map() if aliases is None else aliases
    vals = ws.get_all_values()
    hdr = vals[0]
    wk_cols = [(i, h.strip()) for i, h in enumerate(hdr) if _WEEK_RE.match((h or "").strip())]
    weeks = [w for _, w in wk_cols[:WOW_WEEKS]]
    tot_col = next((i for i, h in enumerate(hdr) if "total dd" in (h or "").lower()), 4)

    icds, by_key = [], {}
    for r in vals[1:]:
        nm = (r[0] or "").strip()
        if not nm or nm.lower().startswith("total"):
            continue
        if len(r) > 1 and r[1].strip().upper() != "YES":
            continue
        row = {"name": nm, "key": _key(nm, aliases),
               "campaign": (r[2] or "").strip() if len(r) > 2 else "",
               "org": (r[3] or "").strip() if len(r) > 3 else "",
               "total": money(r[tot_col]) if tot_col < len(r) else 0.0,
               "weeks": [money(r[i]) if i < len(r) else 0.0 for i, _ in wk_cols[:WOW_WEEKS]]}
        icds.append(row)
        by_key[row["key"]] = row

    # ---- the tree: column index == generation depth; "(1/2)" halves the weight
    kids, last = collections.defaultdict(list), {}
    for r in tree_ws.get_all_values()[1:]:
        for j, c in enumerate(r):
            raw = (c or "").strip()
            if not raw or raw.lower() in ("org heads", "adoptions", "no dd"):
                continue
            k = _key(raw, aliases)
            m = _SPLIT_RE.search(raw)
            wt = (int(m.group(1)) / int(m.group(2))) if m else 1.0
            for d in list(last):
                if d >= j:
                    del last[d]
            if j - 1 in last:
                kids[last[j - 1]].append((k, wt))
            last[j] = k

    excluded = {_key(n, aliases) for n in ADOPTIONS + SPECIAL}

    def _members(k, wt=1.0, seen=frozenset()):
        if k in excluded:
            return {}
        out = {k: wt}
        for c, cw in kids.get(k, []):
            if (k, c) in seen:
                continue
            for k2, v2 in _members(c, wt * cw, seen | {(k, c)}).items():
                out[k2] = out.get(k2, 0) + v2
        return out

    def _sum(k, idx=None, outside=()):
        mem = _members(k)
        for o in outside:
            for k2 in _members(_key(o, aliases)):
                mem.pop(k2, None)
        tot = 0.0
        for k2, wt in mem.items():
            row = by_key.get(k2)
            if not row:
                continue
            tot += (row["weeks"][idx] if idx is not None else row["total"]) * wt
        return round(tot, 2)

    podium = []
    for ld in LEADERS:
        k = _key(ld["name"], aliases)
        out = ld.get("outside", ())
        podium.append({**ld, "key": k,
                       "week": _sum(k, 0, out), "total": _sum(k, None, out),
                       "weeks": [_sum(k, i, out) for i in range(len(weeks))]})
    podium.sort(key=lambda d: -d["week"])

    # ---- pre-computed blocks (read, never recompute)
    headline = next((money(r[wk_cols[0][0]]) for r in vals
                     if r and "total - raf" in (r[0] or "").strip().lower()
                     and wk_cols[0][0] < len(r)), None)
    def _block(start):
        rows = []
        for r in _labelled_block(vals, start):
            lab = (r[0] or "").strip()
            if not lab:
                continue
            rows.append({"name": lab,
                         "total": r[tot_col] if tot_col < len(r) else "",
                         "weeks": [r[i] if i < len(r) else "" for i, _ in wk_cols[:WOW_WEEKS]]})
        return rows
    avg = _block("ORG/CAMPAIGNS")
    active = _block("CAMPAIGNS")

    tracked = [r for r in icds if r["key"] in excluded]
    return {"weeks": weeks, "icds": icds, "podium": podium, "headline": headline,
            "avg": avg, "active_owners": active, "tracked_separately": tracked,
            "org_count": len(icds)}


if __name__ == "__main__":
    d = load()
    print(f"week {d['weeks'][0]}  headline ${d['headline']:,.2f}  "
          f"{d['org_count']} active ICDs")
    print("\npodium:")
    for p in d["podium"]:
        print(f"  {p['name']:18} ${p['week']:>12,.2f}   2026 ${p['total']:>14,.2f}")
    print(f"\nexcluded from roll-up but tracked ({len(d['tracked_separately'])}):")
    for t in d["tracked_separately"]:
        print(f"  {t['name']:18} ${t['weeks'][0]:>12,.2f}   2026 ${t['total']:>14,.2f}")
    print(f"\nAVG DD rows: {len(d['avg'])}   Active-owner rows: {len(d['active_owners'])}")
