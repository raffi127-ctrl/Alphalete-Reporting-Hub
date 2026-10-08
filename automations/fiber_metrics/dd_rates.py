"""Fiber Metrics phase 2 — derive the per-unit payout from Raf's DD.

Carlos 2026-10-08: "go through Raf's direct deposit to find out what the
payout is on every unit" — the pricing authority for the Fiber Revenue
Board, Activation Revenue Overview and Tiered Bonus is the DD itself, not a
comp sheet nobody has.

HOW: the latest settled week's ORG DD Detail (the same crosstab the payroll
pulls) joined to the D2D A.Order Log on the key the commission sheet
already trusts (~96%): DD `cl.Production Lookup` <-> order log `spe.Name`
(SPE-########). Each joined pair gives one PAID line with its order-log
attributes; the payout structure shows itself as a histogram of discrete
`Commission Base to ICD` values per attribute group (same way the B2B SOW
rates were reverse-engineered, but with base vs bonus already split out).

Output: a text report DM'd to Carlos — distinct base values with counts,
grouped by the line attributes that actually discriminate — for him to
bless before any dollar board renders. READ-ONLY; posts nothing anywhere
else.

    lucy rerun fiber_dd_rates            (Lucy 2)
"""
from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "output" / "fiber_metrics"
CARLOS = "U046G04P5LG"


def _norm_key(v: str) -> str:
    return str(v or "").strip().upper().replace("SPE-", "").lstrip("0")


def _money(v) -> float:
    try:
        return float(str(v).replace("$", "").replace(",", "").strip() or 0)
    except ValueError:
        return 0.0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="fiber_dd_rates")
    ap.add_argument("--dm", default=None, metavar="U...",
                    help="DM the derivation report to this user")
    a = ap.parse_args(argv)

    from automations.commission_sheet import sources as S
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # ---- order log, keyed by SPE ---------------------------------------
    ol_rows = S.read_crosstab(S.fetch_order_log())
    hdr_i = next(i for i, r in enumerate(ol_rows)
                 if any(str(c).strip().lower() == "rep" for c in r))
    ol_hdr = [str(c).strip() for c in ol_rows[hdr_i]]
    ol_norm = [" ".join(h.lower().split()) for h in ol_hdr]

    def ocol(*cands):
        for c in cands:
            c = " ".join(c.lower().split())
            if c in ol_norm:
                return ol_norm.index(c)
        for c in cands:
            c = " ".join(c.lower().split())
            for i, h in enumerate(ol_norm):
                if c in h:
                    return i
        return None

    i_spe = ocol("spe.name")
    i_prod = ocol("product type (broken out)", "product")
    i_owner = ocol("owner name", "owner")
    i_prov = ocol("spe.provider")
    i_rep = ocol("rep")
    i_tn = ocol("spe.tn type", "tn type")
    i_byod = ocol("wireless installment plan", "byod")
    if i_spe is None:
        print("OL header has no spe.Name — header: " + " | ".join(ol_hdr))
        return 1
    ol_by_spe = {}
    for r in ol_rows[hdr_i + 1:]:
        k = _norm_key(r[i_spe] if len(r) > i_spe else "")
        if k:
            ol_by_spe.setdefault(k, r)

    def oc(r, i):
        return (str(r[i]).strip() if r is not None and i is not None
                and len(r) > i and r[i] else "")

    # ---- DD ------------------------------------------------------------
    dd_rows = S.read_crosstab(S.fetch_dd())
    dd_hdr_i = next(i for i, r in enumerate(dd_rows)
                    if any("total $" in str(c).lower() for c in r))
    dd_hdr = [str(c).strip() for c in dd_rows[dd_hdr_i]]
    dd_norm = [" ".join(h.lower().split()) for h in dd_hdr]

    def dcol(*cands):
        for c in cands:
            c = " ".join(c.lower().split())
            for i, h in enumerate(dd_norm):
                if c in h:
                    return i
        return None

    d_pl = dcol("production lookup")
    d_base = dcol("commission base to icd")
    d_ec = dcol("ec bonus to icd")
    d_bon = dcol("bonuses to icd")
    d_adj = dcol("adjustments to icd")
    d_tot = dcol("total $ to icd")
    d_rep = dcol("icd rep name", "rep")
    d_desc = dcol("description")
    missing = [n for n, i in (("Production Lookup", d_pl),
                              ("Commission Base", d_base),
                              ("Total $", d_tot)) if i is None]
    if missing:
        print(f"DD header missing {missing}: " + " | ".join(dd_hdr))
        return 1

    lines = ["FIBER PER-UNIT PAYOUT — derived from Raf's latest DD",
             f"(DD rows joined to the D2D order log on SPE; "
             f"{len(ol_by_spe)} order-log SPE keys loaded)", ""]
    data = dd_rows[dd_hdr_i + 1:]
    matched = unmatched = 0
    groups = collections.defaultdict(collections.Counter)
    comps = collections.defaultdict(lambda: collections.Counter())
    for r in data:
        k = _norm_key(r[d_pl] if len(r) > d_pl else "")
        if not k:
            continue
        ol = ol_by_spe.get(k)
        if ol is None:
            unmatched += 1
            continue
        matched += 1
        base = _money(r[d_base] if len(r) > d_base else 0)
        prod = oc(ol, i_prod) or "(no product)"
        prov = oc(ol, i_prov)
        # Grand-total rows join to the export's own Total line — never a
        # rate (first run surfaced a $242,794.50 'base'). Skip, loudly.
        if "total" in prod.lower() or "total" in oc(ol, i_rep).lower():
            matched -= 1
            lines.append(f"  (skipped a Total row: base "
                         f"${base:,.2f} — aggregate, not a rate)")
            continue
        key = f"{prod}" + (f" / {prov}" if prov else "")
        if prod.upper() == "WIRELESS":
            tn = oc(ol, i_tn)
            byod = oc(ol, i_byod)
            if tn:
                key += f" / {tn}"
            if byod:
                key += f" / {byod}"
        groups[key][round(base, 2)] += 1
        for lbl, di in (("EC bonus", d_ec), ("Bonuses", d_bon),
                        ("Adjustments", d_adj)):
            if di is not None:
                v = _money(r[di] if len(r) > di else 0)
                if v:
                    comps[key][f"{lbl} {v:+,.2f}"] += 1
    lines.append(f"JOIN: {matched} matched / {unmatched} unmatched DD rows")
    lines.append("")
    for key in sorted(groups):
        c = groups[key]
        total_n = sum(c.values())
        lines.append(f"▶ {key}  ({total_n} paid line(s))")
        for val, n in c.most_common(8):
            lines.append(f"    base ${val:,.2f} × {n}")
        extras = comps.get(key)
        if extras:
            for e, n in extras.most_common(5):
                lines.append(f"    + {e} × {n}")
        lines.append("")
    report = "\n".join(lines)
    print(report)
    (OUT_DIR / "fiber_dd_rates.txt").write_text(report, encoding="utf-8")
    if a.dm:
        from automations.shared.slack_metrics_post import _bot_client
        client = _bot_client()
        ch = client.conversations_open(users=a.dm)["channel"]["id"]
        client.chat_postMessage(
            channel=ch,
            text="📐 *Fiber per-unit payout derivation* (from Raf's latest "
                 "DD — bless these before the dollar boards build):\n```"
                 + report[:3500] + "```")
        print(f"[fib-dd] DM'd {a.dm}")
    print("=== done ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
