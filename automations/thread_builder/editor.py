"""The Thread Builder editor UI, backend-agnostic so the SAME drag surface serves
both homes:

  - standalone/dev app  -> LocalBackend  (writes the committed thread_plans.json)
  - enrollment admin     -> SheetBackend  (writes the 'Thread Plans' sheet; the
                            morning sync materializes it for the runners)

render_editor(backend) draws campaign + office pickers, the two-bucket drag list
(In the thread / Not included), a live order preview, and Save / Reset.
"""
from __future__ import annotations

import streamlit as st

from automations.thread_builder import catalog as C

# Drag-and-drop is the intended UX, but the enrollment app it lives in is deployed
# on Streamlit Cloud — if streamlit-sortables isn't installed there yet, fall back
# to a dependency-free up/down + checkbox editor so the form NEVER crashes.
try:
    from streamlit_sortables import sort_items
    _HAS_SORT = True
except Exception:  # noqa: BLE001
    _HAS_SORT = False


# --- storage backends -------------------------------------------------------
class LocalBackend:
    """Committed thread_plans.json (dev / standalone). Edits need a git deploy."""
    name = "local file"

    def current_ids(self, campaign, key):
        return C.current_ids(campaign, key)

    def has_plan(self, campaign, key):
        from automations.shared import thread_plans as tp
        return tp.plan_for(campaign, key) is not None

    def save(self, campaign, key, ids, by=""):
        from automations.shared import thread_plans as tp
        tp.save_plan(campaign, key, ids)

    def clear(self, campaign, key):
        from automations.shared import thread_plans as tp
        return tp.clear_plan(campaign, key)


class SheetBackend:
    """The shared 'Thread Plans' sheet (admin). Edits go live on the next morning
    sync — no git."""
    name = "shared sheet"

    def current_ids(self, campaign, key):
        from automations.thread_builder import store
        plan = store.plan_for(campaign, key)
        if plan:
            valid = {i for i, _ in C.catalog(campaign)}
            picked = [i for i in plan if i in valid]
            if picked:
                return picked
        return C.default_ids(campaign, key)

    def has_plan(self, campaign, key):
        from automations.thread_builder import store
        return store.plan_for(campaign, key) is not None

    def save(self, campaign, key, ids, by=""):
        from automations.thread_builder import store
        stamp = _now_iso()
        return store.save_plan(campaign, key, ids, updated_by=by, updated_at=stamp)

    def clear(self, campaign, key):
        from automations.thread_builder import store
        return store.clear_plan(campaign, key)


def _now_iso() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# --- the editor -------------------------------------------------------------
def render_editor(backend, *, by: str = "") -> None:
    """Admin editor: campaign + office pickers, then the section editor for the
    chosen office."""
    st.caption("Choose which sections post in an office's daily thread — and drag "
               "to set the order they post in.")

    campaign = st.radio("Campaign", options=list(C.CAMPAIGNS),
                        format_func=lambda k: C.CAMPAIGN_LABEL[k], horizontal=True)

    offs = C.offices(campaign)
    if not offs:
        st.warning("No offices found for this campaign.")
        return
    disp = dict(offs)
    office_key = st.selectbox("Office", options=[k for k, _ in offs],
                              format_func=lambda k: disp[k])
    _edit_office(backend, campaign, office_key, disp[office_key], by=by)


def render_owner_editor(backend, campaign: str, office_key: str,
                        office_label: str, *, by: str = "") -> None:
    """Owner-scoped editor: no campaign/office pickers — locked to ONE office (the
    owner resolved via their code). Same include/reorder surface + save behaviour."""
    _edit_office(backend, campaign, office_key, office_label, by=by)


def _edit_office(backend, campaign: str, office_key: str, disp_label: str,
                 *, by: str = "") -> None:
    has_plan = backend.has_plan(campaign, office_key)
    st.markdown("**Status:** " + ("✏️ custom plan saved" if has_plan
                                  else "🟢 using the default order"))

    lab = C.label_map(campaign)
    all_ids = [i for i, _ in C.catalog(campaign)]
    included = backend.current_ids(campaign, office_key)

    st.write("")
    if _HAS_SORT:
        new_included = _pick_drag(campaign, office_key, lab, included, all_ids)
    else:
        st.caption("Tip: install `streamlit-sortables` for drag-and-drop. Using "
                   "checkboxes + order numbers for now.")
        new_included = _pick_fallback(campaign, office_key, lab, included, all_ids)

    st.write("---")
    st.markdown("**Resulting thread order:**")
    if new_included:
        st.markdown("\n".join("{}. {}".format(n + 1, lab[i])
                              for n, i in enumerate(new_included)))
    else:
        st.info("Nothing selected — drag at least one section into the thread.")

    is_default = new_included == C.default_ids(campaign, office_key)

    st.write("")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("💾 Save", type="primary", use_container_width=True,
                     disabled=not new_included):
            if is_default:
                existed = backend.clear(campaign, office_key)
                st.success("Saved — matches the default, so no custom plan is "
                           "stored" + (" (previous one removed)." if existed
                                       else "."))
            else:
                backend.save(campaign, office_key, new_included, by=by)
                st.success("Saved a custom plan for {}.".format(disp_label))
            _go_live_note(backend)
            st.rerun()
    with c2:
        if st.button("↩️ Reset to default", use_container_width=True,
                     disabled=not has_plan):
            backend.clear(campaign, office_key)
            st.success("Reset {} to the default order.".format(disp_label))
            st.rerun()


def _pick_drag(campaign, office_key, lab, included, all_ids) -> list:
    """Two-bucket drag surface: drag between In/Not-included and within to order."""
    rev = {v: k for k, v in lab.items()}
    excluded = [i for i in all_ids if i not in included]
    buckets = [
        {"header": "✅ In the thread  (top = posts first)",
         "items": [lab[i] for i in included]},
        {"header": "🚫 Not included",
         "items": [lab[i] for i in excluded]},
    ]
    result = sort_items(buckets, multi_containers=True, direction="vertical",
                        key="sort_{}_{}".format(campaign, office_key))
    return [rev[l] for l in result[0]["items"] if l in rev]


def _pick_fallback(campaign, office_key, lab, included, all_ids) -> list:
    """Dependency-free editor (checkbox = include, number = order) for when the
    drag component isn't installed. Same result shape as _pick_drag."""
    order_of = {i: n for n, i in enumerate(included)}
    picked = []
    for i in all_ids:
        c1, c2 = st.columns([6, 1])
        on = c1.checkbox(lab[i], value=i in order_of,
                         key="inc_{}_{}_{}".format(campaign, office_key, i))
        pos = c2.number_input("order", 1, 99,
                              (order_of.get(i, len(included)) + 1),
                              key="ord_{}_{}_{}".format(campaign, office_key, i),
                              label_visibility="collapsed", disabled=not on)
        if on:
            picked.append((int(pos), i))
    return [i for _, i in sorted(picked)]


def _go_live_note(backend) -> None:
    if isinstance(backend, SheetBackend):
        st.info("✅ Saved to the shared sheet — it goes live on the next morning "
                "run (no deploy needed).")
    else:
        st.info("⤴️ To go live: commit + push, then update the reporting machine "
                "(`lucy update --machine \"Lucy 2\"`).")
