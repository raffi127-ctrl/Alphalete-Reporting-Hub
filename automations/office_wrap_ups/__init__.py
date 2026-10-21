"""Reps-that-didn't-send-wrap-ups, across Raf's captainship offices.

The multi-office sibling of rc_contact_sync_raf. Same question ("which
customers were never texted on Dylan's RingCentral line, and which reps owe
them a wrap-up"), same Slack format, but it scales to every office in one run
by swapping the data source:

  * rc_contact_sync_raf pulls ONE office's SaraPlus dealer (near-live, needs
    that office's login on a mini).
  * this pulls the ORG-WIDE Tableau Order Log (the same ALLREPS crosstab the
    disconnects / canceled_orders reports already use) ONCE, which carries
    Owner Name + Rep + Customer Name + Customer Phone + Product Type for every
    office at once — so no per-office SaraPlus logins are needed (those live
    only on each owner's own machine and never reach Lucy).

Trade-off: Tableau refreshes on a lag vs SaraPlus's near-live, so a very recent
sale may not appear until the next refresh; a daily re-run over a short
Order-Date window catches stragglers. Raf's own report stays on SaraPlus.

ONE shared RingCentral line (Dylan's — the rc_autoread account) is the texted
check for every office (Dylan 2026-10-21: all offices text wrap-ups from that
line). If an office's wrap-ups actually go out from a different line, that
office reads as ~100% un-texted — the signal to wire it to its own line.

Per office it posts to that office's own Slack channel (from
office_metrics.OFFICES): a header "Reps that didn't send wrap ups" + a threaded
reply of each un-texted customer (name / phone / Internet·TV·Wireless) with the
reps @tagged at the bottom. Nothing here writes a Sheet.
"""
