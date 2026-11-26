"use strict";
// ---------- constants ----------
const OPT = {
  f:["Qualify","Disqualify","Disqualify - Declined"],
  g:["Age","Looks","Communication Skills","Commute","Pay","Schedule","Hopped Off"],
  h:["Answered","No Answer","Not Contacted"],
  i:["Booked","Not Booked"],
  k:["Showed","No Show","Reschedule Requested","Cancelled"],
  l:["YES","NO"],
  m:["BOB","Declined","No Answer"],
  p:["1 Star","2 Star","3 Star","4 Star","5 Star"]
};
const FIELDS = ["b","d","e","f","g","h","i","j","k","l","m","n","p"];
const DAYN = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"];
const TABS = [
  {id:"entrada", label:"Data Entry", c:"#2f4bc4"},
  {id:"qualified", label:"Qualified Retention", c:"#9900FF"},
  {id:"answered", label:"Answered / Booked", c:"#FF9900"},
  {id:"showed", label:"2nd Rd Showed", c:"#3D85C6"},
  {id:"offered", label:"Offered / BOB", c:"#A64D79"},
  {id:"conversion", label:"Conversion Numbers", c:"#BF9000"},
  {id:"retention", label:"Interviewers Retention", c:"#3D85C6"},
  {id:"ads", label:"Ad Titles", c:"#6b6b6b"},
  {id:"stars", label:"Ads \u00d7 Stars", c:"#6b6b6b"},
  {id:"users", label:"Users", c:"#2f4bc4", admin:true}
];
const STATES="AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC";
const CITY_RE = new RegExp("^[\\s\\S]*(?:\\?|,|\u00b7|\\)|:|\\s[-\u2013]\\s)\\s*([A-Za-z][A-Za-z .'\\-]*?)\\s*,?\\s+("+STATES+")\\b[\\s\\S]*$");

// ---------- state ----------
const S = {db:null, canWrite:true, offices:[], office:null, rows:[], weekDocs:new Set(), loaded:false,
  tab:"entrada", week:null, goal:0.5, adMap:{}, unsub:null,
  ints:[], ent:{month:"", who:"", q:"", d2:"", city:"", page:0}, ads:{month:"", q:"", view:(function(){try{return localStorage.getItem("ars.adview")||"overall"}catch(e){return "overall"}})(), wsort:"T"}, st:{month:"", min:10, sort:"avg", view:(function(){try{return localStorage.getItem("ars.stview")||"overall"}catch(e){return "overall"}})(), wmin:3, wsort:"avg"}};
try{ S.hideDays=!!localStorage.getItem("ars.hideDays"); }catch(e){}
S.ret={data:null, loading:false, err:"", view:(function(){try{return localStorage.getItem("ars.retview")||"service"}catch(e){return "service"}})()};
try{ const t=localStorage.getItem("ars.tab"); if(t && TABS.some(x=>x.id===t)) S.tab=t; const g=localStorage.getItem("ars.goal"); if(g) S.goal=+g; }catch(e){}
if(location.hash && TABS.some(x=>"#"+x.id===location.hash)) S.tab=location.hash.slice(1);

// ---------- helpers ----------
const $=s=>document.querySelector(s);
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const low=s=>String(s||"").trim().toLowerCase();
const slug=s=>low(s).normalize("NFD").replace(/[\u0300-\u036f]/g,"").replace(/[^a-z0-9]+/g,"-").replace(/^-|-$/g,"")||"oficina";
const toD=s=>{const [y,m,d]=s.split("-").map(Number);return new Date(Date.UTC(y,m-1,d));};
const iso=d=>d.toISOString().slice(0,10);
const addD=(s,n)=>{const d=toD(s);d.setUTCDate(d.getUTCDate()+n);return iso(d);};
const monday=s=>{const d=toD(s);const w=(d.getUTCDay()+6)%7;d.setUTCDate(d.getUTCDate()-w);return iso(d);};
const md=s=>{const d=toD(s);return (d.getUTCMonth()+1)+"/"+d.getUTCDate();};
const MONTHS=["January","February","March","April","May","June","July","August","September","October","November","December"];
const monthLabel=s=>{if(!s)return "";const d=toD(s);return MONTHS[d.getUTCMonth()]+" "+d.getUTCFullYear();};
const monthKey=s=>s?s.slice(0,7):"";
const today=()=>{const d=new Date();return d.getFullYear()+"-"+String(d.getMonth()+1).padStart(2,"0")+"-"+String(d.getDate()).padStart(2,"0");};
const pct=(n,d)=>d?n/d:null;
const fp=v=>v==null?"0%":Math.round(v*100)+"%";
function city(n){ if(!n) return ""; const t=n.replace(/\u00a0/g," "); const m=t.match(CITY_RE); return m? m[1]+", "+m[2] : ""; }
// Ad titles are free text (pasted from the job board). Variants of the same ad are merged:
// the Excel Ad Groups table first, then a loose key that ignores punctuation, "?"/"\u00b7"/commas,
// "New application for"/"Indeed /" prefixes and a repeated "City, ST" at the end.
function adBase(n){
  let t=String(n||"").replace(/\u00a0/g," ").trim(); if(!t) return "";
  const k0=t.toLowerCase().replace(/[^a-z0-9]/g,""); if(S.adMap[k0]) t=S.adMap[k0];
  return t.replace(/^\s*(new application for|indeed\s*\/)\s*/i,"").trim();
}
function adKey(n){
  const t=adBase(n); if(!t) return "";
  let w=t.toLowerCase().replace(/&/g," and ").replace(/[^a-z0-9]+/g," ").trim().split(" ").filter(Boolean);
  for(let L=4;L>=2;L--){ if(w.length>=2*L && w.slice(-L).join(" ")===w.slice(-2*L,-L).join(" ")){ w=w.slice(0,-L); break; } }
  return w.join("");
}
function buildAdLabels(){
  const c={};
  for(const r of S.rows){ const k=adKey(r.n); if(!k) continue; const lab=adBase(r.n).replace(/[\s,]+$/,""); (c[k]??={}); c[k][lab]=(c[k][lab]||0)+1; }
  S.adLabel={}; for(const k in c){ S.adLabel[k]=Object.entries(c[k]).sort((a,b)=>b[1]-a[1]||a[0].length-b[0].length)[0][0]; }
}
function adGroup(n){ const k=adKey(n); if(!k) return ""; return (S.adLabel&&S.adLabel[k])||adBase(n); }
function rid(){ return Date.now().toString(36)+Math.random().toString(36).slice(2,7); }
function status(t,err){ const s=$("#status"); s.textContent=t; s.className=err?"err":""; }
const sleep=ms=>new Promise(r=>setTimeout(r,ms));

// ---------- data index ----------
let IDX=null;
function buildIndex(){
  const byB={}, byJ={}, people=new Set(), weeks=new Set();
  for(const r of S.rows){
    if(r.b){ (byB[r.d]??={}); (byB[r.d][r.b]??=[]).push(r); weeks.add(monday(r.b)); }
    if(r.j){ (byJ[r.d]??={}); (byJ[r.d][r.j]??=[]).push(r); weeks.add(monday(r.j)); }
    if(r.d) people.add(r.d);
  }
  IDX={byB,byJ,people:[...people],weeks:[...weeks].sort().reverse()};
  buildAdLabels();
}
const RB=(p,day)=>(IDX.byB[p]&&IDX.byB[p][day])||[];
const RJ=(p,day)=>(IDX.byJ[p]&&IDX.byJ[p][day])||[];
const cnt=(arr,f,v)=>{let n=0;for(const r of arr) if(low(r[f])===v) n++;return n;};

// ---------- weekly report specs ----------
// Each spec: date field for "who appears", day list, count fns per day, pct defs, total columns.
const SPECS = {
  qualified:{ rule:{ok:60}, title:"Qualified Retention", c:"pal-q", who:"b", days:5,
    note:"By 1st round date. QR = Qualified \u00f7 (Q + Di + De).",
    day:(p,d)=>{const a=RB(p,d);return {Q:cnt(a,"f","qualify"),Di:cnt(a,"f","disqualify"),De:cnt(a,"f","disqualify - declined")};},
    cols:[["Q","Q"],["Di","Di"],["De","De"],["QR","QR",["Q"],["Q","Di","De"],{ok:60}],["DiR","DiR",["Di"],["Q","Di","De"]],["DR","DR",["De"],["Q","Di","De"]]],
    totDays:6,
    tcols:[["Q","Qualified"],["Di","Disqualified"],["De","Declined"],["QR","Qualified Retention",["Q"],["Q","Di","De"],{ok:60}],["DiR","Disqualified Retention",["Di"],["Q","Di","De"]],["DR","Declined Retention",["De"],["Q","Di","De"]]]},
  answered:{ rule:{ok:85,mid:80}, title:"Answered / Booked Retention", c:"pal-a", who:"b", days:5,
    note:"By 1st round date. AR, BR and NCR are divided by Qualified.",
    day:(p,d)=>{const a=RB(p,d);return {Q:cnt(a,"f","qualify"),A:cnt(a,"h","answered"),B:cnt(a,"i","booked"),NC:cnt(a,"h","not contacted")};},
    cols:[["Q","Q"],["A","A"],["B","B"],["NC","NC"],["AR","AR",["A"],["Q"],{ok:85,mid:80}],["BR","BR",["B"],["Q"],{ok:85,mid:80}],["NCR","NCR",["NC"],["Q"]]],
    totDays:6,
    tcols:[["Q","Qualified"],["A","Answered"],["B","Booked"],["NC","Not Contacted"],["AR","Answered Retention",["A"],["Q"],{ok:85,mid:80}],["BR","Booked Retention",["B"],["Q"],{ok:85,mid:80}],["NCR","Not Contacted Retention",["NC"],["Q"]]]},
  showed:{ title:"2nd Round Showed Retention", c:"pal-s", who:"j", days:6,
    note:"By 2nd round date. R = Showed \u00f7 Booked.",
    day:(p,d)=>{const a=RJ(p,d);return {B:cnt(a,"i","booked"),S:cnt(a,"k","showed"),NS:cnt(a,"k","no show"),RR:cnt(a,"k","reschedule requested"),C:cnt(a,"k","cancelled")};},
    cols:[["B","B"],["S","S"],["NS","NS"],["RR","RR"],["C","C"],["R","R",["S"],["B"],1]],
    totDays:6,
    tcols:[["B","2nd Rd Booked"],["S","2nd Rd Showed"],["R","2nd Showed Retention",["S"],["B"],1]]},
  offered:{ title:"Offered Position | BOB Retention", c:"pal-o", who:"j", days:5,
    note:"By 2nd round date. OPR = Offered \u00f7 Showed. BOBR = BOB \u00f7 Offered.",
    day:(p,d)=>{const a=RJ(p,d);return {S:cnt(a,"k","showed"),YES:cnt(a,"l","yes"),NO:cnt(a,"l","no"),NA:cnt(a,"m","no answer"),D:cnt(a,"m","declined"),BOB:cnt(a,"m","bob")};},
    cols:[["S","S"],["YES","YES"],["NO","NO"],["NA","NA"],["D","D"],["BOB","BOB"],["OPR","OPR",["YES"],["S"],1],["BOBR","BOBR",["BOB"],["YES"],1]],
    totDays:5,
    tcols:[["S","2nd R Showed"],["YES","Offered Position"],["BOB","BOB"],["OPR","Offered Position Retention",["YES"],["S"],1],["BOBR","BOB Retention",["BOB"],["YES"],1]]},
  conversion:{ title:"Conversion Numbers", c:"pal-c", who:"bj", days:5,
    note:"1st round columns use the 1st round date; 2nd round columns use the 2nd round date. Showed up = Qualified + Disqualified.",
    day:(p,d)=>{const a=RB(p,d),b=RJ(p,d);const Di=cnt(a,"f","disqualify"),Q=cnt(a,"f","qualify");return {SU:Di+Q,Di,Q,BK:cnt(a,"i","booked"),B2:cnt(b,"i","booked"),S2:cnt(b,"k","showed")};},
    cols:[["SU","1st Showed up"],["Di","Disq."],["Q","Qualified"],["QP","Qualified %",["Q"],["SU"],1],["BK","Booked to 2nd"],["BKP","1st\u21922nd %",["BK"],["SU"],1],["B2","2nd Booked"],["S2","2nd Showed"],["S2P","2nd Showed %",["S2"],["B2"],1]],
    totDays:5,
    tcols:[["SU","1st Rounds Showed up"],["Di","Disqualified"],["Q","Qualified"],["QP","INT Retention",["Q"],["SU"],1],["BK","1st booked to 2nd"],["BKP","2nd Booked Retention",["BK"],["SU"],1],["B2","2nd Round Booked"],["S2","2nd Round Showed"],["S2P","2nd Showed Retention",["S2"],["B2"],1]]}
};

