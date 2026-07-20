"""DTR status -> colour for Carlos's ATT B2B Order Log.

Carlos's rule, from the Loom (0:59-1:45), verbatim in intent:
  * "post it as active… if it could stay labeled as Posted, because everything
    else calls it posted" — keep the WORD "Posted", colour it green.
  * "Delivered should be yellow, because it's pending."
  * "cancelled and disconnected would be the red ones."
  * "Shipped, porting issue, those are also yellow."

That covers five statuses. The 2026-07-19 Lucy 2 probe found FIFTEEN in the real
export, so ~34,000 rows (15%) had no colour and would have rendered blank-white
— which reads as "this order has no status", not "we haven't mapped this yet".

SPELLING: the data says "Canceled" (one L). Carlos says "cancelled". The first
draft of this map used his spelling and therefore matched ZERO of the 14,008
cancelled orders, silently. Match the DATA's spelling; _norm() below also folds
the double-L variant so a future Tableau edit either way still lands.

The ten additions follow Carlos's own logic rather than inventing a new one:
in-flight/awaiting-something -> yellow (his "pending" bucket, same as Delivered
and Shipped), terminal-and-bad -> red (his Cancelled/Disconnected bucket).
Megan 2026-07-19: "just build and he can tweak later if needed." Each is one
line to change.

Row counts are from that probe, kept so the next person can see at a glance
which of these actually carry weight.
"""
from __future__ import annotations

GREEN = "green"
YELLOW = "yellow"
RED = "red"

STATUS_COLORS = {
    # --- Carlos named these explicitly -------------------------------------
    "posted":             GREEN,    # 158,612 — keep the label "Posted"
    "shipped":            YELLOW,   #  20,916
    "canceled":           RED,      #  14,008 — NB one L in the data
    "disconnected":       RED,      #  10,896
    "delivered":          YELLOW,   #   4,164
    "porting issue":      YELLOW,   #   2,764
    # --- inferred, following his in-flight = yellow logic -------------------
    "scheduled":          YELLOW,   #   5,916 — booked, not yet done
    "byod":               YELLOW,   #   2,060 — bring-your-own-device, in flight
    "port approved":      YELLOW,   #   1,840 — port cleared, not yet ported
    "pending":            YELLOW,   #   1,780
    "confirmed":          YELLOW,   #   1,704 — confirmed but not yet posted
    "pending shipment":   YELLOW,   #   1,320
    "pending order port": YELLOW,   #     808
    "open":               YELLOW,   #     640
    # Found by the FIRST LIVE RUN (2026-07-19 22:28), not by the probe — the
    # probe's 60-day all-owner pull never surfaced them. Proof that a fixed
    # status list goes stale on its own, and the reason unmapped() exists and
    # is called on every run rather than just once at build time.
    "backordered":          YELLOW,  # in flight, awaiting stock
    "pending valid payment": YELLOW,  # pending, same family as "Pending"
    # --- inferred, terminal + bad = red ------------------------------------
    "returned":           RED,      #     160
}

# Hex fills matching the BOX Order Log's look, so Carlos's two logs read the
# same. Sourced from his own hand-built tab, not picked fresh.
FILL_HEX = {
    GREEN:  "#B7E1CD",
    YELLOW: "#FFF2CC",
    RED:    "#F4C7C3",
}


def _norm(status: str) -> str:
    """Fold to the map's key form. Also collapses the Cancelled/Canceled
    spelling split so either upstream spelling resolves."""
    s = " ".join((status or "").split()).lower()
    if s == "cancelled":
        return "canceled"
    return s


def color_for(status: str):
    """Colour name for a DTR status, or None if we have never seen it.

    None is deliberately distinguishable from 'no colour': callers should
    FLAG an unknown status rather than render it plain, because a silently
    uncoloured row is exactly the failure this module exists to prevent."""
    return STATUS_COLORS.get(_norm(status))


def fill_for(status: str):
    """Hex fill for a status, or None when unmapped."""
    c = color_for(status)
    return FILL_HEX.get(c) if c else None


def unmapped(statuses) -> list:
    """Every distinct status with no colour rule — call this on each run and
    surface the result. New statuses appear upstream without warning; the log
    should say so rather than quietly render them white."""
    seen, out = set(), []
    for s in statuses:
        n = _norm(s)
        if not n or n in seen:
            continue
        seen.add(n)
        if n not in STATUS_COLORS:
            out.append(s)
    return out
