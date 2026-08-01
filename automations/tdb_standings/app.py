"""Texas de Brazil — 'Steak on the Line' LIVE standings page (Streamlit).

The team-facing view that gets linked with the daily PDF. Reads the auto-filled
per-day scoring-log Sheet (current month tab) and renders the steakhouse board —
ranked high->low, each rep's daily swings, losses in red, a "these eat steak"
line, and a find-your-name box. Updates on every page load (data comes straight
from the Sheet the 7:45am run fills), so there is nothing manual to refresh.

Run locally:   streamlit run automations/tdb_standings/app.py
Deploy:        Streamlit Community Cloud -> point at this file -> add the Google
               OAuth token to st.secrets (see automations/tdb_standings/README).
"""
import datetime
import html as _html

import streamlit as st

SHEET_ID = "1zlgrL36ly67xl_XU5okJ6yjHbpcx1F_eurtA09m-DaM"
DINNER_FALLBACK = "TBA"

st.set_page_config(page_title="Steak on the Line — Standings", page_icon="🥩", layout="wide")


def _client():
    """gspread client. On Lucy 1 the report's OAuth token is on disk; on Streamlit
    Cloud drop the same token JSON into st.secrets['gcp_oauth']."""
    try:
        from automations.recruiting_report import fill as _fill
        return _fill._client()
    except Exception:
        import gspread
        from google.oauth2.credentials import Credentials
        info = dict(st.secrets["gcp_oauth"])
        creds = Credentials.from_authorized_user_info(
            info, ["https://www.googleapis.com/auth/spreadsheets"])
        return gspread.authorize(creds)


@st.cache_data(ttl=120)
def load_month(title):
    sh = _client().open_by_key(SHEET_ID)
    return sh.worksheet(title).get_all_values()


def _num(x):
    try:
        return int(round(float(str(x).replace(",", "").strip())))
    except (TypeError, ValueError):
        return None


def parse_grid(values):
    """Locate header (#, REP NAME, MONTH TOTALS, day dates) and return reps sorted
    high->low with their per-day swings."""
    hrow = rank_c = name_c = total_c = None
    for i, row in enumerate(values[:5]):
        low = [str(c).strip().lower() for c in row]
        if "rep name" in low and "month totals" in low:
            hrow, name_c, total_c = i, low.index("rep name"), low.index("month totals")
            rank_c = low.index("#") if "#" in low else None
            break
    if hrow is None:
        return [], []
    hdr = values[hrow]
    day_cols = []
    c = total_c + 1
    while c < len(hdr) and str(hdr[c]).strip():
        day_cols.append((c, str(hdr[c]).strip()))
        c += 1
    reps = []
    for row in values[hrow + 1:]:
        name = row[name_c].strip() if name_c < len(row) else ""
        if not name:
            continue
        total = _num(row[total_c]) if total_c < len(row) else None
        if total is None:
            total = 0
        days = []
        for ci, label in day_cols:
            v = _num(row[ci]) if ci < len(row) else None
            days.append((label, v))
        reps.append({"name": name, "total": total, "days": days})
    reps.sort(key=lambda r: (-r["total"], r["name"]))
    for i, r in enumerate(reps, 1):
        r["rank"] = i
    return reps, [d[1] for d in day_cols]