function peopleFor(spec, mon){
  const days=[...Array(6)].map((_,i)=>addD(mon,i));
  const out=new Map();
  for(const p of IDX.people){
    let n=0;
    for(const d of days){ if(spec.who.includes("b")) n+=RB(p,d).length; if(spec.who.includes("j")) n+=RJ(p,d).length; }
    if(n) out.set(p,n);
  }
  return [...out.entries()].sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0])).map(x=>x[0]);
}
function cellPct(col, counts){
  const n=col[2].reduce((s,k)=>s+(counts[k]||0),0), d=col[3].reduce((s,k)=>s+(counts[k]||0),0);
  return {v:pct(n,d), d};
}
function tdFor(col, counts, sep){
  const cls=[]; if(sep) cls.push("sep");
  if(col[2]){ const {v,d}=cellPct(col,counts);
    if(col[4] && d){ const p=Math.round(v*100);
      if(typeof col[4]==="object"){ const g=col[4]; cls.push(p>=g.ok?"ok":(g.mid!=null&&p>=g.mid)?"mid":"bad"); }
      else cls.push(v>=S.goal-1e-9?"ok":"bad"); } else if(!d) cls.push("z");
    return `<td class="${cls.join(" ")}">${fp(v)}</td>`; }
  const x=counts[col[0]]||0; if(!x) cls.push("z");
  return `<td class="${cls.join(" ")}">${x}</td>`;
}
function addInto(t,c){ for(const k in c) t[k]=(t[k]||0)+c[k]; }

function renderWeekly(key){
  const spec=SPECS[key]; const mon=S.week;
  if(!mon) return emptyData();
  const people=peopleFor(spec,mon);
  const days=S.hideDays?[]:[...Array(spec.days)].map((_,i)=>addD(mon,i));
  const sunday=addD(mon,6);
  let h=`<div class="head"><p>Week ${md(mon)} \u2013 ${md(addD(mon,5))} \u00b7 ${esc(spec.note)}</p>
    <button class="btn" id="toggleDays" style="min-height:24px;padding:1px 8px;font-size:12.5px">${S.hideDays?"Show days":"Hide days (totals only)"}</button>
    <span class="legend">${spec.rule?`<span class="pill ok">\u2265 ${spec.rule.ok}%</span>${spec.rule.mid!=null?`<span class="pill mid">${spec.rule.mid}\u2013${spec.rule.ok-1}%</span><span class="pill bad">&lt; ${spec.rule.mid}%</span>`:`<span class="pill bad">&lt; ${spec.rule.ok}%</span>`}`:`<span class="pill ok">\u2265 ${fp(S.goal)}</span><span class="pill bad">&lt; ${fp(S.goal)}</span>`}</span></div>`;
  if(!people.length) return h.replace('<div class="head">',`<div class="head"><h2>${spec.title}</h2>`)+`<div class="card empty"><p>No interviews logged this week for ${esc(S.office?.name)}.</p></div>`;
  h+=`<div class="card scroll ${spec.c}"><table class="rpt"><thead><tr class="ttl"><th colspan="${1+days.length*spec.cols.length+spec.tcols.length}"><span style="position:sticky;left:8px">${spec.title}</span></th></tr><tr class="grp"><th class="name">${md(sunday)}</th>`;
  days.forEach((d,i)=>h+=`<th class="sep" colspan="${spec.cols.length}">${DAYN[i]} ${md(d)}</th>`);
  h+=`<th class="sep" colspan="${spec.tcols.length}">TOTAL for the WEEK</th></tr><tr class="sub"><th class="name">Interviewer</th>`;
  days.forEach(()=>spec.cols.forEach((c,j)=>h+=`<th class="${j?"":"sep"}">${c[1]}</th>`));
  spec.tcols.forEach((c,j)=>h+=`<th class="${j?"":"sep"}" style="white-space:normal;max-width:72px;line-height:1.15">${c[1]}</th>`);
  h+=`</tr></thead><tbody>`;
  const dayTot=days.map(()=>({})), grand={};
  for(const p of people){
    h+=`<tr><td class="name">${esc(p)}</td>`;
    const tot={};
    days.forEach((d,i)=>{const c=spec.day(p,d); addInto(dayTot[i],c); spec.cols.forEach((col,j)=>h+=tdFor(col,c,j===0));});
    for(let i=0;i<spec.totDays;i++) addInto(tot,spec.day(p,addD(mon,i)));
    addInto(grand,tot);
    spec.tcols.forEach((col,j)=>h+=tdFor(col,tot,j===0));
    h+=`</tr>`;
  }
  h+=`<tr class="tot"><td class="name">TOTALS</td>`;
  dayTot.forEach(c=>spec.cols.forEach((col,j)=>h+=tdFor(col,c,j===0)));
  spec.tcols.forEach((col,j)=>h+=tdFor(col,grand,j===0));
  h+=`</tr></tbody></table></div>`;
  return h;
}

// ---------- Ad Titles ----------
function renderAds(){
  if(!S.rows.length) return emptyData();
  const months=[...new Set(S.rows.filter(r=>r.b).map(r=>monthKey(r.b)))].sort().reverse();
  const q=low(S.ads.q);
  const rows=S.rows.filter(r=>(!S.ads.month||monthKey(r.b)===S.ads.month));
  const g=new Map();
  for(const r of rows){ const k=adGroup(r.n)||"(no ad)"; if(q && !low(k).includes(q)) continue; (g.get(k)||g.set(k,[]).get(k)).push(r); }
  const list=[...g.entries()].map(([k,a])=>{
    const o={k,T:a.length,Q:cnt(a,"f","qualify"),Di:cnt(a,"f","disqualify"),De:cnt(a,"f","disqualify - declined"),A:cnt(a,"h","answered"),B:cnt(a,"i","booked"),S:cnt(a,"k","showed"),Y:cnt(a,"l","yes"),BOB:cnt(a,"m","bob")};
    for(let s=1;s<=5;s++) o["s"+s]=cnt(a,"p",s+" star");
    const rs=(v)=>OPT.g.map(x=>{const n=a.filter(r=>low(r.f)===v&&low(r.g)===low(x)).length;return n?x+" "+n:"";}).filter(Boolean).join(" \u00b7 ");
    o.whyDi=rs("disqualify"); o.whyDe=rs("disqualify - declined"); return o;
  }).sort((a,b)=>b.T-a.T);
  let h=`<div class="head"><h2>Ad Titles</h2>${adsToggle()}<p>Grouped with the Excel Ad Groups table. Star % is calculated over Qualified.</p></div>
  <div class="filters"><div class="ctl"><label for="adMonth">Month</label><select id="adMonth"><option value="">All months</option>${months.map(m=>`<option value="${m}" ${m===S.ads.month?"selected":""}>${monthLabel(m+"-01")}</option>`).join("")}</select></div>
  <div class="ctl"><label for="adQ">Filter ads</label><input type="search" id="adQ" value="${esc(S.ads.q)}" placeholder="e.g. Frisco, Arabic\u2026"></div></div>`;
  // reasons summary
  const sum=(v)=>OPT.g.map(x=>[x,rows.filter(r=>low(r.f)===v&&low(r.g)===low(x)&&(!q||low(adGroup(r.n)).includes(q))).length]);
  const box=(t,arr)=>{const mx=Math.max(1,...arr.map(x=>x[1]));const tot=arr.reduce((s,x)=>s+x[1],0);
    return `<div class="card pal-k"><h2>${t} \u2013 Why <span style="color:var(--muted);font-weight:500">(${tot})</span></h2>${arr.map(([k,n])=>`<div class="rbar"><span>${k}</span><div class="track"><div class="fill" style="width:${n/mx*100}%"></div></div><b>${n}</b></div>`).join("")}</div>`;};
  h+=`<div class="reasons">${box("Disqualified",sum("disqualify"))}${box("Declined",sum("disqualify - declined"))}</div>`;
  h+=`<div class="card scroll pal-k"><table class="rpt"><thead><tr class="sub"><th class="name">Ad Titles</th><th>Total Interviews</th><th>Qualify</th><th>Disqualified</th><th>Disq. %</th><th>Declined</th><th>Declined %</th><th>Answer Call</th><th>Booked 2nd Rd</th><th>Showed 2nd Rd</th><th>Offered</th><th>BOB</th>${[1,2,3,4,5].map(s=>`<th class="sep">${s} Star</th><th>%</th>`).join("")}<th class="sep l">Disqualified \u2013 Why</th><th class="l">Declined \u2013 Why</th></tr></thead><tbody>`;
  const z=(n)=>`<td class="${n?"":"z"}">${n}</td>`;
  for(const o of list){
    h+=`<tr><td class="name" style="max-width:380px;overflow:hidden;text-overflow:ellipsis" title="${esc(o.k)}">${esc(o.k)}</td>${z(o.T)}${z(o.Q)}${z(o.Di)}<td>${fp(pct(o.Di,o.T))}</td>${z(o.De)}<td>${fp(pct(o.De,o.T))}</td>${z(o.A)}${z(o.B)}${z(o.S)}${z(o.Y)}${z(o.BOB)}`;
    for(let s=1;s<=5;s++) h+=`<td class="sep ${o["s"+s]?"":"z"}">${o["s"+s]}</td><td>${fp(pct(o["s"+s],o.Q))}</td>`;
    h+=`<td class="sep l">${esc(o.whyDi)}</td><td class="l">${esc(o.whyDe)}</td></tr>`;
  }
  if(!list.length) h+=`<tr><td class="l" colspan="24" style="color:var(--muted)">No ads match this filter.</td></tr>`;
  return h+`</tbody></table></div>`;
}


function adsToggle(){ const v=S.ads.view||"overall";
  return `<div style="display:flex;gap:0"><button class="btn ${v==="overall"?"primary":""}" data-adview="overall" style="border-radius:6px 0 0 6px">Overall</button><button class="btn ${v==="week"?"primary":""}" data-adview="week" style="border-radius:0 6px 6px 0;margin-left:-1px">By week</button></div>`; }
