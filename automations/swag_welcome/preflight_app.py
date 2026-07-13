"""Preflight UI for new-hire swag texts — upload, review, edit, run.

Standalone Streamlit page (7-year-old-simple, per house UX rules):
    streamlit run automations/swag_welcome/preflight_app.py

Flow:
  1. Upload the roster screenshot.
  2. Claude vision reads the rows → we normalize phones + split quoted names.
  3. Editable table: fix any name/phone, pick the real-name vs. quoted version
     for flagged rows, uncheck anyone to leave out.
  4. Preview a card, then Dry run (default) or Send.

Kept out of dashboard.py (Megan owns that file's structure) until the real
photo + message land and Megan approves a preview — then it gets wired as a
card under the 🏢 Office Operations profile.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import streamlit as st

from automations.swag_welcome import compose, extract, message, run as run_mod
from automations.swag_welcome.roster import build_roster, pretty_phone

st.set_page_config(page_title="New-Hire Swag Texts", page_icon="🏢", layout="wide")
st.title("🏢 New-Hire Swag Texts")
st.caption("Upload the roster screenshot → check the names & numbers → send each "
           "new hire a welcome text with their name on the swag card. "
           "Texts send from THIS machine's iMessage account.")

# --- 0. Always-on card preview --------------------------------------------
# Shows the handwriting-on-envelope for any name, before/without a roster, so
# you can eyeball the look any time.
with st.expander("👀 Preview the swag card", expanded=True):
    sample = st.text_input("Type a name to preview it on the card",
                           value="Lola", key="sample_name")
    if sample.strip():
        sp = Path(tempfile.gettempdir()) / f"swag_sample_{sample.strip()}.png"
        meta = compose.compose(sample.strip(), sp)
        st.image(str(sp), use_container_width=True)
        if not meta["used_real_photo"]:
            st.caption("⚠️ Placeholder card — real swag photo not found in "
                       "resources/swag/.")

st.markdown("---")

# --- 1. Upload -------------------------------------------------------------
up = st.file_uploader("Roster screenshot (Name · Last Name · Phone)",
                      type=["png", "jpg", "jpeg"])

if up and st.session_state.get("_uploaded_name") != up.name:
    with st.spinner("Reading names & numbers off the image…"):
        tmp = Path(tempfile.gettempdir()) / f"swag_upload_{up.name}"
        tmp.write_bytes(up.getbuffer())
        try:
            rows = extract.extract_rows(tmp)
            st.session_state["_recips"] = [r.to_dict() for r in build_roster(rows)]
            st.session_state["_uploaded_name"] = up.name
        except Exception as e:
            st.error(f"Couldn't read the roster: {e}")

recips = st.session_state.get("_recips", [])

if recips:
    # --- flags up top: warnings + rows that need a real-name/nickname choice
    flagged = [r for r in recips if r.get("warnings")]
    if flagged:
        st.warning("⚠️ Check these before sending:\n"
                   + "\n".join(f"- **{r['raw_name'] or '(no name)'}** — "
                               f"{', '.join(r['warnings'])}" for r in flagged))

    st.markdown("### Review & edit")
    st.caption("Fix any misread name or number. For a name in quotes, pick which "
               "version goes on the card. Uncheck anyone you don't want texted.")

    for i, r in enumerate(recips):
        c1, c2, c3, c4 = st.columns([0.5, 3, 3, 2])
        with c1:
            r["include"] = st.checkbox("send", value=r.get("include", True),
                                       key=f"inc_{i}", label_visibility="collapsed")
        with c2:
            if r.get("needs_quote_decision"):
                opts = [r["base_name"], r["quoted_alt"]]
                pick = st.radio(
                    f"Name (quoted: “{r['quoted_alt']}”)", opts,
                    index=opts.index(r["chosen_name"]) if r["chosen_name"] in opts else 0,
                    key=f"name_{i}", horizontal=True,
                    help="Real name (pronunciation guide) vs. preferred nickname")
                r["chosen_name"] = pick
            else:
                r["chosen_name"] = st.text_input("Name", value=r["chosen_name"],
                                                 key=f"name_{i}")
        with c3:
            new_phone = st.text_input("Phone", value=pretty_phone(r["phone_e164"]),
                                      key=f"phone_{i}")
            # Re-normalize if edited.
            from automations.swag_welcome.roster import normalize_phone
            e164, warn = normalize_phone(new_phone)
            r["phone_e164"] = e164
            r["phone_pretty"] = pretty_phone(e164)
        with c4:
            st.markdown(f"<div style='padding-top:1.9rem;opacity:0.7'>"
                        f"{'✅' if (r['include'] and r['phone_e164'] and r['chosen_name']) else '—'}"
                        f"</div>", unsafe_allow_html=True)

    st.markdown("---")

    # --- message copy ------------------------------------------------------
    st.markdown("### Message")
    manager = st.text_input("Manager name (signs the text)", value="",
                            placeholder="e.g. Megan")
    template = st.text_area("Welcome text ({name} = first name, {manager} = manager)",
                            value=message.DEFAULT_TEMPLATE, height=120)

    # --- preview one card --------------------------------------------------
    included = [r for r in recips if r.get("include") and r.get("chosen_name")]
    if included:
        st.markdown("### Preview")
        preview_name = st.selectbox("Preview card for",
                                    [r["chosen_name"] for r in included])
        if preview_name:
            out = Path(tempfile.gettempdir()) / f"swag_preview_{preview_name}.png"
            meta = compose.compose(preview_name, out)
            colp, colt = st.columns([2, 3])
            with colp:
                st.image(str(out))
                if not meta["used_real_photo"]:
                    st.caption("⚠️ Placeholder card — drop the real photo into "
                               "resources/swag/ to use the real one.")
            with colt:
                st.info(message.render(preview_name, template, manager=manager))

    # --- run ---------------------------------------------------------------
    st.markdown("---")
    ready = [r for r in recips if r.get("include") and r.get("phone_e164") and r.get("chosen_name")]
    st.markdown(f"**{len(ready)}** ready to text.")

    # The template signs off with {manager}; block sending until it's filled so
    # nobody texts "This is , one of the managers…".
    needs_manager = "{manager}" in template and not manager.strip()
    if needs_manager:
        st.warning("✍️ Enter the **manager name** above — it goes in every text.")

    cdry, csend = st.columns(2)
    roster = {"template": template, "manager": manager, "recipients": recips}
    with cdry:
        if st.button("🔍 Dry run (preview all, send nothing)", use_container_width=True):
            summary = run_mod.run(roster, send=False)
            st.success(f"Composited {summary['total']} card(s) → {summary['out_dir']}. "
                       "Nothing was texted.")
    with csend:
        if st.button("📲 Send texts now", type="primary", use_container_width=True,
                     disabled=needs_manager):
            summary = run_mod.run(roster, send=True)
            st.success(f"Sent {summary['sent']}/{summary['total']} "
                       f"(failed {summary['failed']}, skipped {summary['skipped']}).")
            if summary["failed"]:
                st.error("Some failed:\n" + "\n".join(
                    f"- {row['name']} ({row['phone']}): {row['error']}"
                    for row in summary["rows"] if row.get("error")))
