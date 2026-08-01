"""Texas de Brazil — 'Steak on the Line' LIVE standings page (Streamlit).

Team-facing view linked with the daily PDF. Reads the auto-filled per-day
scoring-log Sheet (itemized cells: line 1 = day total, lines below = each point
source like 'Internet 5×+2') and renders the steakhouse board ranked high->low.
Tap a rep to EXPAND their day-by-day breakdown inline (running total + monthly
bonus) — inline (not a pop-up) so it scrolls natively on phones. Updates every
load; nothing manual. Month dropdown = July 2026 -> current month.

Deploy: Streamlit Community Cloud -> this file. No secrets while the Sheet is
link-viewable (public CSV read).
"""
import csv
import datetime
import io
import json
import re
import urllib.parse
import urllib.request

import streamlit as st
import streamlit.components.v1 as components

SHEET_ID = "1zlgrL36ly67xl_XU5okJ6yjHbpcx1F_eurtA09m-DaM"
START = (2026, 7)

st.set_page_config(page_title="Steak on the Line — Standings", page_icon="🥩", layout="centered")


@st.cache_data(ttl=120)
def load_month(title):
    try:
        url = ("https://docs.google.com/spreadsheets/d/%s/gviz/tq?tqx=out:csv&sheet=%s"
               % (SHEET_ID, urllib.parse.quote(title)))
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        raw = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "replace")
        rows = list(csv.reader(io.StringIO(raw)))
        if any("rep name" in " ".join(r).lower() for r in rows[:5]):
            return rows
    except Exception:
        pass
    from automations.recruiting_report import fill as _fill
    return _fill._client().open_by_key(SHEET_ID).worksheet(title).get_all_values()


_IT_CU = re.compile(r"^(.*?)\s+(\d+)\s*[×x]\s*([+-]\d+)$")
_IT_P = re.compile(r"^(.*?)\s+([+-]\d+)$")


def _parse_item(line):
    line = line.strip()
    m = _IT_CU.match(line)
    if m:
        c, u = int(m.group(2)), int(m.group(3))
        return [m.group(1).strip(), c * u, c, u]
    m = _IT_P.match(line)
    if m:
        return [m.group(1).strip(), int(m.group(2)), None, None]
    return None


def _parse_cell(cell):
    lines = [l for l in str(cell).split("\n") if l.strip()]
    if not lines:
        return 0, []
    try:
        tot = int(lines[0].replace("+", "").strip())
    except ValueError:
        tot = 0
    items = [x for x in (_parse_item(l) for l in lines[1:]) if x]
    return tot, items


def parse_board(values):
    hrow = name_c = total_c = None
    for i, row in enumerate(values[:5]):
        low = [str(c).strip().lower() for c in row]
        if "rep name" in low:
            hrow, name_c = i, low.index("rep name")
            total_c = low.index("month totals") if "month totals" in low else name_c + 1
            break
    if hrow is None:
        return []
    hdr = values[hrow]
    day_cols = [(j, hdr[j].strip()) for j in range(total_c + 1, len(hdr)) if "/" in str(hdr[j])]
    bonus_c = next((j for j, c in enumerate(hdr) if "bonus" in str(c).lower()), None)
    reps = []
    for row in values[hrow + 1:]:
        name = row[name_c].strip() if name_c < len(row) else ""
        if not name:
            continue
        try:
            total = int(str(row[total_c]).replace("+", "").strip()) if total_c < len(row) else 0
        except ValueError:
            total = 0
        days = []
        for j, label in day_cols:
            if j < len(row) and str(row[j]).strip():
                tot, items = _parse_cell(row[j])
                days.append({"d": label, "items": items, "tot": tot})
        month = []
        if bonus_c is not None and bonus_c < len(row) and str(row[bonus_c]).strip():
            _, month = _parse_cell(row[bonus_c])
        reps.append({"name": name, "total": total, "days": days, "month": month})
    reps.sort(key=lambda r: (-r["total"], r["name"]))
    for i, r in enumerate(reps, 1):
        r["rank"] = i
    return reps


def _month_titles():
    now = datetime.datetime.now()
    out, y, mo = [], now.year, now.month
    while (y, mo) >= START:
        out.append(datetime.date(y, mo, 1).strftime("%B %Y"))
        mo -= 1
        if mo == 0:
            mo, y = 12, y - 1
    return out