function renderAdsMain(){ return (S.ads.view==="week")?renderAdsWeek():renderAds(); }
function renderAdsWeek(){
  if(!S.rows.length) return emptyData();
  const N=8, weeks=(IDX.weeks||[]).filter(w=>w<=S.week).slice(0,N).reverse();
  if(!S.week||!weeks.length) return emptyData();
  const cur=S.week, prev=weeks.length>1?weeks[weeks.length-2]:null, inSet=new Set(weeks), q=low(S.ads.q), sort=S.ads.wsort||"T";
  const DI="disqualify", DE="disqualify - declined";
  const R={di:{},de:{}}, tot={}, ads=new Map();
  for(const r of S.rows){ if(!r.b) continue; const w=monday(r.b); if(!inSet.has(w)) continue;
    const k=adGroup(r.n)||"(no ad)"; if(q && !low(k).includes(q)) continue;
    const f=low(r.f), g=OPT.g.find(x=>low(x)===low(r.g))||(r.g?"Other":"No reason");
    const t=tot[w]||(tot[w]={T:0,Di:0,De:0}); t.T++; if(f===DI) t.Di++; if(f===DE) t.De++;
    if(f===DI||f===DE){ const b=R[f===DI?"di":"de"]; const m=b[g]||(b[g]={}); m[w]=(m[w]||0)+1; }
    const o=ads.get(k)||ads.set(k,{k,w:{}}).get(k); const c=o.w[w]||(o.w[w]={T:0,Di:0,De:0,why:{di:{},de:{}}}); c.T++;
    if(f===DI){ c.Di++; c.why.di[g]=(c.why.di[g]||0)+1; } if(f===DE){ c.De++; c.why.de[g]=(c.why.de[g]||0)+1; } }
  const pctS=(n,d)=>d?Math.round(n/d*100)+"%":"–";
  const dN=(a,b)=>{ if(b==null) return ""; const d=a-b; return d===0?`<span style="color:var(--muted)">=</span>`:`<span style="color:var(${d>0?"--bad":"--good"});font-weight:700">${d>0?"▲":"▼"} ${Math.abs(d)}</span>`; };
  const dP=(a,b)=>{ if(a==null||b==null) return `<span style="color:var(--muted)">–</span>`; const d=Math.round((a-b)*100); return d===0?`<span style="color:var(--muted)">=</span>`:`<span style="color:var(${d>0?"--bad":"--good"});font-weight:700">${d>0?"▲":"▼"} ${Math.abs(d)} pts</span>`; };
  const tc=tot[cur]||{T:0,Di:0,De:0}, tp=prev?(tot[prev]||{T:0,Di:0,De:0}):null;
  const reasons=b=>{ const keys=[...OPT.g,"Other","No reason"].filter(k=>OPT.g.includes(k)||b[k]); return keys.map(k=>({k,w:b[k]||{}})); };
  const box=(title,key,total,ptotal)=>{ const list=reasons(R[key]); const mx=Math.max(1,...list.map(x=>x.w[cur]||0));
    return `<div class="card pal-k"><h2>${title} – Why <span style="color:var(--muted);font-weight:500">(${total} this week${ptotal!=null?` · ${ptotal} last week`:""})</span></h2>${list.map(x=>{const n=x.w[cur]||0, p=prev?(x.w[prev]||0):null;
      return `<div class="rbar" style="grid-template-columns:150px 1fr 34px 60px"><span>${x.k}</span><div class="track"><div class="fill" style="width:${n/mx*100}%"></div></div><b>${n}</b><span style="text-align:right">${dN(n,p)}</span></div>`;}).join("")}</div>`; };
  let h=`<div class="head"><h2>Ad Titles</h2>${adsToggle()}<p>Week ${md(cur)} – ${md(addD(cur,5))}, by 1st round date. Use the Week selector above to move between weeks. ▲ = more than last week.</p></div>
  <div class="filters"><div class="ctl"><label for="adQ">Filter ads</label><input type="search" id="adQ" value="${esc(S.ads.q)}" placeholder="e.g. Frisco, Arabic…"></div>
  <div class="keyrow">This week: <b style="color:var(--ink)">${tc.T}</b> interviews · Disqualified <b style="color:var(--ink)">${tc.Di}</b> (${pctS(tc.Di,tc.T)}) ${tp?dP(tc.T?tc.Di/tc.T:null,tp.T?tp.Di/tp.T:null):""} · Declined <b style="color:var(--ink)">${tc.De}</b> (${pctS(tc.De,tc.T)}) ${tp?dP(tc.T?tc.De/tc.T:null,tp.T?tp.De/tp.T:null):""}</div></div>`;
  h+=`<div class="reasons">${box("Disqualified","di",tc.Di,tp?tp.Di:null)}${box("Declined","de",tc.De,tp?tp.De:null)}</div>`;
  // reasons week by week
  const trow=(label,w,cls)=>`<tr${cls?` class="${cls}"`:""}><td class="name">${label}</td>${weeks.map(x=>{const n=w[x]||0;return `<td class="${x===cur?"sep":""} ${n?"":"z"}">${n}</td>`;}).join("")}</tr>`;
  h+=`<div class="card scroll pal-k"><table class="rpt"><thead><tr class="sub"><th class="name">Reasons week by week</th>${weeks.map(w=>`<th class="${w===cur?"sep":""}">${md(w)}${w===cur?" ◀":""}</th>`).join("")}</tr></thead><tbody>
  <tr class="tot"><td class="name">Disqualified</td>${weeks.map(w=>`<td class="${w===cur?"sep":""}">${(tot[w]||{}).Di||0} <span style="font-weight:400;color:var(--muted)">(${pctS((tot[w]||{}).Di||0,(tot[w]||{}).T||0)})</span></td>`).join("")}</tr>
  ${reasons(R.di).map(x=>trow("  "+x.k,x.w)).join("")}
  <tr class="tot"><td class="name">Declined</td>${weeks.map(w=>`<td class="${w===cur?"sep":""}">${(tot[w]||{}).De||0} <span style="font-weight:400;color:var(--muted)">(${pctS((tot[w]||{}).De||0,(tot[w]||{}).T||0)})</span></td>`).join("")}</tr>
  ${reasons(R.de).map(x=>trow("  "+x.k,x.w)).join("")}
  <tr><td class="name" style="color:var(--muted)">Total interviews</td>${weeks.map(w=>`<td class="${w===cur?"sep":""}" style="color:var(--muted)">${(tot[w]||{}).T||0}</td>`).join("")}</tr></tbody></table></div>`;
  // ads this week
  const why=m=>Object.entries(m).sort((a,b)=>b[1]-a[1]).map(([k,n])=>k+" "+n).join(" · ");
  const list=[...ads.values()].map(o=>{ const c=o.w[cur]||{T:0,Di:0,De:0,why:{di:{},de:{}}}, p=prev?o.w[prev]:null;
    const dr=c.T?c.Di/c.T:null, er=c.T?c.De/c.T:null, pdr=p&&p.T?p.Di/p.T:null, per=p&&p.T?p.De/p.T:null;
    return {k:o.k,c,p,T:c.T,dr,er,pdr,per,dd:(dr!=null&&pdr!=null)?dr-pdr:null,de:(er!=null&&per!=null)?er-per:null}; }).filter(o=>o.T>0);
  const so={T:(a,b)=>b.T-a.T,dr:(a,b)=>(b.dr??-1)-(a.dr??-1),er:(a,b)=>(b.er??-1)-(a.er??-1),dd:(a,b)=>(b.dd??-9)-(a.dd??-9),de:(a,b)=>(b.de??-9)-(a.de??-9),name:(a,b)=>a.k.localeCompare(b.k)};
  list.sort((a,b)=>so[sort](a,b)||b.T-a.T);
  const th=(k,l)=>`<th class="sort" data-adwsort="${k}">${l}${sort===k?(k==="name"?" ↑":" ↓"):""}</th>`;
  h+=`<div class="card scroll pal-k"><table class="rpt"><thead><tr class="sub"><th class="name sort" data-adwsort="name">Ad Titles this week${sort==="name"?" ↑":""}</th>${th("T","Interviews")}<th>Disqualified</th>${th("dr","Disq. %")}${th("dd","vs last week")}<th>Declined</th>${th("er","Declined %")}${th("de","vs last week")}<th class="sep l">Disqualified – Why</th><th class="l">Declined – Why</th></tr></thead><tbody>`;
  for(const o of list){ h+=`<tr><td class="name" style="max-width:360px;overflow:hidden;text-overflow:ellipsis" title="${esc(o.k)}">${esc(o.k)}</td><td>${o.T}</td><td class="${o.c.Di?"":"z"}">${o.c.Di}</td><td>${pctS(o.c.Di,o.T)}</td><td>${dP(o.dr,o.pdr)}</td><td class="${o.c.De?"":"z"}">${o.c.De}</td><td>${pctS(o.c.De,o.T)}</td><td>${dP(o.er,o.per)}</td><td class="sep l">${esc(why(o.c.why.di))}</td><td class="l">${esc(why(o.c.why.de))}</td></tr>`; }
  if(!list.length) h+=`<tr><td class="l" colspan="10" style="color:var(--muted)">No interviews this week${q?" for this filter":""}.</td></tr>`;
  h+=`</tbody></table></div><p style="margin:0;color:var(--muted);font-size:12.5px">"vs last week" compares the share of interviews that were disqualified or declined: red ▲ = a bigger share than last week, green ▼ = a smaller share.</p>`;
  return h;
}

// ---------- Ads x Stars ----------
function renderStarsOverall(){
  if(!S.rows.length) return emptyData();
  const T=S.st, months=[...new Set(S.rows.filter(r=>r.b).map(r=>monthKey(r.b)))].sort().reverse();
  const g=new Map();
  for(const r of S.rows){ if(T.month && monthKey(r.b)!==T.month) continue;
    const m=String(r.p||"").match(/^([1-5])\s*star/i); const k=adGroup(r.n)||"(no ad)";
    const o=g.get(k)||g.set(k,{k,T:0,R:0,sum:0,s:[0,0,0,0,0,0]}).get(k); o.T++;
    if(m){ const s=+m[1]; o.R++; o.sum+=s; o.s[s]++; } }
  const all=[...g.values()].filter(o=>o.R>0).map(o=>({...o,avg:o.sum/o.R,hi:(o.s[4]+o.s[5])/o.R,lo:(o.s[1]+o.s[2])/o.R}));
  const elig=all.filter(o=>o.R>=T.min && o.k!=="(no ad)");
  const totR=all.reduce((s,o)=>s+o.R,0), totSum=all.reduce((s,o)=>s+o.sum,0), base=totR?totSum/totR:0;
  const best=[...elig].sort((a,b)=>b.avg-a.avg||b.R-a.R).slice(0,5), worst=[...elig].sort((a,b)=>a.avg-b.avg||b.R-a.R).slice(0,5);
  const f2=v=>v.toFixed(2);
  const dist=o=>`<div class="dist" title="${[1,2,3,4,5].map(s=>s+"\u2605 "+o.s[s]).join(" \u00b7 ")}">${[1,2,3,4,5].map(s=>o.s[s]?`<span class="s${s}" style="width:${o.s[s]/o.R*100}%"></span>`:"").join("")}</div>`;
  const li=(o,i)=>`<li><span class="n">${i+1}</span><span class="t" title="${esc(o.k)}">${esc(o.k)}<small>${o.R} rated \u00b7 ${fp(o.hi)} with 4\u20135\u2605</small></span><span class="avg ${o.avg>=base?"ok":"bad"}">${f2(o.avg)}\u2605</span></li>`;
  let h=`<div class="head"><h2>Ads \u00d7 Stars</h2>${starToggle()}<p>Average Star Rating per ad. Only interviews with a star rating count.</p></div>
  <div class="filters"><div class="ctl"><label for="stMonth">Month</label><select id="stMonth"><option value="">All months</option>${months.map(m=>`<option value="${m}" ${m===T.month?"selected":""}>${monthLabel(m+"-01")}</option>`).join("")}</select></div>
  <div class="ctl"><label for="stMin">Minimum rated interviews to rank</label><select id="stMin">${[1,5,10,20,50].map(n=>`<option value="${n}" ${n===T.min?"selected":""}>${n}+</option>`).join("")}</select></div>
  <div class="keyrow">Overall average <b class="avg" style="font-size:15px;color:var(--ink)">${f2(base)}\u2605</b> across ${totR.toLocaleString("en-US")} interviews \u00b7 ${[1,2,3,4,5].map(s=>`<span><i class="s${s}"></i>${s}\u2605</span>`).join("")}</div></div>`;
  if(!elig.length) return h+`<div class="card empty"><p>No ad reaches ${T.min} rated interviews with these settings. Lower the minimum or pick another month.</p></div>`;
  h+=`<div class="rank pal-k"><div class="card"><h2>Highest rated</h2><ol>${best.map(li).join("")}</ol></div>
  <div class="card"><h2>Lowest rated</h2><ol>${worst.map(li).join("")}</ol></div></div>`;
  const sorters={avg:(a,b)=>b.avg-a.avg,R:(a,b)=>b.R-a.R,hi:(a,b)=>b.hi-a.hi,lo:(a,b)=>b.lo-a.lo};
  const list=[...all].sort((a,b)=>(a.R>=T.min)-(b.R>=T.min)?(b.R>=T.min)-(a.R>=T.min):(sorters[T.sort](a,b)||b.R-a.R));
  const th=(k,l)=>`<th class="sort" data-sort="${k}" aria-sort="${T.sort===k?"descending":"none"}">${l}${T.sort===k?" \u2193":""}</th>`;
  h+=`<div class="card scroll pal-k"><table class="rpt"><thead><tr class="sub"><th class="name">Ad Title</th>${th("R","Rated")}${th("avg","Average")}<th class="l">Distribution</th>${[1,2,3,4,5].map(s=>`<th>${s}\u2605</th>`).join("")}${th("hi","% 4\u20135\u2605")}${th("lo","% 1\u20132\u2605")}<th>Interviews</th></tr></thead><tbody>`;
  for(const o of list){ const low_=o.R<T.min;
    h+=`<tr style="${low_?"opacity:.55":""}"><td class="name" style="max-width:380px;overflow:hidden;text-overflow:ellipsis" title="${esc(o.k)}">${esc(o.k)}</td><td>${o.R}</td><td class="${low_?"":o.avg>=base?"ok":"bad"}">${f2(o.avg)}</td><td class="l">${dist(o)}</td>${[1,2,3,4,5].map(s=>`<td class="${o.s[s]?"":"z"}">${o.s[s]}</td>`).join("")}<td>${fp(o.hi)}</td><td>${fp(o.lo)}</td><td class="z" style="opacity:1">${o.T}</td></tr>`; }
  h+=`</tbody></table></div><p style="margin:0;color:var(--muted);font-size:12.5px">Green = average at or above the overall average (${f2(base)}\u2605), red = below it. Ads with fewer than ${T.min} rated interviews are dimmed at the bottom and left out of the ranking.</p>`;
  return h;
}


