"""NDS churn math -- the LUCY CHURN rules (vantura_churn.compute) run over the
NDS-SN (RES-ATT-OOF) ORDERLOG export, Owner & Office = CARLOS HIDALGO.

Same counting as the B2B report, by design (Carlos 2026-11-09: "see if we
can make the same report"):
  * churn units = DISTINCT lines (per product) ACTIVATED in the last 30 days,
    by activation ("posted") date; a unit churned when its status is
    Disconnected. Products: Wireless / Air / Internet (Internet stays for
    the tab's shape; NDS sells wireless + Internet Air).
  * WIRELESS COUNTS PORT LINES ONLY (spe.TN Type == port) -- that is what
    Smart Circle's own NDS CHURNRATES view counts as "Activated SPE/SP":
    proven 2026-11-09, ours 17/136 became its 16/126 the moment upgrades
    (5), tablet/wearable "new" lines (4) and one untyped line were left
    out, rep by rep. Those lines are counted separately (summary
    'excluded') and named on the status line; they are not churn base.
  * the hidden helper block = one row per product + customer (+ BAN when the
    export carries one), soonest to fall off first; same 16 columns as LUCY
    CHURN except offset +9, which was CRU/IRU ("there's not going to be CRU
    or IRU"): it shows the line type and footprint ("port · OOF"). The NDS
    ORDERLOG export has NO disconnect-reason or non-pay column (the B2B one
    did), so a reason cannot come from this source.
  * activation rates (office + per rep) = the Activation Rate by Rep rule on
    the NDS Metrics thread: sold by ORDER-date age (0-30 / 31-60 days),
    activated = Posted now or Disconnected (it was active before it fell).
  * wireless split BYOD vs Non-BYOD (Package / device / installment cell says
    BYOD) because the SOW tiers them separately (comp.py).
Column names are resolved by header text (exact, then prefix), never by
position; `probe()` prints the mapping. Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import collections
import datetime as dt
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from automations.nds_churn import comp

OWNER_TOKENS = ("CARLOS", "HIDALGO")
PRODUCT_ORDER = ["Wireless", "Air", "Internet"]
DISCONNECTED = ("disconnected",)
ACTIVATED = ("posted", "disconnected")        # Disconnected was active first
WINDOW_DAYS = 30
BUCKETS = ("0-30", "31-60")

# key -> header candidates, most specific first. Resolved exact (normalised)
# first, then by prefix; a prefix hit on a "... Date" header is refused unless
# the candidate itself says "date" ("dtr status" must not land on "DTR Status
# Date").
FIELDS = {
    "owner": ("owner & office", "owner name", "owner"),
    "rep": ("rep",),
    "customer": ("customer name",),
    "order_date": ("sp.order date (copy)", "sp.order date", "order date"),
    "spm": ("sp.spm number", "spm number"),
    "ban": ("spe.account ban", "account ban"),
    "product": ("product type (broken out)", "product type (broken out lvl 3)",
                "product type", "product"),
    "status": ("dtr status (enriched)", "dtr status", "spe.status",
               "order status"),
    "status_date": ("dtr status date", "status date"),
    "posted": ("spe.dtr posted date (copy)", "spe.dtr posted date",
               "dtr posted date", "activatoin date (order log)",
               "activation date (order log)", "dtr active date",
               "activation date", "dtr first available"),
    "spe": ("spe.name",),
    "tn": ("spe.tn",),
    "tn_type": ("spe.tn type", "tn type"),
    "device": ("spe.phone", "device", "phone"),
    "wireless_ip": ("wireless installment plan", "wireless ip"),
    "abp": ("auto bill pay", "abp"),
    "reason": ("disconnect reason (consolidated)", "disconnect reason"),
    "package": ("package",),
    "ported_from": ("ported from",),
    "if_oof": ("if/oof",),
    "nonpay_days": ("non pmt days to rolloff",),
    "measure": ("measure names",),
}
REQUIRED = ("owner", "rep", "customer", "order_date", "product", "status",
            "posted")


def _norm(s) -> str:
    return " ".join(str(s or "").lower().split())


def find_col(header: List[str], cands) -> Optional[int]:
    norm = [_norm(h) for h in header]
    for c in cands:
        c = _norm(c)
        if c in norm:
            return norm.index(c)
    for c in cands:
        c = _norm(c)
        hits = [i for i, h in enumerate(norm)
                if h.startswith(c) and ("date" in c or not h.endswith("date"))]
        if hits:
            return hits[0]
    return None


def parse_date(v) -> Optional[dt.date]:
    if v in (None, ""):
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    s = str(v).strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%m-%d-%Y"):
        try:
            return dt.datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        return dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    return None


def fmt_date(d: Optional[dt.date]) -> str:
    return f"{d.month}/{d.day}/{d.year}" if d else ""


def product_of(label: str) -> Optional[str]:
    u = (label or "").upper()
    if "AIR" in u:
        return "Air"
    if "WIRELESS" in u:
        return "Wireless"
    if "INTERNET" in u:
        return "Internet"
    return None


def is_byod(rec: dict) -> bool:
    blob = " ".join(rec.get(k, "") for k in ("package", "device",
                                              "wireless_ip")).upper()
    return "BYOD" in blob


# ------------------------------------------------------------------ load ----

def read_rows(path: Path) -> List[List[str]]:
    """The export as a cell grid. The Tableau .csv endpoint writes a comma
    file; a giant Notes cell must not kill the parse."""
    import csv
    csv.field_size_limit(10_000_000)
    raw = Path(path).read_bytes()
    text = None
    for enc in ("utf-8-sig", "utf-16", "utf-8", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise RuntimeError(f"cannot decode {path}")
    delim = "\t" if text.count("\t") > text.count(",") else ","
    return list(csv.reader(text.splitlines(), delimiter=delim))


def load_owner_lines(path: Path, log=print, owner_tokens=OWNER_TOKENS
                     ) -> Tuple[List[str], Dict[str, Optional[int]],
                                List[dict]]:
    """-> (header, field index map, line records on Carlos's owner). The
    export is long-format (one row per Measure Name); only the 'Unit Count'
    measure is kept so each line appears once (nds_metrics.load_crew's rule)."""
    rows = read_rows(path)
    hdr_i = next((i for i, r in enumerate(rows)
                  if any(_norm(c) == "rep" for c in r)), None)
    if hdr_i is None:
        raise RuntimeError("no header row with a 'Rep' column in the export")
    header = [str(h or "").strip() for h in rows[hdr_i]]
    data = rows[hdr_i + 1:]
    ix = {k: find_col(header, cands) for k, cands in FIELDS.items()}
    missing = [k for k in REQUIRED if ix[k] is None]
    if missing:
        raise RuntimeError(f"export is missing {missing}; header = {header}")
    i_mn = ix["measure"]
    if i_mn is not None:
        measures = sorted({str(r[i_mn]).strip() for r in data if len(r) > i_mn})
        keep = next((m for m in measures if "unit count" in m.lower()),
                    measures[0] if measures else "")
        before = len(data)
        data = [r for r in data if len(r) > i_mn and str(r[i_mn]).strip() == keep]
        log(f"[nds_churn] long-format export: kept {keep!r} ({before} -> {len(data)})")
    out = []
    i_owner = ix["owner"]
    for r in data:
        if len(r) <= i_owner:
            continue
        owner = str(r[i_owner]).upper()
        if not all(t in owner for t in owner_tokens):
            continue
        rec = {k: ("" if i is None or i >= len(r) else str(r[i]).strip())
               for k, i in ix.items()}
        rec["order_date"] = parse_date(rec["order_date"])
        rec["posted"] = parse_date(rec["posted"])
        rec["status_date_d"] = parse_date(rec["status_date"])
        rec["prod"] = product_of(rec["product"])
        rec["byod"] = is_byod(rec)
        out.append(rec)
    log(f"[nds_churn] {len(out)} line(s) on Carlos's owner "
        f"({len(data)} in the export)")
    return header, ix, out


def _line_key(ln: dict):
    return ln["spe"] or (ln["spm"], ln["tn"], ln["customer"], ln["product"])


PORT = "port"


def line_kind(ln: dict) -> str:
    """'port' (a voice port line -- churn base), 'upgrade', 'new' (tablet /
    wearable / hotspot add-a-line on NDS) or 'untyped'."""
    t = (ln.get("tn_type") or "").strip().lower()
    return t if t in (PORT, "upgrade", "new") else "untyped"


def churn_units(lines: List[dict], today: dt.date, days: int = WINDOW_DAYS,
                ports_only: bool = True) -> List[dict]:
    """Distinct activated lines in the window. Wireless keeps port lines only
    unless ports_only=False (the excluded kinds are reported by
    excluded_units)."""
    cutoff = today - dt.timedelta(days=days)
    seen, units = set(), []
    for ln in lines:
        p = ln["prod"]
        if not p or not ln["posted"] or ln["posted"] < cutoff or ln["posted"] > today:
            continue
        if ports_only and p == "Wireless" and line_kind(ln) != PORT:
            continue
        key = (p, _line_key(ln))
        if key in seen:
            continue
        seen.add(key)
        units.append(ln)
    return units


def excluded_units(lines: List[dict], today: dt.date) -> Dict[str, int]:
    """Activated wireless lines in the window that are NOT churn base, by
    kind: {'upgrade': n, 'new': n, 'untyped': n}."""
    out: Dict[str, int] = collections.Counter()
    for u in churn_units(lines, today, ports_only=False):
        if u["prod"] == "Wireless" and line_kind(u) != PORT:
            out[line_kind(u)] += 1
    return dict(out)


def churn_summary(lines: List[dict], today: dt.date) -> dict:
    base = {p: 0 for p in PRODUCT_ORDER}
    disc = {p: 0 for p in PRODUCT_ORDER}
    split = {"byod": {"base": 0, "disc": 0}, "non_byod": {"base": 0, "disc": 0}}
    for u in churn_units(lines, today):
        dead = u["status"].lower() in DISCONNECTED
        base[u["prod"]] += 1
        if dead:
            disc[u["prod"]] += 1
        if u["prod"] == "Wireless":
            s = split["byod" if u["byod"] else "non_byod"]
            s["base"] += 1
            if dead:
                s["disc"] += 1
    return {"base": base, "disc": disc, "split": split,
            "excluded": excluded_units(lines, today),
            "base_total": sum(base.values()), "disc_total": sum(disc.values())}


def unmapped_products(lines: List[dict], today: dt.date) -> Dict[str, int]:
    cutoff = today - dt.timedelta(days=WINDOW_DAYS)
    c: Dict[str, int] = collections.Counter()
    for ln in lines:
        if ln["prod"] is None and ln["posted"] and ln["posted"] >= cutoff:
            c[ln["product"] or "(blank)"] += 1
    return dict(c)


def _join_uniq(vals, sep=" / "):
    seen, out = set(), []
    for v in vals:
        v = (v or "").strip()
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return sep.join(out)


_ABBR = {"Wireless": "W", "Internet": "INT", "Air": "AIR"}


def helper_block(lines: List[dict], today: dt.date) -> List[List]:
    """The hidden 16-column rows (formulas at +3 and +13 left None for
    fill.update_churn_tab to inject). One row per product + account."""
    groups: Dict[tuple, List[dict]] = collections.defaultdict(list)
    for u in churn_units(lines, today):
        if u["status"].lower() not in DISCONNECTED:
            continue
        groups[(u["prod"], u["customer"], u["ban"])].append(u)

    acct: Dict[tuple, Dict[str, set]] = collections.defaultdict(
        lambda: collections.defaultdict(set))
    for ln in lines:
        if ln["prod"]:
            k = ln["ban"] or ln["customer"]
            acct[k][_ABBR.get(ln["prod"], "OTH")].add(_line_key(ln))

    def _acct_lines(ban, customer) -> str:
        prods = acct.get(ban or customer)
        if not prods:
            return ""
        parts = [f"{len(prods[k])}{k}" for k in ("W", "INT", "AIR", "OTH")
                 if prods.get(k)]
        return f"{sum(len(v) for v in prods.values())} ({' · '.join(parts)})"

    def _device(g) -> str:
        if g["byod"]:
            return "BYOD"
        return g["device"] or g["package"]

    rows = []
    for p in PRODUCT_ORDER:
        prod = [(k, v) for k, v in groups.items() if k[0] == p]
        prod.sort(key=lambda kv: (min(u["posted"] for u in kv[1]), kv[0][1]))
        for (_, customer, ban), grp in prod:
            posted = min(u["posted"] for u in grp)
            falloff = posted + dt.timedelta(days=WINDOW_DAYS)
            disc_real = min((g["status_date_d"] for g in grp
                             if g["status_date_d"]), default=None)
            remaining = sum(len(v) for _, v in prod
                            if min(u["posted"] for u in v) > posted)
            rows.append([
                f"{(falloff - today).days}d",                 # +0 Days Left
                fmt_date(falloff),                            # +1 Fall-Off Date
                len(grp),                                     # +2 Lines
                None,                                         # +3 churn-after formula
                customer,                                     # +4 Customer
                _join_uniq(g["rep"] for g in grp),            # +5 Sales Rep
                fmt_date(min((g["order_date"] for g in grp
                              if g["order_date"]), default=None)),  # +6 Order Date
                fmt_date(posted),                             # +7 Activation Date
                fmt_date(disc_real),                          # +8 Disconnect Date
                _join_uniq(f"{line_kind(g)} · {g['if_oof']}".strip(" ·")
                           for g in grp),                     # +9 Line · IF/OOF (was CRU/IRU)
                _acct_lines(ban, customer),                   # +10 Lines on Acct
                _join_uniq(_device(g) for g in grp),          # +11 Phone/BYOD
                p,                                            # +12 Product Type
                None,                                         # +13 notes formula
                p,                                            # +14 Product key
                remaining,                                    # +15 remaining after
            ])
    return rows


def activation_rates(lines: List[dict], today: dt.date) -> Tuple[dict, dict]:
    """-> (office, reps) in fill.update_activation_rates' shape:
    {'0-30': {'activated', 'sold', 'rate'}, '31-60': {...}}."""
    def _blank():
        return {b: {"activated": 0, "sold": 0, "rate": None} for b in BUCKETS}
    office = _blank()
    reps: Dict[str, dict] = {}
    for ln in lines:
        od = ln["order_date"]
        if not od:
            continue
        age = (today - od).days
        bucket = "0-30" if 0 <= age <= 30 else "31-60" if 31 <= age <= 60 else None
        if bucket is None:
            continue
        act = ln["status"].lower() in ACTIVATED
        for slot in (office[bucket],
                     reps.setdefault(ln["rep"] or "(no rep)", _blank())[bucket]):
            slot["sold"] += 1
            if act:
                slot["activated"] += 1
    for d in [office] + list(reps.values()):
        for b in BUCKETS:
            s = d[b]
            s["rate"] = (s["activated"] / s["sold"]) if s["sold"] else None
    return office, reps


# ------------------------------------------------------------- tiers ----

def _pct(disc: int, base: int) -> Optional[float]:
    return (100.0 * disc / base) if base else None


def tier_status(summary: dict, today: dt.date) -> dict:
    """Where the live 0-30 wireless churn sits on the SOW tier charts, next
    to the tier the latest Churn Notice placed us at. The notice is the word
    that pays; the live band is the early read."""
    sp = summary["split"]
    out = {"notice": dict(comp.NOTICE), "products": {},
           "excluded": summary.get("excluded") or {}}
    for key, byod, bands in (("non_byod", False, comp.NONBYOD_0_30),
                             ("byod", True, comp.BYOD_0_30)):
        base, disc = sp[key]["base"], sp[key]["disc"]
        pct = _pct(disc, base)
        tier = comp.tier_for(pct, bands)
        code = comp.NOTICE[key]
        oof, infp = comp.payout(code, byod)
        t90 = comp.notice_90(byod)
        live_code = f"{tier}-{t90}" if tier else None
        live_pay = comp.payout(live_code, byod) if live_code else None
        out["products"][key] = {
            "base": base, "disc": disc, "pct": pct, "tier": tier,
            "notice_code": code, "notice_pay": (oof, infp),
            "live_code": live_code, "live_pay": live_pay,
            "auto": base <= comp.AUTO_TIER_MAX_ACTIVATIONS,
        }
    return out


def status_line(ts: dict) -> str:
    n, b = ts["products"]["non_byod"], ts["products"]["byod"]

    def _live(p, label):
        if p["pct"] is None:
            return f"{label} 0 activated"
        return (f"{label} {p['disc']}/{p['base']} = {p['pct']:.1f}% "
                f"(Tier {p['tier']} band)")
    eff = dt.date.fromisoformat(ts["notice"]["effective"])
    exc = ts.get("excluded") or {}
    names = {"new": "tablet/wearable line", "upgrade": "upgrade", "untyped": "untyped line"}
    exc_txt = ", ".join(f"{v} {names.get(k, k)}{'s' if v != 1 else ''}"
                        for k, v in sorted(exc.items())) or "none"
    return (f"Churn Notice eff {eff.month}/{eff.day}: Non-BYOD Tier "
            f"{n['notice_code']} (${n['notice_pay'][0]} OOF / ${n['notice_pay'][1]} INFP per port line) · "
            f"BYOD Tier {b['notice_code']} (${b['notice_pay'][0]} / ${b['notice_pay'][1]}).  "
            f"Live 0-30 day: {_live(n, 'Non-BYOD')} · {_live(b, 'BYOD')}.  "
            f"Port lines only, like Smart Circle's churn view (not counted: {exc_txt}).  "
            f"≤{comp.AUTO_TIER_MAX_ACTIVATIONS} port activations in the month = automatic Tier "
            f"{comp.AUTO_TIER}.  Rep tier bonus DNQ: 0-30 churn >{comp.DNQ_CHURN_PCT:.0f}% "
            f"(at {comp.DNQ_CHURN_MIN_ACTIVATIONS}+ activations) or activation rate "
            f"<{comp.DNQ_ACT_RATE_PCT:.0f}% (at {comp.DNQ_ACT_RATE_MIN_SALES}+ sales).")


def probe_text(header: List[str], ix: Dict[str, Optional[int]],
               lines: List[dict], today: dt.date) -> str:
    """What the export carries -- run on Lucy 2 before trusting the mapping."""
    out = [f"header ({len(header)}): " + " | ".join(header)]
    out.append("mapping: " + ", ".join(
        f"{k}={header[i]!r}" if i is not None else f"{k}=MISSING"
        for k, i in ix.items()))
    out.append(f"lines on owner: {len(lines)}")
    for key in ("status", "product", "reason", "tn_type", "if_oof"):
        c = collections.Counter(ln[key] or "(blank)" for ln in lines)
        out.append(f"{key}: " + ", ".join(f"{k}={v}" for k, v in c.most_common(12)))
    out.append(f"byod lines: {sum(1 for ln in lines if ln['byod'])}; "
               f"with BAN: {sum(1 for ln in lines if ln['ban'])}; "
               f"with SPE: {sum(1 for ln in lines if ln['spe'])}; "
               f"with posted: {sum(1 for ln in lines if ln['posted'])}; "
               f"with status date: {sum(1 for ln in lines if ln['status_date_d'])}")
    ods = [ln["order_date"] for ln in lines if ln["order_date"]]
    pds = [ln["posted"] for ln in lines if ln["posted"]]
    if ods:
        out.append(f"order dates {min(ods)} .. {max(ods)}")
    if pds:
        out.append(f"posted dates {min(pds)} .. {max(pds)}")
    s = churn_summary(lines, today)
    out.append(f"0-30 by posted: base {s['base']} disc {s['disc']} split {s['split']}")
    um = unmapped_products(lines, today)
    if um:
        out.append(f"UNMAPPED products in window: {um}")
    reasonish = [h for h in header if any(k in h.lower() for k in
                                           ("reason", "pmt", "cancel", "churn", "rolloff"))]
    out.append("reason-ish headers: " + (" | ".join(reasonish) or "(none)"))
    out.append(f"non-pay days populated: {sum(1 for ln in lines if ln['nonpay_days'])}")
    units = churn_units(lines, today)
    wl = [u for u in units if u["prod"] == "Wireless"]
    out.append("0-30 wireless units by tn_type: " + ", ".join(
        f"{k}={v}" for k, v in collections.Counter(u["tn_type"] or "(blank)" for u in wl).most_common()))
    kinds = collections.Counter(
        "tablet/watch" if any(w in (u["device"] + " " + u["package"]).lower()
                              for w in ("tab ", "tab-", "tablet", "watch", "ipad", "wearable"))
        else ("byod" if u["byod"] else "phone") for u in wl)
    out.append("0-30 wireless units by device kind: " + ", ".join(f"{k}={v}" for k, v in kinds.items()))
    out.append("0-30 UNITS (customer | rep | posted | status | tn_type | device | package | byod | if_oof | reason | nonpay | spe):")
    for u in sorted(units, key=lambda x: (x["rep"], x["posted"] or dt.date.min)):
        out.append(" | ".join(str(x) for x in (
            u["customer"], u["rep"], u["posted"], u["status"], u["tn_type"], u["device"][:40],
            u["package"][:40], "BYOD" if u["byod"] else "", u["if_oof"], u["reason"],
            u["nonpay_days"], u["spe"])))
    return "\n".join(out)