CSS = """
<style>
.block-container{max-width:1120px;padding-top:1.2rem}
.stApp{background:radial-gradient(120% 60% at 50% -8%,rgba(179,18,26,.26),transparent 46%),linear-gradient(180deg,#160b08,#0c0404 40%,#0a0705)}
.hero{text-align:center;margin-bottom:6px}
.kick{font-size:12px;letter-spacing:6px;color:#caa14a;text-transform:uppercase;font-weight:700}
.brand{font-family:Georgia,serif;font-style:italic;font-weight:700;font-size:56px;color:#f6efe1;line-height:1}
.brand em{color:#e7c878}
.month{letter-spacing:8px;color:#e7c878;text-transform:uppercase;font-weight:700;font-size:13px;margin-top:4px}
.prize{display:inline-block;margin-top:12px;padding:8px 16px;border:1px solid #3a281c;border-radius:999px;color:#f6efe1;font-size:13px}
.prize b{color:#e7c878}
.row{display:grid;grid-template-columns:52px 1fr auto;gap:14px;align-items:center;background:linear-gradient(180deg,#17100c,#1f1611);border:1px solid #3a281c;border-radius:13px;padding:12px 18px;margin-bottom:7px}
.row.r1{border-color:rgba(231,200,120,.55);background:linear-gradient(180deg,rgba(231,200,120,.14),#1f1611)}
.row.r2{border-color:rgba(231,200,120,.32)}.row.r3{border-color:rgba(231,200,120,.22)}
.rank{font-family:Georgia,serif;font-size:24px;font-weight:700;text-align:center;color:#b7a68f}
.row.top .rank{color:#e7c878}
.nm{font-size:17px;font-weight:650;color:#fff}
.chips{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px}
.chip{font-size:11px;padding:2px 7px;border-radius:6px;background:rgba(231,200,120,.10);color:#e7c878;border:1px solid rgba(231,200,120,.18)}
.chip.neg{background:rgba(224,59,42,.12);color:#e03b2a;border-color:rgba(224,59,42,.25)}
.tot{font-family:Georgia,serif;font-size:28px;font-weight:700;color:#fff;text-align:right;min-width:70px}
.tot span{display:block;font-size:9px;letter-spacing:2px;color:#b7a68f;text-transform:uppercase}
.cut{display:flex;align-items:center;gap:14px;margin:14px 2px 8px;color:#e7c878;font-size:12px;letter-spacing:3px;text-transform:uppercase;font-weight:700}
.cut::before,.cut::after{content:"";flex:1;height:1px;background:linear-gradient(90deg,transparent,#caa14a,transparent)}
.foot{text-align:center;color:#b7a68f;font-size:11.5px;margin-top:22px}
</style>
"""


def rep_row(r, show_days):
    cls = "row top r%d" % r["rank"] if r["rank"] <= 3 else ("row top" if r["rank"] <= 10 else "row")
    medal = {1: "1<small>ST</small>", 2: "2<small>ND</small>", 3: "3<small>RD</small>"}.get(r["rank"], r["rank"])
    chips = ""
    if show_days:
        for label, v in r["days"]:
            if v:
                neg = v < 0
                chips += '<span class="chip %s">%s %s%d</span>' % ("neg" if neg else "", _html.escape(label), "+" if v > 0 else "", v)
    return ('<div class="%s"><div class="rank">%s</div>'
            '<div><div class="nm">%s</div><div class="chips">%s</div></div>'
            '<div class="tot">%d<span>pts</span></div></div>') % (
        cls, medal, _html.escape(r["name"]), chips, r["total"])


def main():
    now = datetime.datetime.now()
    title = now.strftime("%B %Y")
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown(
        '<div class="hero"><div class="kick">Texas de Brazil Competition</div>'
        '<div class="brand">Steak on the <em>Line</em></div>'
        '<div class="month">%s · Standings</div>'
        '<div class="prize">🥩 Top 10 earn their seat at the table</div></div>' % title.upper(),
        unsafe_allow_html=True)
    try:
        values = load_month(title)
    except Exception as e:
        st.warning("Standings for %s aren't posted yet. (%s)" % (title, type(e).__name__))
        return
    reps, _ = parse_grid(values)
    if not reps:
        st.info("The %s board hasn't started yet — check back once the competition is underway." % title)
        return

    c1, c2 = st.columns([3, 2])
    q = c1.text_input("Find your name", "", placeholder="Type a rep's name…").strip().lower()
    show_days = c2.toggle("Show daily breakdown", value=True)

    shown = [r for r in reps if not q or q in r["name"].lower()]
    html_out = ""
    for r in shown:
        if not q and r["rank"] == 11:
            html_out += '<div class="cut"><span>🍽️ These eat steak · everyone below is chasing a seat</span></div>'
        html_out += rep_row(r, show_days)
    st.markdown(html_out, unsafe_allow_html=True)
    st.markdown('<div class="foot">%d reps competing · updates automatically · ranked highest to lowest</div>' % len(reps),
                unsafe_allow_html=True)


if __name__ == "__main__" or True:
    main()