function starToggle(){ const v=S.st.view||"overall";
  return `<div style="display:flex;gap:0"><button class="btn ${v==="overall"?"primary":""}" data-stview="overall" style="border-radius:6px 0 0 6px">Overall</button><button class="btn ${v==="week"?"primary":""}" data-stview="week" style="border-radius:0 6px 6px 0;margin-left:-1px">By week</button></div>`; }
function renderStars(){ return (S.st.view==="week")?renderStarsWeek():renderStarsOverall(); }
function renderStarsWeek(){
  if(!S.rows.length) return emptyData();
  const T=S.st, min=T.wmin||3, sort=T.wsort||"avg", N=8;
  const weeks=(IDX.weeks||[]).filter(w=>w<=S.week).slice(0,N).reverse();
  if(!S.week||!weeks.length) return emptyData();
  const cur=S.week, prev=weeks.length>1?weeks[weeks.length-2]:null, inSet=new Set(weeks);
  const ads=new Map(), wk={};
  for(const r of S.rows){ if(!r.b) continue; const w=monday(r.b); if(!inSet.has(w)) continue;
    const m=String(r.p||"").match(/^([1-5])\s*star/i); if(!m) continue; const s=+m[1];
    const k=adGroup(r.n)||"(no ad)";
    const o=ads.get(k)||ads.set(k,{k,w:{}}).get(k); const c=o.w[w]||(o.w[w]={R:0,sum:0,s:[0,0,0,0,0,0]}); c.R++; c.sum+=s; c.s[s]++;
    const t=wk[w]||(wk[w]={R:0,sum:0}); t.R++; t.sum+=s; }
  const avgOf=c=>c&&c.R?c.sum/c.R:null, f2=v=>v==null?"–":v.toFixed(2);
  const base=avgOf(wk[cur]), basePrev=prev?avgOf(wk[prev]):null;
  const list=[...ads.values()].map(o=>{ const c=o.w[cur], p=prev?o.w[prev]:null; const a=avgOf(c), pa=avgOf(p);
    return {...o, R:c?c.R:0, avg:a, pavg:pa, pR:p?p.R:0, d:(a!=null&&pa!=null)?a-pa:null, c}; });
  const elig=list.filter(o=>o.k!=="(no ad)"&&o.R>=min);
  const best=[...elig].sort((a,b)=>b.avg-a.avg||b.R-a.R).slice(0,5), worst=[...elig].sort((a,b)=>a.avg-b.avg||b.R-a.R).slice(0,5);
  const movers=elig.filter(o=>o.d!=null&&o.pR>=min), up=[...movers].sort((a,b)=>b.d-a.d).filter(o=>o.d>0).slice(0,5), down=[...movers].sort((a,b)=>a.d-b.d).filter(o=>o.d<0).slice(0,5);
  const delta=d=>d==null?`<span style="color:var(--muted)">new</span>`:Math.abs(d)<0.005?`<span style="color:var(--muted)">=</span>`:`<span style="color:var(${d>0?"--good":"--bad"});font-weight:700">${d>0?"▲":"▼"} ${Math.abs(d).toFixed(2)}</span>`;
  const li=(o,i,showD)=>`<li><span class="n">${i+1}</span><span class="t" title="${esc(o.k)}">${esc(o.k)}<small>${o.R} rated this week${o.pR?` · last week ${f2(o.pavg)}★ (${o.pR})`:""}</small></span><span style="display:flex;gap:8px;align-items:center">${showD?delta(o.d):""}<span class="avg ${o.avg>=base?"ok":"bad"}">${f2(o.avg)}★</span></span></li>`;
  const card=(t,arr,showD,empty)=>`<div class="card"><h2>${t}</h2>${arr.length?`<ol>${arr.map((o,i)=>li(o,i,showD)).join("")}</ol>`:`<p style="color:var(--muted);margin:0">${empty}</p>`}</div>`;
  let h=`<div class="head"><h2>Ads × Stars</h2>${starToggle()}<p>Week ${md(cur)} – ${md(addD(cur,5))}, by 1st round date. Use the Week selector above to move between weeks.</p></div>
  <div class="filters"><div class="ctl"><label for="stWMin">Minimum rated this week to rank</label><select id="stWMin">${[1,3,5,10].map(n=>`<option value="${n}" ${n===min?"selected":""}>${n}+</option>`).join("")}</select></div>
  <div class="keyrow">This week's average <b class="avg" style="font-size:15px;color:var(--ink)">${f2(base)}★</b> across ${(wk[cur]||{R:0}).R} rated interviews${basePrev!=null?` · last week ${f2(basePrev)}★ ${base!=null?delta(base-basePrev):""}`:""}</div></div>`;
  h+=`<div class="rank pal-k" style="grid-template-columns:repeat(auto-fit,minmax(300px,1fr))">${card("Best ads this week",best,false,`No ad reaches ${min} rated interviews this week.`)}${card("Worst ads this week",worst,false,`No ad reaches ${min} rated interviews this week.`)}${card("Biggest improvement vs last week",up,true,"No ad improved vs last week.")}${card("Biggest drop vs last week",down,true,"No ad dropped vs last week.")}</div>`;
  const sorters={avg:(a,b)=>(b.avg??-1)-(a.avg??-1),d:(a,b)=>(b.d??-9)-(a.d??-9),R:(a,b)=>b.R-a.R,name:(a,b)=>a.k.localeCompare(b.k)};
  const rows=list.filter(o=>o.k!=="(no ad)").sort((a,b)=>((b.R>=min)-(a.R>=min))||sorters[sort](a,b)||b.R-a.R);
  const th=(k,l)=>`<th class="sort" data-wsort="${k}" aria-sort="${sort===k?(k==="name"?"ascending":"descending"):"none"}">${l}${sort===k?(k==="name"?" ↑":" ↓"):""}</th>`;
  h+=`<div class="card scroll pal-k"><table class="rpt"><thead><tr class="sub"><th class="name sort" data-wsort="name">Ad Title${sort==="name"?" ↑":""}</th>${th("R","Rated this week")}${th("avg","Avg this week")}${th("d","vs last week")}${weeks.map(w=>`<th class="${w===cur?"sep":""}" title="Week of ${md(w)}">${md(w)}${w===cur?" ◀":""}</th>`).join("")}</tr>
  <tr class="tot"><td class="name">All ads</td><td>${(wk[cur]||{R:0}).R}</td><td>${f2(base)}</td><td>${base!=null&&basePrev!=null?delta(base-basePrev):""}</td>${weeks.map(w=>`<td>${f2(avgOf(wk[w]))}</td>`).join("")}</tr></thead><tbody>`;
  for(const o of rows){ const dim=o.R<min;
    h+=`<tr style="${dim?"opacity:.55":""}"><td class="name" style="max-width:360px;overflow:hidden;text-overflow:ellipsis" title="${esc(o.k)}">${esc(o.k)}</td><td>${o.R||""}</td><td class="${o.avg==null||dim?"":o.avg>=base?"ok":"bad"}">${f2(o.avg)}</td><td>${o.avg==null?"":delta(o.d)}</td>`;
    for(const w of weeks){ const c=o.w[w], a=avgOf(c), wb=avgOf(wk[w]);
      h+=`<td class="${a==null?"z":a>=wb?"ok":"bad"}" title="${c?`${c.R} rated · week avg ${f2(wb)}`:"No ratings"}" style="${a==null?"":"opacity:"+(c.R>=min?1:.6)}">${a==null?"·":f2(a)}</td>`; }
    h+=`</tr>`; }
  if(!rows.length) h+=`<tr><td class="l" colspan="${4+weeks.length}" style="color:var(--muted)">No star ratings in these weeks.</td></tr>`;
  h+=`</tbody></table></div><p style="margin:0;color:var(--muted);font-size:12.5px">Each week column shows that ad's average stars. Green = at or above that week's average for all ads, red = below. Faded cells have fewer than ${min} rated interviews. Hover a cell to see how many were rated.</p>`;
  return h;
}

