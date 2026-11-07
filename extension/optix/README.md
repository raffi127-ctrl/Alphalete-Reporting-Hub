# Lucy Optix — Chrome extension (Verizon offices)

Verizon's Optix refuses its data to any browser a program launches (proven 2026-11-06:
hidden, visible, bundled Chromium and real Chrome all got an empty profile list). The office's
own everyday Chrome gets it fine — so Lucy reads Optix from there.

Every 10 minutes during selling hours it re-applies **today's date** on the Lead Details tab the
office keeps open, counts per rep, and sends **counts only** (never an address) to the Lucy relay
under the office's key — knocks for the knock board, "Sale Made" for sale alerts.
The outcome rules are `rules.json`, shared with `automations/icd_alerts/optix_read.py`
(a test keeps them identical).

## Install (on the office's ECO computer, ~1 min)
1. Chrome → `chrome://extensions` → **Developer mode** on.
2. **Load unpacked** → pick this `extension/optix` folder. Pin it.
3. Click the icon → **Office code** + **Lucy key** (from the Relay Keys tab) → tick **Test mode** first → Save.
4. In Optix: profile → **Dashboard** → **SMART LEADS** → **Lead Details**. Leave that tab open.
5. **Send my knocks now** → it should say "Test mode: N reps, N knocks". Then untick Test mode.

Nothing goes live for an office until it is on ECO and its rooms are approved (Megan 2026-11-06).
