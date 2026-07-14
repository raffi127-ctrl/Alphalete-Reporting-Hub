"""The New-Hire Swag Texts UI, as a reusable function.

`render()` draws the whole upload → review/edit → preview → send flow. It's
called both by the standalone app (preflight_app.py) and by the Hub card
(dashboard.py's Office Operations profile), so there's one codebase. All
widget keys are prefixed `swag_` so it composes cleanly inside the Hub.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import streamlit as st

from automations.swag_welcome import compose, extract, imessage, message, run as run_mod
from automations.swag_welcome.roster import build_roster, pretty_phone, normalize_phone

# Reference screenshot of the finished Shortcut (Megan can drop one in here).
_SETUP_SHOT = compose.RESOURCE_DIR / "shortcut-setup.png"


def _pick_name(i: int) -> None:
    """Quick-pick radio → drop the choice into the editable name field."""
    st.session_state[f"swag_name_{i}"] = st.session_state[f"swag_pick_{i}"]


def _render_setup() -> None:
    """First-time, per-machine setup for auto-sending the CARD image."""
    ready = imessage.shortcut_installed()
    title = ("✅ Card sending is set up on this Mac"
             if ready else "🛠️ First-time setup — sending the card (do once per Mac)")
    with st.expander(title, expanded=not ready):
        if ready:
            st.success("This Mac has the **Alphalete Swag Card** Shortcut — cards "
                       "will send automatically. (The text needs no setup.)")
        else:
            st.warning("This Mac can send the **text** with no setup, but to also "
                       "auto-send the **card image** it needs a one-time Shortcut. "
                       "Without it, texts still send and cards are saved to the "
                       "output folder to attach by hand.")
        st.markdown(
            "**Why:** macOS won't let a script send an iMessage photo directly, so "
            "the card goes out through a tiny Shortcut. Build it once on each Mac "
            "that will send from its own number.\n\n"
            "**Steps (~2 min):**\n"
            "1. Make sure **Messages is signed into iMessage** on this Mac (the "
            "number these should come from).\n"
            "2. Open the **Shortcuts** app → **＋ New Shortcut** → name it exactly "
            "`Alphalete Swag Card`.\n"
            "3. Add these **3 actions, in order**:\n"
            "   - **Get Clipboard**\n"
            "   - **Get Phone Numbers from Input** — set its input to **Clipboard**\n"
            "   - **Send Message** — set **Message** = **Shortcut Input**, "
            "**Recipients** = **Phone Numbers**, and **uncheck “Show Compose "
            "Sheet.”**\n"
            "4. Close it (auto-saves). The **first** time a card sends, macOS asks "
            "**“Shortcuts can send messages” → click Allow**.\n\n"
            "That's it — after that, the Hub sends the card automatically from this "
            "Mac's iMessage."
        )
        # Reference screenshot of the finished shortcut.
        shot = st.file_uploader("📸 Reference screenshot of the finished Shortcut "
                                "(optional — for whoever sets up the next Mac)",
                                type=["png", "jpg", "jpeg"], key="swag_setup_shot")
        if shot is not None:
            _SETUP_SHOT.parent.mkdir(parents=True, exist_ok=True)
            _SETUP_SHOT.write_bytes(shot.getbuffer())
            st.success("Saved — it'll show here for everyone.")
        if _SETUP_SHOT.exists():
            st.image(str(_SETUP_SHOT), caption="What the finished Shortcut should "
                     "look like", use_container_width=True)


def render(show_header: bool = True) -> None:
    if show_header:
        st.title("🏢 New-Hire Swag Texts")
    st.caption("Upload the roster screenshot → check the names & numbers → send "
               "each new hire a welcome text with their name on the swag card. "
               "Texts send from THIS machine's iMessage account.")

    _render_setup()

    # (The always-on name-preview was removed — there's a per-person preview
    # below once a roster is uploaded, so it was redundant. Megan 2026-07-13.)

    # --- 1. Upload --------------------------------------------------------
    up = st.file_uploader("Roster screenshot (Name · Last Name · Phone)",
                          type=["png", "jpg", "jpeg"], key="swag_uploader")
    if up and st.session_state.get("swag_uploaded_name") != up.name:
        with st.spinner("Reading names & numbers off the image…"):
            tmp = Path(tempfile.gettempdir()) / f"swag_upload_{up.name}"
            tmp.write_bytes(up.getbuffer())
            try:
                rows = extract.extract_rows(tmp)
                st.session_state["swag_recips"] = [r.to_dict() for r in build_roster(rows)]
                st.session_state["swag_uploaded_name"] = up.name
            except Exception as e:
                st.error(f"Couldn't read the roster: {e}")

    recips = st.session_state.get("swag_recips", [])
    if not recips:
        return

    # --- flags ------------------------------------------------------------
    flagged = [r for r in recips if r.get("warnings")]
    if flagged:
        st.warning("⚠️ Check these before sending:\n"
                   + "\n".join(f"- **{r['raw_name'] or '(no name)'}** — "
                               f"{', '.join(r['warnings'])}" for r in flagged))

    st.markdown("### Review & edit")
    st.caption("Fix any misread name or number. For a name in quotes, pick which "
               "version goes on the card. Uncheck anyone you don't want texted.")

    for i, r in enumerate(recips):
        c1, c2, c3, c4, c5 = st.columns([0.5, 3, 2.4, 1.3, 1.3])
        with c1:
            r["include"] = st.checkbox("send", value=r.get("include", True),
                                       key=f"swag_inc_{i}", label_visibility="collapsed")
        with c2:
            if r.get("needs_quote_decision"):
                # Quick-pick between the real name and the quoted part; tapping
                # one drops it into the editable field below (still fully typeable).
                opts = [r["base_name"], r["quoted_alt"]]
                st.radio(
                    f"Quoted “{r['quoted_alt']}” — tap to use, or edit below",
                    opts, index=0, key=f"swag_pick_{i}", horizontal=True,
                    on_change=_pick_name, args=(i,),
                    help="Real name (pronunciation guide) vs. preferred nickname")
            r["chosen_name"] = st.text_input(
                "Name", value=r.get("chosen_name") or r.get("base_name", ""),
                key=f"swag_name_{i}",
                label_visibility=("collapsed" if r.get("needs_quote_decision")
                                  else "visible"))
        with c3:
            new_phone = st.text_input("Phone", value=pretty_phone(r["phone_e164"]),
                                      key=f"swag_phone_{i}")
            e164, _ = normalize_phone(new_phone)
            r["phone_e164"] = e164
            r["phone_pretty"] = pretty_phone(e164)
        with c4:
            r["start_time"] = st.text_input("Mon. time", value=r.get("start_time", ""),
                                            key=f"swag_time_{i}",
                                            placeholder="1:00")
        with c5:
            ok = r["include"] and r["phone_e164"] and r["chosen_name"]
            st.markdown(f"<div style='padding-top:1.9rem;opacity:0.7'>"
                        f"{'✅' if ok else '—'}</div>", unsafe_allow_html=True)

    st.markdown("---")

    # --- message ----------------------------------------------------------
    st.markdown("### Message")
    manager = st.text_input("Manager name (signs the text)", value="",
                            placeholder="e.g. Rafael", key="swag_manager")

    # Optional: name each person's Monday start time. Defaults on when the
    # roster came with times; toggling swaps the template preset (dynamic key).
    _has_times = any((r.get("start_time") or "").strip() for r in recips)
    include_time = st.checkbox(
        "⏰ Include each person's Monday start time in the text",
        value=_has_times, key="swag_include_time",
        help="Uses the Start Time column, e.g. “…orientation Monday at 1:00…”")
    _default_tmpl = (message.DEFAULT_TEMPLATE_WITH_TIME if include_time
                     else message.DEFAULT_TEMPLATE)
    _ph = "{name}, {manager}" + (", {time}" if include_time else "")
    template = st.text_area(f"Welcome text ({_ph})",
                            value=_default_tmpl, height=140,
                            key=f"swag_template_{include_time}")

    if include_time:
        _missing_t = [r["chosen_name"] for r in recips
                      if r.get("include") and not (r.get("start_time") or "").strip()]
        if _missing_t:
            st.warning("⏰ No Monday time for: " + ", ".join(_missing_t)
                       + " — add it in the table above or their text will read "
                       "“…Monday at  …”.")

    included = [r for r in recips if r.get("include") and r.get("chosen_name")]
    if included:
        st.markdown("### Preview")
        preview_name = st.selectbox("Preview card for",
                                    [r["chosen_name"] for r in included],
                                    key="swag_preview_pick")
        if preview_name:
            _prow = next((r for r in included if r["chosen_name"] == preview_name), {})
            out = Path(tempfile.gettempdir()) / f"swag_preview_{preview_name}.png"
            meta = compose.compose(preview_name, out)
            colp, colt = st.columns([3, 2])
            with colp:
                st.image(str(out))
                if not meta["used_real_photo"]:
                    st.caption("⚠️ Placeholder card — drop the real photo into "
                               "resources/swag/ to use the real one.")
            with colt:
                st.info(message.render(preview_name, template, manager=manager,
                                       time=_prow.get("start_time", "")))

    # --- run --------------------------------------------------------------
    st.markdown("---")
    ready = [r for r in recips if r.get("include") and r.get("phone_e164") and r.get("chosen_name")]
    st.markdown(f"**{len(ready)}** ready to text.")

    needs_manager = "{manager}" in template and not manager.strip()
    if needs_manager:
        st.warning("✍️ Enter the **manager name** above — it goes in every text.")

    roster = {"template": template, "manager": manager, "recipients": recips}
    cdry, csend = st.columns(2)
    with cdry:
        if st.button("🔍 Dry run (preview all, send nothing)",
                     use_container_width=True, key="swag_dry"):
            st.session_state["swag_summary"] = run_mod.run(roster, send=False)
    with csend:
        # Two-step confirm so a 30-person batch can't fire on a single stray click.
        confirm = st.checkbox(f"Yes, text all {len(ready)} now",
                              key="swag_confirm", disabled=needs_manager or not ready)
        if st.button("📲 Send texts now", type="primary", use_container_width=True,
                     disabled=needs_manager or not confirm or not ready, key="swag_send"):
            st.session_state["swag_summary"] = run_mod.run(roster, send=True)

    # Show the last dry-run / send result as a card grid, right here in the Hub
    # (no folder-digging) — each card + its message + per-person status.
    _render_summary(st.session_state.get("swag_summary"))


def _render_summary(summary: dict | None) -> None:
    if not summary:
        return
    from PIL import Image
    dry = summary.get("dry_run")
    st.markdown("---")
    if dry:
        st.success(f"👀 Dry run — {summary['total']} card(s) generated. "
                   "Nothing was texted. Check them below, then send.")
    else:
        st.success(f"📲 Sent {summary['sent']}/{summary['total']} "
                   f"(failed {summary['failed']}, skipped {summary['skipped']}).")

    rows = [r for r in summary.get("rows", []) if r.get("card")]
    per_row = 3
    for i in range(0, len(rows), per_row):
        cols = st.columns(per_row)
        for col, row in zip(cols, rows[i:i + per_row]):
            with col:
                try:
                    img = Image.open(row["card"])
                    img.thumbnail((520, 520))
                    st.image(img, use_container_width=True)
                except Exception:
                    st.caption("(card image unavailable)")
                if dry:
                    status = "— preview only"
                elif row.get("sent"):
                    status = "✅ sent"
                elif row.get("error"):
                    status = f"❌ {row['error']}"
                else:
                    status = "⏭️ skipped"
                st.markdown(f"**{row['name']}** · {row['phone']}  \n{status}")
                if row.get("text"):
                    with st.expander("message"):
                        st.write(row["text"])