// ---------- Data entry ----------
function sel(f,v,id,extra=""){
  const opts=f==="d"?S.ints:OPT[f]; let o=`<option value=""></option>`;
  if(v && !opts.includes(v)) o+=`<option selected>${esc(v)}</option>`;
  for(const x of opts) o+=`<option ${x===v?"selected":""}>${esc(x)}</option>`;
  return `<select data-f="${f}" ${id?`id="${id}"`:""} ${extra} ${S.canWrite?"":"disabled"} aria-label="${f}">${o}</select>`;
}
function inp(f,v,type,cls,id){ return `<input type="${type}" class="${cls||""}" data-f="${f}" ${id?`id="${id}"`:""} value="${esc(v||"")}" ${f==="n"?'autocomplete="off" spellcheck="false"':""} ${S.canWrite?"":"disabled"} aria-label="${f}">`; }
function renderEntry(){
  const months=[...new Set(S.rows.filter(r=>r.b).map(r=>monthKey(r.b)))].sort().reverse();
  const E=S.ent, q=low(E.q);
  const d2c={}; for(const r of S.rows){ if(r.j && (!E.month||monthKey(r.b)===E.month) && (!E.who||r.d===E.who)) d2c[r.j]=(d2c[r.j]||0)+1; }
  const d2opts=Object.entries(d2c).sort((a,b)=>b[0].localeCompare(a[0]));
  const cc={}; for(const r of S.rows){ if((!E.month||monthKey(r.b)===E.month)&&(!E.who||r.d===E.who)){ const c=city(r.n)||"(no city)"; cc[c]=(cc[c]||0)+1; } }
  const cityOpts=Object.entries(cc).sort((a,b)=>a[0]==="(no city)"?1:b[0]==="(no city)"?-1:a[0].localeCompare(b[0]));
  let rows=S.rows.filter(r=>(!E.month||monthKey(r.b)===E.month)&&(!E.d2||r.j===E.d2)&&(!E.city||city(r.n)===E.city)&&(!E.who||r.d===E.who)&&(!q||low(r.e).includes(q)||low(r.n).includes(q)));
  rows.sort((a,b)=>(b.b||"").localeCompare(a.b||"")||(b.t||0)-(a.t||0));
  const per=100, pages=Math.max(1,Math.ceil(rows.length/per)); if(E.page>=pages) E.page=pages-1;
  const view=rows.slice(E.page*per,E.page*per+per);
  let h=`
  <div class="head"><h2>Data Entry \u00b7 ${esc(S.office?.name||"")}</h2><p>${S.rows.length.toLocaleString("en-US")} interviews. Every change saves automatically to the Google Sheet. The page refreshes every minute.</p></div>
  <div class="filters"><div class="ctl"><label for="eMonth">Month</label><select id="eMonth"><option value="">All</option>${months.map(m=>`<option value="${m}" ${m===E.month?"selected":""}>${monthLabel(m+"-01")}</option>`).join("")}</select></div>
  <div class="ctl"><label for="eWho">Interviewer</label><select id="eWho"><option value="">All</option>${IDX.people.slice().sort().map(p=>`<option ${p===E.who?"selected":""}>${esc(p)}</option>`).join("")}</select></div>
  <div class="ctl"><label for="eCity">City</label><select id="eCity"><option value="">All</option>${cityOpts.map(([c,n])=>`<option value="${esc(c==="(no city)"?"":c)}" ${c===E.city?"selected":""} ${c==="(no city)"?"disabled":""}>${esc(c)} (${n})</option>`).join("")}</select></div>
  <div class="ctl"><label for="eD2">Date 2nd Rd</label><select id="eD2"><option value="">All</option>${d2opts.map(([d,n])=>`<option value="${d}" ${d===E.d2?"selected":""}>${toD(d).toLocaleDateString("en-US",{weekday:"short",month:"short",day:"numeric",year:"numeric",timeZone:"UTC"})} (${n})</option>`).join("")}</select></div>
  <div class="ctl"><label for="eQ">Search</label><input type="search" id="eQ" value="${esc(E.q)}" placeholder="Name or ad"></div>${S.role==="admin"?`<button class="btn" data-act="ints">Interviewer list (${S.ints.length})</button>`:""}</div>
  ${!S.ints.length&&S.role==="admin"?`<div class="card" style="padding:8px 12px;border-color:var(--accent)">The interviewer list is empty. <button class="btn primary" data-act="ints">Add interviewers</button> to fill the 1st Round Interviewer dropdown for every office.</div>`:""}
  <div class="card scroll entry pal-k"><table class="rpt"><thead><tr class="sub"><th class="name">#</th><th class="l">Date 1st Rd</th><th class="l">Month</th><th class="l">1st Round Interviewer</th><th class="l">Full Name</th><th class="l">Qualify</th><th class="l">Reasons</th><th class="l">Answer Call</th><th class="l">Booked to 2nd Rd</th><th class="l">Date 2nd Rd</th><th class="l">Showed Up to 2nd Round</th><th class="l">Offered Position</th><th class="l">BOB</th><th class="l">Ad Title</th><th class="l">City</th><th class="l">Star Rating</th><th></th></tr></thead><tbody>`;
  if(S.canWrite){
    const L=S.lastAdd||{};
    h+=`<tr class="addrow" id="addRow"><td class="name" style="background:var(--accent-soft)">New</td><td>${inp("b",L.b||today(),"date","","nb")}</td><td class="ro">\u2013</td><td>${sel("d",L.d&&S.ints.includes(L.d)?L.d:"","nd")}</td><td>${inp("e","","text","w-name","ne")}</td><td>${sel("f","Qualify","nf")}</td><td>${sel("g","","ng")}</td><td>${sel("h","","nh")}</td><td>${sel("i","","ni")}</td><td>${inp("j","","date","","nj")}</td><td>${sel("k","","nk")}</td><td>${sel("l","","nl")}</td><td>${sel("m","","nm")}</td><td>${inp("n",L.n,"text","w-ad","nn")}</td><td class="ro">\u2013</td><td>${sel("p","","np")}</td><td><button class="btn primary" id="addGo">Add</button></td></tr>`;
  }
  view.forEach((r,i)=>{
    h+=`<tr data-id="${r.id}"><td class="name idx">${E.page*per+i+1}</td><td>${inp("b",r.b,"date")}</td><td class="ro">${esc(monthLabel(r.b))}</td><td>${sel("d",r.d)}</td><td>${inp("e",r.e,"text","w-name")}</td><td>${sel("f",r.f)}</td><td>${sel("g",r.g)}</td><td>${sel("h",r.h)}</td><td>${sel("i",r.i)}</td><td>${inp("j",r.j,"date")}</td><td>${sel("k",r.k)}</td><td>${sel("l",r.l)}</td><td>${sel("m",r.m)}</td><td>${inp("n",r.n,"text","w-ad")}</td><td class="ro">${esc(city(r.n))}</td><td>${sel("p",r.p)}</td><td></td></tr>`;
  });
  if(!view.length) h+=`<tr><td class="l" colspan="17" style="color:var(--muted);padding:16px">No interviews match these filters.</td></tr>`;
  h+=`</tbody></table></div><div class="pager"><button class="btn" id="pPrev" ${E.page?"":"disabled"}>\u2039 Previous</button><span>Page ${E.page+1} of ${pages} \u00b7 ${rows.length.toLocaleString("en-US")} rows</span><button class="btn" id="pNext" ${E.page<pages-1?"":"disabled"}>Next \u203a</button></div>`;
  return h;
}

function emptyData(){
  if(!S.loaded) return `<div class="card empty"><p>Loading data\u2026</p></div>`;
  if(!S.offices.length) return `<div class="card empty"><h2>No offices yet</h2><p>Import your ARS report Excel files to get started, or create a new office and log interviews by hand.</p>${S.role==="admin"?`<div style="display:flex;gap:8px"><button class="btn primary" data-act="import">Import Excel</button><button class="btn" data-act="office">+ Office</button></div>`:"<p>Ask an Admin to add offices.</p>"}</div>`;
  return `<div class="card empty"><h2>${esc(S.office?.name)} has no interviews yet</h2><p>Log the first one in the Data Entry tab.</p><button class="btn primary" data-act="entry">Go to Data Entry</button></div>`;
}

// cells that don't apply because an earlier step ended the funnel (shown black, like the Excel)
function naFields(v){
  const s=new Set(), add=(...a)=>a.forEach(x=>s.add(x));
  const f=low(v.f), hh=low(v.h), k=low(v.k);
  if(f==="disqualify"||f==="disqualify - declined") add("h","i","j","k","l","m");
  if(hh==="no answer"||hh==="not contacted") add("i","j","k","l","m");
  if(low(v.i)==="not booked") add("j","k","l","m");
  if(k==="no show"||k==="cancelled"||k==="reschedule requested") add("l","m");
  if(low(v.l)==="no") add("m");
  return s;
}
const VCOL={
  f:{"qualify":"g","disqualify":"r","disqualify - declined":"o"},
  h:{"answered":"g","no answer":"r"},
  i:{"booked":"g","not booked":"r"},
  p:{"1 star":"r","2 star":"o","3 star":"b","4 star":"v","5 star":"y"}
};
function applyNA(tr){
  const v={}; tr.querySelectorAll("[data-f]").forEach(c=>v[c.dataset.f]=c.value);
  const na=naFields(v);
  tr.querySelectorAll("[data-f]").forEach(c=>{ const on=na.has(c.dataset.f);
    const col=on?"":(VCOL[c.dataset.f]||{})[low(c.value)]||""; const tdc=c.closest("td"); tdc.classList.remove("v-g","v-r","v-o","v-b","v-v","v-y"); if(col) tdc.classList.add("v-"+col); const td=c.closest("td"); td.classList.toggle("na",on); c.disabled=on||!S.canWrite; c.tabIndex=on?-1:0; if(on) c.title="Not applicable"; else c.removeAttribute("title"); });
}

// ---------- Interviewers Retention (Raf 11/20) ----------
// The daily 6 PM email's 4 tables, written by a Lucy into the 'Retention Report'
// tab. Two views: the offices that use our interviewing service (= the email),
// or every office in our org (offices from AppStream; interviewer rows only
// exist for the service). Same for every office, so the Office menu does nothing here.
async function loadRetention(){
  S.ret.loading=true; S.ret.err="";
  try{ const t=await api("getRetention"); S.ret.data=t?JSON.parse(t):{}; }
  catch(e){ S.ret.err=e.message; }
  S.ret.loading=false; if(S.tab==="retention") render();
}
function retCls(v){ if(v==null) return "z"; return Math.round(v*100)>=Math.round((S.ret.data.goal||0.5)*100)?"ok":"bad"; }
function retPct(v){ return `<td class="${retCls(v)}">${v==null?"–":fp(v)}</td>`; }
function retName(l){ return `${esc(l.name)}${l.detail&&l.detail.length&&!l.owner?`<div style="font-weight:400;font-size:11px;color:var(--muted)">${esc(l.detail.join(", "))}</div>`:""}`; }
function retBoard(b){
  const owner=b.header==="Interviewer", days=b.days||null, hl=b.history_labels||[];
  const cols=2+(owner?1:0)+(days?days.length*3+3:3)+hl.length;
  let h=`<div class="card scroll pal-s"><table class="rpt"><thead><tr class="ttl"><th colspan="${cols}"><span style="position:sticky;left:8px">${esc(b.title)}</span> <span style="font-weight:400;text-transform:none;letter-spacing:0">· ${esc(b.subtitle)}</span></th></tr>`;
  h+=`<tr class="grp"><th></th><th class="name"></th>${owner?"<th></th>":""}`;
  if(days) days.forEach(d=>h+=`<th class="sep" colspan="3">${DAYN[(toD(d).getUTCDay()+6)%7]||""} ${md(d)}</th>`);
  h+=`<th class="sep" colspan="3">${days?"WEEK":"TOTAL"}</th>${hl.length?`<th class="sep" colspan="${hl.length}">LAST ${hl.length} WEEKS</th>`:""}</tr>`;
  h+=`<tr class="sub"><th>#</th><th class="name">${esc(b.header)}</th>${owner?`<th class="l">Owner</th>`:""}`;
  const bsp=()=>`<th class="sep">B</th><th>S</th><th>%</th>`;
  if(days) days.forEach(()=>h+=bsp());
  h+=bsp(); hl.forEach((l,i)=>h+=`<th class="${i?"":"sep"}">${esc(l)}</th>`); h+=`</tr></thead><tbody>`;
  if(!b.lines.length) h+=`<tr><td colspan="${cols}" class="l" style="color:var(--muted)">No 2nd rounds recorded.</td></tr>`;
  b.lines.forEach((l,i)=>{
    h+=`<tr><td>${i+1}</td><td class="name">${retName(l)}</td>${owner?`<td class="l">${esc(l.owner)}</td>`:""}`;
    if(days) l.days.forEach(([bk,sh])=>{ const v=bk?sh/bk:null; h+=`<td class="sep${bk?"":" z"}">${bk}</td><td class="${sh?"":"z"}">${sh}</td>${bk?retPct(v):`<td class="z"></td>`}`; });
    h+=`<td class="sep">${l.booked}</td><td>${l.showed}</td>${retPct(l.pct)}`;
    (l.history||[]).forEach((v,j)=>h+=`<td class="${retCls(v)}${j?"":" sep"}">${v==null?"–":fp(v)}</td>`);
    h+=`</tr>`;
  });
  return h+`</tbody></table></div>`;
}
function renderRetention(){
  if(!S.ret.data && !S.ret.loading && !S.ret.err) loadRetention();
  if(S.ret.err) return `<div class="card empty"><p>Couldn't load the report: ${esc(S.ret.err)}</p><button class="btn" data-act="retReload">Try again</button></div>`;
  if(!S.ret.data) return `<div class="card empty"><p>Loading the Interviewers Retention report…</p></div>`;
  const d=S.ret.data, views=d.views||{};
  if(!Object.keys(views).length) return `<div class="card empty"><h2>No report yet</h2><p>The Interviewers Retention report shows up here after its next daily run.</p></div>`;
  if(!views[S.ret.view]) S.ret.view=Object.keys(views)[0];
  const v=views[S.ret.view], g=fp(d.goal||0.5);
  let h=`<div class="head"><h2>Interviewers Retention</h2><p>2nd rounds showed / booked · updated ${esc(d.generated||"")}</p>
    <span class="legend"><span class="pill ok">≥ ${g}</span><span class="pill bad">&lt; ${g}</span></span></div>
    <div class="filters"><div class="ctl"><label for="retView">Show</label><select id="retView">${Object.keys(views).map(k=>`<option value="${k}" ${k===S.ret.view?"selected":""}>${esc(views[k].label)}</option>`).join("")}</select></div></div>`;
  v.boards.forEach(b=>h+=retBoard(b));
  if(d.notes&&d.notes.length) h+=`<p style="font-size:11.5px;color:var(--muted);margin:0">${d.notes.map(esc).join("<br>")}${S.ret.view==="org"?"<br>Our org: every office on the Hub's office lists, 2nd rounds from AppStream. Interviewer rows exist only for offices that use our interviewing service.":""}</p>`;
  return h;
}
document.addEventListener("change",e=>{ if(e.target.id==="retView"){ S.ret.view=e.target.value; try{localStorage.setItem("ars.retview",S.ret.view);}catch(x){} render(); } });
document.addEventListener("click",e=>{ if(e.target.closest("[data-act=retReload]")){ S.ret.err=""; S.ret.data=null; render(); } });