@st.cache_data(ttl=120)
def month_reps(title):
    try:
        return parse_board(load_month(title))
    except Exception:
        return []


# Hero + control styling (rendered as native Streamlit markdown so the month
# picker below it inherits the dark theme instead of a stray white bar).
HERO = """
<style>
#MainMenu,header,footer{visibility:hidden}
.block-container{padding:1.1rem 1rem 0;max-width:1080px}
.stApp{background:radial-gradient(120% 55% at 50% -6%,rgba(179,18,26,.28),transparent 46%),linear-gradient(180deg,#160b08,#0e0a08 42%,#0a0705)}
.tdb-hero{text-align:center;margin-bottom:6px}
.tdb-hero .kick{font-size:12px;letter-spacing:6px;color:#caa14a;text-transform:uppercase;font-weight:700}
.tdb-hero .brand{font-family:Georgia,serif;font-style:italic;font-weight:700;font-size:clamp(36px,8vw,60px);color:#f6efe1;line-height:1;margin:2px 0}
.tdb-hero .brand em{color:#e7c878}
.tdb-hero .prize{display:inline-block;margin-top:10px;padding:8px 16px;border:1px solid #3a281c;border-radius:999px;font-size:13px;color:#f6efe1}
.tdb-hero .prize b{color:#e7c878}
div[data-testid="stSelectbox"] label{color:#caa14a;font-size:11px;letter-spacing:2px;text-transform:uppercase;font-weight:700}
div[data-testid="stSelectbox"]{max-width:280px;margin:2px auto 6px}
</style>
<div class="tdb-hero">
  <div class="kick">Texas de Brazil Competition</div>
  <div class="brand">Steak on the <em>Line</em></div>
  <div class="prize">🥩 Top 10 earn their seat at the table</div>
</div>
"""

