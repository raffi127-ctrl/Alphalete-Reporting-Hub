"""Cancel/disconnect customer feedback outreach.

Every day, text the customers who CANCELLED or DISCONNECTED the day before —
the same rows the #alphalete-sales daily post surfaces under 🚫 Canceled Orders
(canceled_orders) and ❎ Disconnected New Internets (disconnects) — a premade
message asking for honest written feedback, so the local office can use it for
coaching. Every outreach is logged, and when the customer replies the feedback
is logged too. Sends from Dylan's RingCentral line (214-845-6450) via a
dedicated JWT; dry-run is the default until a send is explicitly asked for.
"""