// ---------- render ----------
function renderTabs(){
  $("#tabs").innerHTML=TABS.filter(t=>!t.admin||S.role==="admin").map(t=>`<button class="tab" role="tab" aria-selected="${t.id===S.tab}" data-tab="${t.id}" style="--tc:${t.c}">${t.label}</button>`).join("");
}
function renderWeeks(){
  const w=$("#week"); const ws=IDX?IDX.weeks:[];
  if(!S.week || !ws.includes(S.week)){ const t=monday(today()); S.week=ws.find(x=>x<=t)||ws[0]||null; }
  w.innerHTML=ws.map(m=>`<option value="${m}" ${m===S.week?"selected":""}>${md(m)} \u2013 ${md(addD(m,5))} ${toD(m).getUTCFullYear()}</option>`).join("")||`<option>No data</option>`;
  const i=ws.indexOf(S.week); $("#wPrev").disabled=i<0||i>=ws.length-1; $("#wNext").disabled=i<=0;
}
function render(){
  renderTabs();
  $("#weekCtl").style.visibility=(S.tab==="entrada"||S.tab==="retention"||(S.tab==="ads"&&S.ads.view!=="week")||(S.tab==="stars"&&S.st.view!=="week")||S.tab==="users")?"hidden":"visible";
  $("#goal").value=String(S.goal);
  $("#office").innerHTML=S.offices.length?S.offices.map(o=>`<option value="${o.id}" ${o.id===S.office?.id?"selected":""}>${esc(o.name)}</option>`).join(""):`<option>No offices</option>`;
  const adm=S.role==="admin"; $("#addOffice").hidden=!adm; $("#importBtn").hidden=!adm; $("#manageOffices").hidden=!adm;
  if(!IDX) buildIndex();
  renderWeeks();
  $("#sub").textContent=S.office? `${S.office.name} \u00b7 ${S.rows.length.toLocaleString("en-US")} interviews`: (S.loaded?"No offices":"Loading\u2026");
  const m=$("#main");
  if(S.tab==="users"){ if(S.role!=="admin") S.tab="entrada"; else { m.innerHTML=renderUsers(); return; } }
  if(S.tab==="retention"){ m.innerHTML=renderRetention(); return; }
  if(!S.office || (!S.rows.length && S.tab!=="entrada")) { m.innerHTML=emptyData(); return; }
  if(S.tab==="entrada"){ m.innerHTML=renderEntry(); m.querySelectorAll("tr[data-id],#addRow").forEach(applyNA); }
  else if(S.tab==="ads") m.innerHTML=renderAdsMain();
  else if(S.tab==="stars") m.innerHTML=renderStars();
  else m.innerHTML=renderWeekly(S.tab);
}

// ---------- server (Google Apps Script) ----------
const PUBLIC_FNS=["login","needsSetup","setupAdmin"];
function rawApi(fn,...args){ return new Promise((ok,no)=>{ google.script.run.withSuccessHandler(ok).withFailureHandler(e=>no(new Error((e&&e.message)||String(e))))[fn](...args); }); }
function api(fn,...args){
  const p=PUBLIC_FNS.includes(fn)?rawApi(fn,...args):rawApi(fn,S.token,...args);
  return p.catch(e=>{ if(/AUTH:/.test(e.message)){ signOut(true); } throw e; });
}
let saveChain=Promise.resolve(), pending=0;
function writeRow(row){
  const oid=S.office.id; status("Saving\u2026"); pending++;
  const val=[row.id,...FIELDS.map(f=>row[f]||""),row.t||Date.now()];
  saveChain=saveChain.then(()=>api("saveRow",oid,val)).then(()=>status("Saved"),e=>status("Couldn't save: "+e.message,true)).finally(()=>pending--);
  return saveChain;
}
let loadSeq=0;
async function loadRows(quiet){
  if(!S.office) return; const oid=S.office.id, seq=++loadSeq;
  try{
    const rows=await api("getRows",oid);
    if(seq!==loadSeq||!S.office||S.office.id!==oid||(quiet&&pending)) return;
    S.rows=rows.map(a=>{const r={id:a[0],t:a[14]||0}; FIELDS.forEach((f,i)=>r[f]=a[i+1]||""); r.wk=r.b?monday(r.b):"sin-fecha"; return r;});
    S.loaded=true; buildIndex();
    const ae=document.activeElement, editing=ae&&ae.closest&&ae.closest("tr[data-id],#addRow,.modal.on");
    if(!editing) render(); else S.pendingRender=true;
  }catch(e){ if(!quiet){ status("Couldn't read data: "+e.message,true); S.loaded=true; render(); } }
}
function subscribeOffice(){
  S.rows=[]; IDX=null; S.loaded=false; render();
  if(!S.office){ S.loaded=true; render(); return; }
  loadRows(false);
}
// pick up the team's changes every minute while the page is open
setInterval(()=>{ if(document.visibilityState==="visible" && S.office && !pending) loadRows(true); },60000);
function setOffice(id){
  S.office=S.offices.find(o=>o.id===id)||S.offices[0]||null;
  try{ if(S.office) localStorage.setItem("ars.office",S.office.id);}catch(e){}
  S.ent.page=0; S.week=null; subscribeOffice();
}

// ---------- import ----------
// ---------- import from uploaded Excel files ----------
const HDR={b:["date 1st rd"],d:["1st round interviewer"],e:["full name"],f:["qualify"],g:["reasons"],h:["answer call"],i:["booked to 2nd rd"],j:["date 2nd rd"],k:["showed up to 2nd round"],l:["offered positon","offered position"],m:["bob"],n:["ad title"],p:["star rating"]};
let IMP=[];
function xDate(v){
  if(v==null||v==="") return "";
  if(typeof v==="number"){ if(v<20000||v>80000) return ""; return iso(new Date(Math.round((v-25569)*864e5))); }
  const s=String(v).trim(); let m=s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})/); if(m) return `${m[1]}-${m[2].padStart(2,"0")}-${m[3].padStart(2,"0")}`;
  m=s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{2,4})$/); if(m){ const y=m[3].length===2?"20"+m[3]:m[3]; return `${y}-${m[1].padStart(2,"0")}-${m[2].padStart(2,"0")}`; }
  return "";
}
function parseSheet(X,ws){
  const rows=X.utils.sheet_to_json(ws,{header:1,raw:true,blankrows:false,defval:""});
  for(let hr=0;hr<Math.min(rows.length,5);hr++){
    const head=(rows[hr]||[]).slice(0,40).map(x=>low(String(x).replace(/\s+/g," ")));
    const col={}; for(const f in HDR){ const i=head.findIndex(x=>HDR[f].includes(x)); if(i>=0) col[f]=i; }
    if(col.b==null||col.e==null||col.f==null) continue;
    const out=[]; const owners={};
    for(const r of rows.slice(hr+1)){
      const s=f=>col[f]==null?"":String(r[col[f]]??"").replace(/\u00a0/g," ").trim();
      const e=s("e"); if(!e) continue;
      const row={b:xDate(r[col.b]),d:s("d"),e,f:s("f"),g:s("g"),h:s("h"),i:s("i"),j:col.j==null?"":xDate(r[col.j]),k:s("k"),l:s("l"),m:s("m"),n:s("n"),p:s("p")};
      out.push(row); const o=String(r[0]??"").trim(); if(o) owners[o]=(owners[o]||0)+1;
    }
    const owner=Object.entries(owners).sort((a,b)=>b[1]-a[1])[0]; return {rows:out, owner:owner?owner[0]:""};
  }
  return null;
}
function guessOffice(sheet,owner){
  const cands=[sheet,owner].filter(Boolean).map(slug);
  const hit=S.offices.find(o=>cands.includes(o.id)||cands.includes(slug(o.name)));
  return hit?hit.id:"new:"+(/^sheet\d*$/i.test(sheet)&&owner?owner:sheet);
}
function renderImpList(){
  const opts=sel=>S.offices.map(o=>`<option value="${o.id}" ${o.id===sel?"selected":""}>${esc(o.name)}</option>`).join("");
  $("#impList").innerHTML=IMP.length?`<table class="rpt" style="width:100%"><thead><tr class="sub"><th></th><th class="l">File \u203a tab</th><th>Interviews</th><th>Dates</th><th class="l">Load into office</th></tr></thead><tbody>${IMP.map((t,i)=>{
    const ds=t.rows.map(r=>r.b).filter(Boolean).sort(); const isNew=t.office.startsWith("new:");
    return `<tr><td><input type="checkbox" data-imp="${i}" ${t.on?"checked":""} aria-label="Import this tab"></td><td class="l">${esc(t.file)} \u203a <b>${esc(t.sheet)}</b></td><td>${t.rows.length.toLocaleString("en-US")}</td><td>${ds.length?md(ds[0])+" \u2013 "+md(ds[ds.length-1]):"\u2013"}</td>
    <td class="l"><select data-impo="${i}"><option value="new:${esc(isNew?t.office.slice(4):t.sheet)}" ${isNew?"selected":""}>+ New office: ${esc(isNew?t.office.slice(4):t.sheet)}</option>${opts(t.office)}</select></td></tr>`;}).join("")}</tbody></table>`:"";
  $("#impMode").style.display=IMP.length?"flex":"none";
  $("#mGo").disabled=!IMP.some(t=>t.on);
}
$("#impFiles").onchange=async e=>{
  const files=[...e.target.files]; if(!files.length) return; const msg=$("#impMsg");
  try{
    msg.textContent="Loading the Excel reader\u2026"; const X=await loadXLSX();
    for(const f of files){
      msg.textContent=`Reading ${f.name}\u2026`; await sleep(30);
      const wb=X.read(await f.arrayBuffer(),{type:"array",cellFormula:false,cellHTML:false,cellText:false,cellStyles:false,cellNF:false});
      for(const name of wb.SheetNames){ const r=parseSheet(X,wb.Sheets[name]); if(r&&r.rows.length) IMP.push({file:f.name,sheet:name,rows:r.rows,owner:r.owner,office:guessOffice(name,r.owner),on:true}); }
    }
    msg.textContent=IMP.length?`Found ${IMP.length} tab(s) with interviews. Check the office for each one, then click Import.`:"No tab with the Data Entry columns was found. The first rows must include Date 1st Rd, Full Name and Qualify.";
  }catch(err){ msg.textContent="Couldn't read the file: "+(err.message||err); }
  e.target.value=""; renderImpList();
};
document.addEventListener("change",e=>{
  const c=e.target.closest("[data-imp]"); if(c){ IMP[+c.dataset.imp].on=c.checked; $("#mGo").disabled=!IMP.some(t=>t.on); }
  const o=e.target.closest("[data-impo]"); if(o){ IMP[+o.dataset.impo].office=o.value; }
});
const rowKey=r=>[r.b||"",low(r.e),low(r.d)].join("|");
async function writeWithRetry(fn){ for(let a=0;a<4;a++){ try{ return await fn(); }catch(e){ if(e.code==="resource_exhausted"||e.code==="unavailable"){ await sleep(1500*(a+1)); continue; } throw e; } } }
async function runFileImport(){
  const go=$("#mGo"); go.disabled=true; const fill=$("#progFill"), txt=$("#progTxt");
  const mode=(document.querySelector('input[name=impMode]:checked')||{}).value||"add";
  const jobs=IMP.filter(t=>t.on); let added=0, skipped=0;
  try{
    const byOffice=new Map();
    for(const t of jobs){
      let id=t.office, name;
      if(id.startsWith("new:")){ name=id.slice(4); id=slug(name); } else name=(S.offices.find(o=>o.id===id)||{}).name||id;
      const g=byOffice.get(id)||byOffice.set(id,{name,rows:[]}).get(id); g.rows.push(...t.rows);
    }
    const total=[...byOffice.values()].reduce((s,g)=>s+g.rows.length,0)||1; let done=0;
    for(const [oid,g] of byOffice){
      txt.textContent=`Importing ${g.name}\u2026`;
      for(let i=0;i<g.rows.length||i===0;i+=800){
        const chunk=g.rows.slice(i,i+800).map(r=>FIELDS.map(f=>r[f]||""));
        const res=await api("importRows",oid,g.name,chunk,mode,i===0);
        added+=res.added; skipped+=res.skipped; done+=chunk.length; fill.style.width=(done/total*100)+"%";
        if(!g.rows.length) break;
      }
    }
    txt.textContent=`Done: ${added.toLocaleString("en-US")} interviews added`+(skipped?`, ${skipped.toLocaleString("en-US")} skipped because they were already loaded`:"")+".";
    IMP=[]; renderImpList(); $("#impMsg").textContent="";
    const b=await api("bootstrap"); S.offices=b.offices.slice().sort((a,c)=>a.name.localeCompare(c.name));
    if(S.office) loadRows(true); else if(S.offices.length) setOffice(S.offices[0].id); render();
  }catch(e){ txt.textContent="The import stopped: "+e.message+". Interviews written before the error are saved; importing again in Add mode skips them."; }
  go.disabled=!IMP.some(t=>t.on);
}