BOARD = r"""
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;color:#f6efe1;background:transparent;-webkit-font-smoothing:antialiased}
.month{text-align:center;letter-spacing:7px;color:#e7c878;text-transform:uppercase;font-weight:700;font-size:12px;margin:2px 0 12px}
.find{position:relative;max-width:340px;margin:0 auto 4px}
.find input{width:100%;background:#17100c;border:1px solid #3a281c;color:#f6efe1;padding:10px 14px;border-radius:10px;font-size:14px;outline:none}
.find input:focus{border-color:#caa14a;box-shadow:0 0 0 3px rgba(231,200,120,.12)}
.hint{text-align:center;color:#b7a68f;font-size:11px;margin:6px 0 14px}.hint b{color:#caa14a}
.row{display:grid;grid-template-columns:48px 1fr auto;gap:12px;align-items:center;background:linear-gradient(180deg,#17100c,#1f1611);border:1px solid #3a281c;border-radius:13px;padding:12px 16px;margin-bottom:7px;cursor:pointer;transition:border-color .15s,transform .15s}
.row:active,.row:hover{border-color:#caa14a;transform:translateX(2px)}
.row.r1{border-color:rgba(231,200,120,.55);background:linear-gradient(180deg,rgba(231,200,120,.14),#1f1611)}
.row.r2{border-color:rgba(231,200,120,.32)}.row.r3{border-color:rgba(231,200,120,.22)}
.rank{font-family:Georgia,serif;font-size:24px;font-weight:700;text-align:center;color:#b7a68f}
.row.top .rank{color:#e7c878}.rank small{display:block;font-size:9px;letter-spacing:1px;color:#caa14a}
.nm{font-size:16px;font-weight:650;color:#fff}
.chips{display:flex;flex-wrap:wrap;gap:5px;margin-top:7px}
.chip{font-size:11px;padding:2.5px 8px;border-radius:6px;background:rgba(231,200,120,.10);color:#e7c878;border:1px solid rgba(231,200,120,.18);white-space:nowrap}
.chip.neg{background:rgba(224,59,42,.10);color:#e03b2a;border-color:rgba(224,59,42,.22)}
.chip b{font-weight:700;margin-left:3px}.chip .x{font-weight:700;margin-left:4px}
.tap{font-size:10px;color:#caa14a;opacity:.7;margin-top:3px;letter-spacing:.5px}
.tot{text-align:right;font-family:Georgia,serif;font-size:27px;font-weight:700;color:#fff;min-width:66px}
.tot span{display:block;font-size:9px;letter-spacing:2px;color:#b7a68f;text-transform:uppercase;font-weight:700}
.cut{display:flex;align-items:center;gap:12px;margin:14px 2px 8px;color:#e7c878;font-size:12px;letter-spacing:3px;text-transform:uppercase;font-weight:700}
.cut::before,.cut::after{content:"";flex:1;height:1px;background:linear-gradient(90deg,transparent,#caa14a,transparent)}
.hidden{display:none!important}
.foot{text-align:center;color:#b7a68f;font-size:11.5px;margin:20px 0}
/* inline detail */
.back{display:inline-flex;align-items:center;gap:7px;color:#e7c878;background:#17100c;border:1px solid #3a281c;border-radius:10px;padding:9px 16px;font-size:14px;font-weight:600;cursor:pointer;margin-bottom:14px}
.dhead{display:grid;grid-template-columns:auto 1fr auto;gap:12px;align-items:center;padding-bottom:12px;border-bottom:1px solid #3a281c;margin-bottom:6px}
.dhead .mr{font-family:Georgia,serif;font-size:26px;color:#e7c878;font-weight:700}
.dhead .mn{font-size:20px;font-weight:700;color:#fff}.dhead .ms{font-size:11.5px;color:#b7a68f}
.dhead .mt{text-align:right;font-family:Georgia,serif;font-size:30px;color:#fff;font-weight:700}.dhead .mt span{display:block;font-size:9px;letter-spacing:2px;color:#b7a68f;text-transform:uppercase}
.sect{font-size:10.5px;letter-spacing:2px;text-transform:uppercase;color:#caa14a;font-weight:700;margin:16px 0 6px}
.day{display:grid;grid-template-columns:76px 1fr auto;gap:10px;align-items:center;padding:9px 0;border-bottom:1px solid #2a1c12}
.dlab{font-size:12px;color:#f6efe1;font-weight:600}.dlab span{display:block;font-size:10px;color:#b7a68f}
.dchips{display:flex;flex-wrap:wrap;gap:4px}
.dsw{font-family:Georgia,serif;font-size:17px;font-weight:700;text-align:right;min-width:44px}
.pos{color:#e7c878}.negc{color:#e03b2a}
.run{font-size:10px;color:#b7a68f;text-align:right}
.grand{display:flex;justify-content:space-between;align-items:center;margin-top:16px;padding-top:14px;border-top:2px solid #caa14a;font-family:Georgia,serif;font-size:19px;color:#fff;font-weight:700}
.grand span:last-child{font-size:24px;color:#e7c878}
</style>
<div class="month">__MONTH__ · Standings</div>
<div id="controls">
  <div class="find"><input id="q" type="text" placeholder="Find your name…" autocomplete="off"></div>
  <div class="hint">👆 <b>Tap any rep</b> for their day-by-day breakdown</div>
</div>
<div id="board"></div>
<div class="foot" id="foot"></div>
<script>
const DATA=__DATA__;
const DOW=["Sun","Mon","Tue","Wed","Thu","Fri","Sat"],MO=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const ctr=document.getElementById('controls'),board=document.getElementById('board'),foot=document.getElementById('foot');
function dfmt(s){var p=String(s).split("/");if(p.length<3)return{d:s,w:""};var mo=+p[0],da=+p[1],yr=2000+(+p[2]);var dt=new Date(yr,mo-1,da);return{d:MO[mo-1]+" "+da,w:DOW[dt.getDay()]};}
function medal(r){return r===1?'1<small>ST</small>':r===2?'2<small>ND</small>':r===3?'3<small>RD</small>':r;}
function chip(it){var l=it[0],v=it[1],c=it[2],u=it[3];var neg=v<0;
  var inner=(c!=null&&u!=null)?('<span class="x">'+c+' × '+(u>0?'+':'')+u+'</span>'):('<b>'+(v>0?'+':'')+Math.round(v)+'</b>');
  return '<span class="chip '+(neg?'neg':'')+'">'+l+' '+inner+'</span>';}
function topChips(rec){var agg={},order=[];
  function add(l,v){if(!(l in agg)){agg[l]=0;order.push(l);}agg[l]+=v;}
  rec.days.forEach(function(dd){dd.items.forEach(function(it){add(it[0],it[1]);});});
  rec.month.forEach(function(it){add(it[0],it[1]);});
  return order.map(function(l){var v=agg[l];return '<span class="chip '+(v<0?'neg':'')+'">'+l+'<b>'+(v>0?'+':'')+Math.round(v)+'</b></span>';}).join('');}
function rowHTML(rec){var cls=rec.rank<=3?('row top r'+rec.rank):(rec.rank<=10?'row top':'row');
  return '<div class="'+cls+'" data-name="'+rec.name.toLowerCase()+'" data-rank="'+rec.rank+'">'
    +'<div class="rank">'+medal(rec.rank)+'</div>'
    +'<div><div class="nm">'+rec.name+'</div><div class="chips">'+topChips(rec)+'</div><div class="tap">Tap for daily breakdown ›</div></div>'
    +'<div class="tot">'+rec.total+'<span>pts</span></div></div>';}
function showList(){ctr.style.display='';foot.style.display='';
  var h='';DATA.forEach(function(rec){if(rec.rank===11&&!document.getElementById('q').value)h+='<div class="cut"><span>🍽️ These eat steak · everyone below is chasing a seat</span></div>';h+=rowHTML(rec);});board.innerHTML=h;
  document.getElementById('q').addEventListener('input',function(){var t=this.value.trim().toLowerCase();
    document.querySelectorAll('.row').forEach(function(el){el.classList.toggle('hidden',!(!t||el.dataset.name.indexOf(t)>-1));});
    document.querySelectorAll('.cut').forEach(function(el){el.classList.toggle('hidden',!!t);});});
  foot.innerHTML=DATA.length+' reps competing · updates automatically · ranked highest to lowest';}
function showRep(rec){ctr.style.display='none';foot.style.display='none';var run=0;
  var days=rec.days.map(function(dd){run+=dd.tot;var f=dfmt(dd.d);
    return '<div class="day"><div class="dlab">'+f.d+'<span>'+f.w+'</span></div>'
      +'<div class="dchips">'+dd.items.map(chip).join('')+'</div>'
      +'<div><div class="dsw '+(dd.tot<0?'negc':'pos')+'">'+(dd.tot>0?'+':'')+Math.round(dd.tot)+'</div><div class="run">'+Math.round(run)+' total</div></div></div>';}).join('');
  var month=rec.month.length?('<div class="sect">Monthly bonus · no single day</div>'+rec.month.map(function(it){
    return '<div class="day"><div class="dlab">'+it[0]+'</div><div class="dchips">'+chip(it)+'</div><div class="dsw '+(it[1]<0?'negc':'pos')+'">'+(it[1]>0?'+':'')+Math.round(it[1])+'</div></div>';}).join('')):'';
  board.innerHTML='<div class="back" onclick="showList()">‹ Back to standings</div>'
    +'<div class="dhead"><div class="mr">'+(rec.rank<=3?['','🥇','🥈','🥉'][rec.rank]:'#'+rec.rank)+'</div>'
    +'<div><div class="mn">'+rec.name+'</div><div class="ms">Rank '+rec.rank+' of '+DATA.length+' · every point, day by day</div></div>'
    +'<div class="mt">'+rec.total+'<span>points</span></div></div>'
    +'<div class="sect">Daily · sales floor</div>'+(days||'<div class="run" style="text-align:left">No daily activity yet.</div>')
    +month+'<div class="grand"><span>Month total</span><span>'+rec.total+'</span></div>';
  window.scrollTo(0,0);}
window.showList=showList;
board.addEventListener('click',function(e){var r=e.target.closest('.row');if(r)showRep(DATA[+r.dataset.rank-1]);});
showList();
</script>
"""


def main():
    st.markdown(HERO, unsafe_allow_html=True)
    titles = _month_titles()
    live = [t for t in titles if any(r["total"] for r in month_reps(t))]
    default = titles[0] if any(r["total"] for r in month_reps(titles[0])) else (live[0] if live else titles[0])
    title = st.selectbox("Month", titles, index=titles.index(default))

    reps = month_reps(title)
    if not reps:
        st.info("The %s board hasn't started yet — check back once the competition is underway." % title)
        return
    html = BOARD.replace("__DATA__", json.dumps(reps)).replace("__MONTH__", title.upper())
    components.html(html, height=min(len(reps), 66) * 88 + 260, scrolling=True)


main()