// ---------- events ----------
document.addEventListener("click",e=>{
  const t=e.target.closest("[data-tab]"); if(t){ S.tab=t.dataset.tab; try{localStorage.setItem("ars.tab",S.tab);}catch(x){} try{ history.replaceState(null,"","#"+S.tab); }catch(x){} render(); return; }
  const a=e.target.closest("[data-act]"); if(a){ const v=a.dataset.act; if(v==="import") openM("#mImport"); if(v==="office") openM("#mOffice"); if(v==="entry"){S.tab="entrada";render();} if(v==="ints"){ $("#intsTxt").value=S.ints.join("\n"); $("#intsMsg").textContent=""; openM("#mInts"); setTimeout(()=>$("#intsTxt").focus(),0);} return; }
  const del=e.target.closest("[data-del]"); if(del){
    if(!del.classList.contains("arm")){ document.querySelectorAll(".del.arm").forEach(x=>{x.classList.remove("arm");x.textContent="Delete";}); del.classList.add("arm"); del.textContent="Sure?"; return; }
    return; }
  if(e.target.id==="addGo") return addRow();
  if(e.target.id==="toggleDays"){ S.hideDays=!S.hideDays; try{localStorage.setItem("ars.hideDays",S.hideDays?"1":"");}catch(x){} return render(); }
  if(e.target.id==="eD2x"){ S.ent.d2=""; S.ent.page=0; return render(); }
  const so=e.target.closest("[data-sort]"); if(so){ S.st.sort=so.dataset.sort; return render(); }
  const aw=e.target.closest("[data-adwsort]"); if(aw){ S.ads.wsort=aw.dataset.adwsort; return render(); }
  const av=e.target.closest("[data-adview]"); if(av){ S.ads.view=av.dataset.adview; try{localStorage.setItem("ars.adview",S.ads.view);}catch(x){} return render(); }
  const ws=e.target.closest("[data-wsort]"); if(ws){ S.st.wsort=ws.dataset.wsort; return render(); }
  const sv=e.target.closest("[data-stview]"); if(sv){ S.st.view=sv.dataset.stview; try{localStorage.setItem("ars.stview",S.st.view);}catch(x){} return render(); }
  if(e.target.id==="pPrev"){S.ent.page--;render();} if(e.target.id==="pNext"){S.ent.page++;render();}
});
function addRow(){
  const g=id=>$("#"+id).value.trim();
  const r={id:rid(),t:Date.now(),b:g("nb"),d:g("nd"),e:g("ne"),f:g("nf"),g:g("ng"),h:g("nh"),i:g("ni"),j:g("nj"),k:g("nk"),l:g("nl"),m:g("nm"),n:g("nn"),p:g("np")};
  for(const f of naFields(r)) r[f]="";
  if(!r.e){ status("Enter the candidate's name",true); $("#ne").focus(); return; }
  if(!r.b){ status("Add the 1st round date",true); $("#nb").focus(); return; }
  S.lastAdd={b:r.b,d:r.d,n:r.n};
  r.wk=r.b?monday(r.b):"sin-fecha"; S.rows.push(r); buildIndex(); render(); writeRow(r,null);
  setTimeout(()=>{const n=$("#ne"); n&&n.focus();},0);
}
document.addEventListener("change",e=>{
  const el=e.target;
  if(el.id==="office") return setOffice(el.value);
  if(el.id==="week"){ S.week=el.value; return render(); }
  if(el.id==="goal"){ S.goal=+el.value; try{localStorage.setItem("ars.goal",el.value);}catch(x){} return render(); }
  if(el.id==="eMonth"){S.ent.month=el.value;S.ent.page=0;return render();}
  if(el.id==="eD2"){S.ent.d2=el.value;S.ent.page=0;return render();}
  if(el.id==="eCity"){S.ent.city=el.value;S.ent.page=0;return render();}
  if(el.id==="eWho"){S.ent.who=el.value;S.ent.page=0;return render();}
  if(el.id==="adMonth"){S.ads.month=el.value;return render();}
  if(el.id==="stMonth"){S.st.month=el.value;return render();}
  if(el.id==="stMin"){S.st.min=+el.value;return render();}
  if(el.id==="stWMin"){S.st.wmin=+el.value;return render();}
  const ar=el.closest("#addRow"); if(ar) applyNA(ar);
  const tr=el.closest("tr[data-id]"); if(tr && el.dataset.f){ applyNA(tr);
    const r=S.rows.find(x=>x.id===tr.dataset.id); if(!r) return;
    const v=el.value.trim(); if((r[el.dataset.f]||"")===v) return;
    const oldWk=r.wk; r[el.dataset.f]=v; if(el.dataset.f==="b"){ r.wk=r.b?monday(r.b):"sin-fecha"; }
    writeRow(r,oldWk);
    if(el.dataset.f==="n"){ const c=tr.children[14]; if(c) c.textContent=city(v); }
    if(el.dataset.f==="b"){ const c=tr.children[2]; if(c) c.textContent=monthLabel(v); }
  }
});
let qT; document.addEventListener("input",e=>{
  if(e.target.id==="eQ"){ clearTimeout(qT); qT=setTimeout(()=>{S.ent.q=e.target.value;S.ent.page=0;render();const x=$("#eQ");x.focus();x.setSelectionRange(x.value.length,x.value.length);},250); }
  if(e.target.id==="adQ"){ clearTimeout(qT); qT=setTimeout(()=>{S.ads.q=e.target.value;render();const x=$("#adQ");x.focus();x.setSelectionRange(x.value.length,x.value.length);},250); }
});
document.addEventListener("keydown",e=>{ if(e.key==="Enter" && e.target.closest && e.target.closest("#addRow")){ e.preventDefault(); addRow(); } });
document.addEventListener("focusout",()=>{ setTimeout(()=>{ if(S.pendingRender && !(document.activeElement&&document.activeElement.closest&&document.activeElement.closest("tr[data-id],#addRow"))){ S.pendingRender=false; render(); } },50); });
$("#wPrev").onclick=()=>{const ws=IDX.weeks,i=ws.indexOf(S.week); if(i<ws.length-1){S.week=ws[i+1];render();}};
$("#wNext").onclick=()=>{const ws=IDX.weeks,i=ws.indexOf(S.week); if(i>0){S.week=ws[i-1];render();}};
function openM(s){ $(s).classList.add("on"); if(s==="#mOffice") setTimeout(()=>$("#newOffice").focus(),0); }
$("#importBtn").onclick=()=>openM("#mImport"); $("#addOffice").onclick=()=>openM("#mOffice");
$("#mCancel").onclick=()=>$("#mImport").classList.remove("on");
$("#oCancel").onclick=()=>$("#mOffice").classList.remove("on");
$("#mGo").onclick=()=>runFileImport();
function loadXLSX(){ return window.XLSX?Promise.resolve(window.XLSX):new Promise((ok,no)=>{const s=document.createElement("script");s.src="https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js";s.onload=()=>ok(window.XLSX);s.onerror=()=>no(new Error("couldn't load the Excel reader"));document.head.appendChild(s);}); }
$("#intsFile").onchange=async(e)=>{
  const f=e.target.files[0]; if(!f) return; const msg=$("#intsMsg"); msg.textContent="Reading "+f.name+"\u2026";
  try{
    const X=await loadXLSX(); const wb=X.read(await f.arrayBuffer(),{type:"array"});
    const rows=X.utils.sheet_to_json(wb.Sheets[wb.SheetNames[0]],{header:1,raw:false,blankrows:false});
    if(!rows.length) throw new Error("the first sheet is empty");
    // pick the column whose header mentions interviewer/name, else the first non-empty column
    const head=(rows[0]||[]).map(x=>low(x));
    let col=head.findIndex(x=>/interviewer|entrevistador/.test(x)); if(col<0) col=head.findIndex(x=>/^(name|names|nombre|nombres|full name)$/.test(x));
    let start=col>=0?1:0; if(col<0){ col=Math.max(0,(rows[0]||[]).findIndex(x=>String(x??"").trim()!=="")); }
    const names=rows.slice(start).map(r=>String((r||[])[col]??"").trim()).filter(Boolean);
    if(!names.length) throw new Error("no names found in the first column");
    $("#intsTxt").value=names.join("\n");
    msg.textContent=`Loaded ${names.length} names from ${f.name}. Review them and click Save list.`;
  }catch(err){ msg.textContent="Couldn't read the file: "+(err.message||err); }
  e.target.value="";
};
function renderManage(){
  $("#manageList").innerHTML=S.offices.map(o=>`<div style="display:flex;gap:8px;align-items:center;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--line)"><span>${esc(o.name)}</span>
    <span style="display:flex;gap:6px;align-items:center"><input type="text" data-confirm="${o.id}" placeholder="Type the office name to confirm" style="width:230px"><button class="btn" data-delof="${o.id}" disabled style="color:var(--bad)">Delete office</button></span></div>`).join("")||"<p>No offices.</p>";
}
document.addEventListener("input",e=>{ const c=e.target.closest("[data-confirm]"); if(!c) return; const o=S.offices.find(x=>x.id===c.dataset.confirm); const b=document.querySelector(`[data-delof="${c.dataset.confirm}"]`); if(o&&b) b.disabled=c.value.trim().toLowerCase()!==o.name.trim().toLowerCase(); });
document.addEventListener("click",async e=>{
  const b=e.target.closest("[data-delof]"); if(!b||b.disabled) return;
  const id=b.dataset.delof, o=S.offices.find(x=>x.id===id); if(!o) return; const msg=$("#manageMsg");
  b.disabled=true; msg.textContent=`Deleting ${o.name}\u2026`;
  try{
    S.offices=(await api("deleteOffice",id)).slice().sort((a,c)=>a.name.localeCompare(c.name)); renderManage();
    if(S.office&&S.office.id===id){ if(S.offices.length) setOffice(S.offices[0].id); else { S.office=null; S.rows=[]; buildIndex(); render(); } } else render();
    msg.textContent=`${o.name} was deleted.`;
  }catch(err){ msg.textContent="Couldn't delete it: "+(err.message||err.code)+". Try again."; b.disabled=false; }
});
$("#manageOffices").onclick=()=>{ $("#manageMsg").textContent=""; renderManage(); openM("#mManage"); };
$("#manageClose").onclick=()=>$("#mManage").classList.remove("on");
$("#iCancel").onclick=()=>$("#mInts").classList.remove("on");
$("#iGo").onclick=async()=>{
  const seen=new Set(), list=[];
  for(const line of $("#intsTxt").value.split(/\r?\n|,|\t/)){ const n=line.trim().replace(/\s+/g," "); if(n && !seen.has(low(n))){ seen.add(low(n)); list.push(n); } }
  list.sort((a,b)=>a.localeCompare(b));
  try{ await api("saveInterviewers",list); S.ints=list; $("#mInts").classList.remove("on"); status(`Saved ${list.length} interviewers`); render(); }
  catch(e){ status("Couldn't save the list: "+e.message,true); }
};
$("#oGo").onclick=async()=>{
  const n=$("#newOffice").value.trim(); if(!n) return;
  try{ const res=await api("addOffice",n); S.offices=res.offices.slice().sort((a,c)=>a.name.localeCompare(c.name));
    $("#mOffice").classList.remove("on"); $("#newOffice").value=""; setOffice(res.id); }
  catch(e){ status("Couldn't create: "+e.message,true); }
};

// ---------- users & sign-in ----------
function renderUsers(){
  const U=S.users||[], me=S.user||{};
  const row=u=>`<tr data-user="${esc(u.username)}"><td class="name">${esc(u.name)}</td><td class="l">${esc(u.username)}</td>
    <td><select data-urole aria-label="Role" ${u.username===me.username?"disabled":""}><option value="interviewer" ${u.role==="interviewer"?"selected":""}>Interviewer</option><option value="admin" ${u.role==="admin"?"selected":""}>Admin</option></select></td>
    <td><span class="pill ${u.active?"ok":"bad"}">${u.active?"Active":"Disabled"}</span></td>
    <td class="l">${u.lastLogin?esc(new Date(u.lastLogin).toLocaleString("en-US",{month:"short",day:"numeric",hour:"numeric",minute:"2-digit"})):"Never"}</td>
    <td class="l" style="white-space:nowrap"><button class="btn" data-ureset>Reset password</button> ${u.username===me.username?"":`<button class="btn" data-uactive>${u.active?"Disable":"Enable"}</button> <button class="btn" data-udel style="color:var(--bad)">Delete</button>`}</td></tr>`;
  return `<div class="head"><h2>Users</h2><p>Each person signs in with their own username and password. Interviewers enter and edit interviews; Admins can also manage users, offices, imports and the interviewer list.</p></div>
  <div class="card" style="padding:10px 12px;display:flex;flex-direction:column;gap:8px;max-width:1000px">
    <h2 style="font-size:13px">Create a user</h2>
    <div class="filters">
      <div class="ctl"><label for="nuName">Full name</label><input type="text" id="nuName" placeholder="e.g. Perla Gómez"></div>
      <div class="ctl"><label for="nuUser">Username</label><input type="text" id="nuUser" placeholder="e.g. perla" autocomplete="off" autocapitalize="off"></div>
      <div class="ctl"><label for="nuRole">Role</label><select id="nuRole"><option value="interviewer">Interviewer</option><option value="admin">Admin</option></select></div>
      <div class="ctl"><label for="nuPass">Password</label><div style="display:flex;gap:4px"><input type="text" id="nuPass" autocomplete="off" style="width:150px"><button class="btn" id="nuGen" title="Generate a password">Generate</button></div></div>
      <button class="btn primary" id="nuGo">Create user</button>
    </div>
    <p id="nuMsg" style="margin:0;font-size:12.5px;color:var(--muted)">Usernames: letters, numbers, dots, dashes or underscores. Passwords need at least 8 characters.</p>
  </div>
  <p id="uMsg" style="margin:0;font-size:13px;font-weight:600"></p>
  <div class="card scroll pal-k"><table class="rpt"><thead><tr class="sub"><th class="name">Name</th><th class="l">Username</th><th>Role</th><th>Status</th><th class="l">Last sign-in</th><th class="l"></th></tr></thead>
  <tbody>${S.users?(U.length?U.map(row).join(""):`<tr><td colspan="6" class="l" style="color:var(--muted)">No users yet.</td></tr>`):`<tr><td colspan="6" class="l" style="color:var(--muted)">Loading users…</td></tr>`}</tbody></table></div>`;
}
function genPass(){ const a="abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"; let s=""; const r=new Uint32Array(10); crypto.getRandomValues(r); r.forEach(x=>s+=a[x%a.length]); return s; }
async function loadUsers(){ try{ S.users=await api("listUsers"); if(S.tab==="users") render(); }catch(e){ status("Couldn't load users: "+e.message,true); } }
function uMsg(t,err){ S.uMsg={t,err}; const m=$("#uMsg"); if(m){ m.textContent=t; m.style.color=err?"var(--bad)":"var(--good)"; } }
function rerenderUsers(){ const keep=S.uMsg; render(); if(keep) uMsg(keep.t,keep.err); }
document.addEventListener("click",async e=>{
  if(e.target.id==="nuGen"){ $("#nuPass").value=genPass(); return; }
  if(e.target.id==="nuGo"){
    const u={name:$("#nuName").value.trim(),username:$("#nuUser").value.trim().toLowerCase(),role:$("#nuRole").value,password:$("#nuPass").value,active:true,isNew:true};
    const m=$("#nuMsg");
    if(!u.name||!u.username||!u.password){ m.textContent="Fill in name, username and password."; m.style.color="var(--bad)"; return; }
    e.target.disabled=true;
    try{ S.users=await api("saveUser",u); S.uMsg={t:`Created ${u.username}. Send them their login: username "${u.username}", password "${u.password}". The password is shown only now.`}; rerenderUsers(); }
    catch(err){ m.textContent=err.message; m.style.color="var(--bad)"; e.target.disabled=false; }
    return;
  }
  const tr=e.target.closest("tr[data-user]"); if(!tr) return; const un=tr.dataset.user; const u=(S.users||[]).find(x=>x.username===un); if(!u) return;
  try{
    if(e.target.matches("[data-ureset]")){ const p=genPass(); S.users=await api("saveUser",{username:un,password:p}); S.uMsg={t:`New password for ${un}: ${p}  (send it to them; it is shown only now)`}; rerenderUsers(); }
    else if(e.target.matches("[data-uactive]")){ S.users=await api("saveUser",{username:un,active:!u.active}); S.uMsg={t:`${un} is now ${u.active?"disabled and can't sign in":"active"}.`}; rerenderUsers(); }
    else if(e.target.matches("[data-udel]")){
      if(!e.target.classList.contains("arm")){ e.target.classList.add("arm"); e.target.textContent="Click again to delete"; return; }
      S.users=await api("deleteUser",un); S.uMsg={t:`Deleted ${un}.`}; rerenderUsers();
    }
  }catch(err){ uMsg(err.message,true); }
});
document.addEventListener("change",async e=>{
  if(!e.target.matches("[data-urole]")) return; const un=e.target.closest("tr").dataset.user;
  try{ S.users=await api("saveUser",{username:un,role:e.target.value}); uMsg(`${un} is now ${e.target.value==="admin"?"an Admin":"an Interviewer"}.`); }
  catch(err){ uMsg(err.message,true); }
});

// sign-in screen
function showGate(mode,msg){
  const g=$("#gate"); g.hidden=false; document.body.classList.add("gated");
  const setup=mode==="setup";
  g.innerHTML=`<form class="card gatecard" id="gateForm" autocomplete="on">
    <h1>ARS Interview Tracker</h1>
    <p>${setup?"Create the first Admin account. You'll use it to create everyone else's logins.":"Sign in with the username and password your Admin gave you."}</p>
    ${setup?`<div class="ctl"><label for="gName">Full name</label><input type="text" id="gName" required></div>`:""}
    <div class="ctl"><label for="gUser">Username</label><input type="text" id="gUser" autocomplete="username" autocapitalize="off" required></div>
    <div class="ctl"><label for="gPass">Password${setup?" (8+ characters)":""}</label><input type="password" id="gPass" autocomplete="${setup?"new-password":"current-password"}" required></div>
    <p id="gMsg" class="gmsg">${msg?esc(msg):""}</p>
    <button class="btn primary" type="submit" id="gGo">${setup?"Create Admin and sign in":"Sign in"}</button>
  </form>`;
  setTimeout(()=>{ const f=$(setup?"#gName":"#gUser"); f&&f.focus(); },0);
  $("#gateForm").onsubmit=async ev=>{
    ev.preventDefault(); const b=$("#gGo"); b.disabled=true; $("#gMsg").textContent="";
    try{
      const un=$("#gUser").value.trim().toLowerCase(), pw=$("#gPass").value;
      const r=setup?await rawApi("setupAdmin",$("#gName").value.trim(),un,pw):await rawApi("login",un,pw);
      S.token=r.token; try{ localStorage.setItem("ars.token",r.token); }catch(x){}
      g.hidden=true; document.body.classList.remove("gated"); startApp();
    }catch(err){ $("#gMsg").textContent=err.message.replace(/^.*AUTH:\s*/,""); b.disabled=false; }
  };
}
function signOut(expired){
  if(S.token) rawApi("logout",S.token).catch(()=>{});
  S.token=null; S.user=null; S.role=null; try{ localStorage.removeItem("ars.token"); }catch(x){}
  S.offices=[]; S.office=null; S.rows=[]; S.users=null; S.uMsg=null; buildIndex(); renderUserChip();
  showGate("login",expired?"Your session ended. Please sign in again.":"");
}
function renderUserChip(){
  const u=S.user; const el=$("#userChip"); if(!el) return;
  el.innerHTML=u?`<span><b>${esc(u.name)}</b> · ${u.role==="admin"?"Admin":"Interviewer"}</span><button class="btn" id="chgPass">Change password</button><button class="btn" id="signOut">Sign out</button>`:"";
}
document.addEventListener("click",async e=>{
  if(e.target.id==="signOut") return signOut(false);
  if(e.target.id==="chgPass"){ $("#cpOld").value=""; $("#cpNew").value=""; $("#cpMsg").textContent=""; openM("#mPass"); setTimeout(()=>$("#cpOld").focus(),0); }
  if(e.target.id==="cpCancel") $("#mPass").classList.remove("on");
  if(e.target.id==="cpGo"){
    try{ await api("changePassword",$("#cpOld").value,$("#cpNew").value); $("#cpMsg").textContent="Password changed."; $("#cpMsg").style.color="var(--good)"; setTimeout(()=>$("#mPass").classList.remove("on"),900); }
    catch(err){ $("#cpMsg").textContent=err.message; $("#cpMsg").style.color="var(--bad)"; }
  }
});

// ---------- boot ----------
async function startApp(){
  render();
  try{
    const b=await api("bootstrap");
    S.user=b.user; S.role=b.user.role; S.canWrite=true; S.ints=b.ints||[]; S.adMap=b.adMap||{};
    renderUserChip();
    S.offices=(b.offices||[]).slice().sort((a,c)=>a.name.localeCompare(c.name));
    let want=null; try{ want=localStorage.getItem("ars.office"); }catch(e){}
    if(S.offices.length) setOffice(S.offices.some(o=>o.id===want)?want:S.offices[0].id); else { S.loaded=true; render(); }
    if(S.role==="admin") loadUsers();
  }catch(e){ if(!/AUTH:/.test(e.message)){ S.loaded=true; status("Couldn't load: "+e.message,true); render(); } }
}
(async()=>{
  try{ S.token=localStorage.getItem("ars.token"); }catch(e){}
  try{
    if(await rawApi("needsSetup")) return showGate("setup");
    if(!S.token) return showGate("login");
    startApp();
  }catch(e){ showGate("login",e.message); }
})();
