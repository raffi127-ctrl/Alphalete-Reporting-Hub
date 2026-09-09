"""A button that fills the Apex form the person already has open.

WHY IT IS SHAPED LIKE THIS. Apex will only accept writes from a browser that is
already signed in, and this report cannot get one: a fresh sign-in on that
account ends on the change-password screen. The person's OWN browser is signed
in, so the filling has to happen in there.

A helper on the machine can't be reached either -- Chrome silently blocks a page
on apex.herbjoyent.com from calling 127.0.0.1 (tested 2026-09-09: the local
server never saw the request, no error, no console message). So the data can't
be fetched; it has to travel INSIDE the button.

Hence a bookmarklet. Drag it up once per computer, then on any Apex page:

    click it -> it fills whatever belongs to THAT page -> you check and Save

It is page-aware on purpose, because a new start spans three screens (Add Roster
Employee, User Profile & Account, Tax & Bank Information). One button that fills
"whatever is in front of you" is one thing to learn instead of three.

ON THE TAX SCREEN it also offers to open that person's own Blue Ink packet in a
second tab, so the Social can be read off their signed I-9 beside the box it
goes in, instead of hunted for. That link is Blue Ink's dashboard filtered by
their SURNAME -- deliberately not a link to the document itself. A signed
document URL embedded here would be a link to somebody's SSN sitting in a
bookmarks bar, which would undo the whole point of the paragraph below.

THE SOCIAL NEVER LEAVES THE PAGE. It is not in the button, not in this file, not
in the run's output. On the tax screen the panel shows two boxes; the person
types it there and it goes straight into Apex's own fields, in their browser.

Every value is matched to a box by the LABEL a person reads, the same rule the
Python side uses -- exact first, then contains, and never a checkbox or radio.
"""
from __future__ import annotations

import json
from typing import Dict, List

# semantic name -> the label as it reads on the Apex screen. Python does the
# mapping so the button stays dumb: it only ever looks for a label it is handed.
LABEL_FOR = {
    "first": "First Name", "middle": "Middle Name", "last": "Last Name",
    "username": "User Name", "account_email": "Account Email",
    "hire_date": "Hire Date", "pay_frequency": "Pay Frequency",
    "position": "Position", "rate": "Rate of Pay",
    "pay_state": "State Working In", "pay_basis": "Basis of Pay",
    "department": "Department",
    "dob": "Date of Birth", "gender": "Gender",
    "address1": "Street Address", "apt": "Apt/PO Box",
    "address2": "Street Address 2", "city": "City", "state": "State",
    "zip": "Zip Code", "home_phone": "Home Phone",
    "mobile_phone": "Mobile Phone",
    "claim_dependents": "Claim Dependents",
    "marital_status": "Marital Status",
    "tax_state": "State to be taxed in",
}

# Radio group, not a text box -- set separately by the button.
SECURITY_ROLE_LABEL = "Sales Rep"

_JS = r"""
(function(){
 var D=%(data)s, KEY='apexNewStarts.%(week)s';
 var I=0; try{ I=parseInt(localStorage.getItem(KEY)||'0',10)||0; }catch(e){}
 if(I>=D.length){ alert('All '+D.length+' done for %(week)s.\nTo start again, click this and choose Reset.'); }
 function norm(t){ return (t||'').replace(/\*/g,'').replace(/\s+/g,' ').trim().toLowerCase(); }
 function vis(el){ var r=el.getBoundingClientRect(); return r.width>0&&r.height>0&&!el.disabled&&!el.hasAttribute('readonly'); }
 var BAD={checkbox:1,radio:1,button:1,submit:1,reset:1,hidden:1,file:1,image:1};
 function nearInput(node){
   /* the box that belongs to a caption which is not a <label>: look inside the
      caption's own container, then its parent, then its grandparent. Apex's
      Employment Record writes 'Position *' as plain text beside a <select>,
      which the <label> passes cannot see at all. */
   var n=node, depth=0, f;
   while(n && depth<3){
     f=n.querySelector?n.querySelector('input,select,textarea'):null;
     if(f&&vis(f)&&!(f.tagName==='INPUT'&&BAD[(f.type||'').toLowerCase()])) return f;
     var sib=n.nextElementSibling, hops=0;
     while(sib&&hops<3){
       f=sib.matches&&sib.matches('input,select,textarea')?sib:(sib.querySelector?sib.querySelector('input,select,textarea'):null);
       if(f&&vis(f)&&!(f.tagName==='INPUT'&&BAD[(f.type||'').toLowerCase()])) return f;
       sib=sib.nextElementSibling; hops++;
     }
     n=n.parentElement; depth++;
   }
   return null;
 }
 function fieldFor(label){
   var want=norm(label), pass, i, labs=document.querySelectorAll('label'), out=[];
   for(pass=0;pass<2;pass++){
     out=[];
     for(i=0;i<labs.length;i++){
       var t=norm(labs[i].innerText); if(!t) continue;
       var hit = pass===0 ? (t===want) : (t.indexOf(want)>=0);
       if(!hit) continue;
       var f=labs[i].htmlFor?document.getElementById(labs[i].htmlFor):null;
       if(!f) f=labs[i].querySelector('input,select,textarea');
       if(!f){ var n=labs[i].nextElementSibling;
         for(var k=0;k<3&&n;k++,n=n.nextElementSibling){
           var c=n.matches&&n.matches('input,select,textarea')?n:(n.querySelector?n.querySelector('input,select,textarea'):null);
           if(c){ f=c; break; } } }
       if(f && vis(f) && !(f.tagName==='INPUT'&&BAD[(f.type||'').toLowerCase()])) out.push(f);
     }
     if(out.length===1) return out[0];
   }
   var all=document.querySelectorAll('div,span,td,th,p,legend,strong,b'), cands=[];
   for(i=0;i<all.length;i++){
     if(all[i].children.length>2) continue;
     if(norm(all[i].textContent)!==want) continue;
     var f=nearInput(all[i]);
     if(f&&cands.indexOf(f)<0) cands.push(f);
   }
   if(cands.length===1) return cands[0];
   return null;
 }
 function setVal(el,v){
   if(el.tagName==='SELECT'){
     var o=el.options,w=norm(v),i,pick=null;
     for(i=0;i<o.length;i++){ if(norm(o[i].text)===w){pick=o[i];break;} }
     if(!pick) for(i=0;i<o.length;i++){ var t=norm(o[i].text); if(t&&(t.indexOf(w)===0||w.indexOf(t)===0)){pick=o[i];break;} }
     if(!pick) for(i=0;i<o.length;i++){ var t2=norm(o[i].text); if(t2&&(t2.indexOf(w)>=0||w.indexOf(t2)>=0)){pick=o[i];break;} }
     if(!pick) return false;
     el.value=pick.value;
   } else { el.value=v; }
   el.dispatchEvent(new Event('input',{bubbles:true}));
   el.dispatchEvent(new Event('change',{bubbles:true}));
   return true;
 }
 function role(){
   var rs=document.querySelectorAll('input[type=radio]'),i;
   for(i=0;i<rs.length;i++){
     var lab=rs[i].closest('label')||(rs[i].id?document.querySelector('label[for="'+rs[i].id+'"]'):null);
     if(lab&&norm(lab.innerText)===%(role)s){ rs[i].click(); return true; }
   }
   return false;
 }
 function fill(p){
   var done=[],miss=[],k;
   for(k in p.fields){ var el=fieldFor(k);
     if(el){ if(setVal(el,p.fields[k])) done.push(k); else miss.push(k+' (no matching option)'); }
     else miss.push(k); }
   if(role()) done.push('Sales Rep role');
   return {done:done,miss:miss};
 }
 function ssnBoxes(){ var a=fieldFor('Change SSN'), b=fieldFor('Confirm SSN'); return (a&&b)?[a,b]:null; }
 function blueink(p){ return 'https://secure.blueink.com/dashboard/wall?search='+encodeURIComponent(p.find||p.name); }
 var old=document.getElementById('anspanel'); if(old) old.remove();
 var p=D[Math.min(I,D.length-1)];
 var box=document.createElement('div'); box.id='anspanel';
 box.style.cssText='position:fixed;top:14px;right:14px;z-index:2147483647;background:#fff;border:2px solid #0F766E;border-radius:10px;padding:14px 16px;font:14px -apple-system,Helvetica,sans-serif;box-shadow:0 6px 24px rgba(0,0,0,.25);max-width:330px';
 var ssn=ssnBoxes();
 box.innerHTML='<div style="font-weight:700;font-size:16px">'+p.name+'</div>'+
   '<div style="color:#555;margin:2px 0 10px">'+(I+1)+' of '+D.length+' · %(week)s</div>'+
   (ssn?'<div style="margin-bottom:8px"><div style="font-size:12px;color:#555">Social Security number</div>'+
        '<input id="ansssn" type="password" style="width:100%%;padding:6px;font-size:15px">'+
        '<div style="margin-top:6px"><a href="'+blueink(p)+'" target="_blank" rel="noopener" id="ansbi" style="font-size:12px;color:#0F766E">Open their Blue Ink packet →</a>'+
        '<span style="font-size:11px;color:#888"> (I-9 → Quick View)</span></div></div>':'')+
   '<button id="ansfill" style="background:#0F766E;color:#fff;border:0;border-radius:6px;padding:8px 14px;font-size:14px;cursor:pointer">Fill this page</button> '+
   '<button id="ansnext" style="background:#eee;border:0;border-radius:6px;padding:8px 12px;cursor:pointer">Saved → next</button>'+
   '<div id="ansout" style="margin-top:9px;font-size:12px;color:#333"></div>'+
   '<div style="margin-top:8px"><a href="#" id="ansreset" style="font-size:11px;color:#888">start the week again</a></div>';
 document.body.appendChild(box);
 document.getElementById('ansfill').onclick=function(){
   var r=fill(p);
   /* Nothing matched at all = not an Apex form. Saying so beats a wall of red
      listing every field the page was never going to have, which is what it
      did the first time somebody clicked it on the wrong tab. NOTE: block
      comments only in here -- build_js collapses this to ONE line, so a
      line comment would swallow the entire rest of the script. */
   if(!r.done.length && !ssnBoxes()){
     document.getElementById('ansout').innerHTML=
       '<b>This isn\'t an Apex form.</b><br>Open <b>Roster → Employees → '+
       '+ Add Employee</b> in Apex, then click the button there.';
     return;
   }
   var msg='Filled: '+(r.done.join(', ')||'nothing on this page');
   var s=document.getElementById('ansssn');
   if(s&&s.value){ var b=ssnBoxes(); if(b){ setVal(b[0],s.value); setVal(b[1],s.value); s.value=''; msg+='; Social entered'; } }
   if(r.miss.length) msg+='<br><span style="color:#b00">Not found here: '+r.miss.join(', ')+'</span>';
   document.getElementById('ansout').innerHTML=msg+'<br><b>Check it, then click Save in Apex.</b>';
 };
 document.getElementById('ansnext').onclick=function(){
   I++; try{ localStorage.setItem(KEY,String(I)); }catch(e){}
   box.remove(); alert(I>=D.length?'That was the last one.':'Next: '+D[I].name+'\n\nOpen a blank Add Employee form and click the button again.');
 };
 document.getElementById('ansreset').onclick=function(e){ e.preventDefault();
   try{ localStorage.setItem(KEY,'0'); }catch(err){} box.remove(); alert('Back to the first person.'); };
})();
"""


def build_js(people: List[Dict], week: str) -> str:
    """The bookmarklet body: the week's data plus the filler, as one line."""
    js = _JS % {"data": json.dumps(people, separators=(",", ":")),
                "week": week.replace("'", ""),
                "role": json.dumps(SECURITY_ROLE_LABEL.lower())}
    return "javascript:" + " ".join(js.split())


def rows_for(values: Dict[str, str]) -> Dict[str, str]:
    """{Apex label: value} -- only the fields we actually have."""
    return {LABEL_FOR[k]: v for k, v in values.items()
            if k in LABEL_FOR and v}


PAGE = """<!doctype html><meta charset="utf-8">
<title>Fill Apex — {week}</title>
<style>
 body{{font:16px/1.55 -apple-system,Helvetica,sans-serif;max-width:720px;
      margin:40px auto;padding:0 20px;color:#111}}
 h1{{font-size:26px;margin:0 0 4px}} .sub{{color:#666;margin-bottom:26px}}
 .btn{{display:inline-block;background:#0F766E;color:#fff;text-decoration:none;
      padding:14px 26px;border-radius:10px;font-weight:700;font-size:18px}}
 .drag{{background:#f4f7f7;border:2px dashed #0F766E;border-radius:12px;
       padding:22px;text-align:center;margin:22px 0}}
 ol{{padding-left:22px}} li{{margin:10px 0}}
 .note{{background:#fffbe6;border-left:4px solid #e0b500;padding:12px 16px;
       margin:22px 0;font-size:15px}}
 table{{border-collapse:collapse;width:100%;font-size:14px;margin-top:10px}}
 td,th{{border-bottom:1px solid #eee;padding:6px 8px;text-align:left}}
 .warn{{color:#b00}}
</style>
<h1>Fill Apex — {week}</h1>
<div class="sub">{n} new start{s} ready. Blue Ink extraction is done.</div>

<div class="drag">
  <div style="margin-bottom:12px;font-size:15px">Save this <b>once on this
  computer</b> — drag it to your bookmarks bar:</div>
  <a class="btn" href="{js}" id="thebtn">Fill Apex</a>
  <div style="margin-top:16px;font-size:14px;color:#555">
    No bookmarks bar? <button id="copybtn" style="font:inherit;padding:6px 12px;
    border:1px solid #0F766E;background:#fff;color:#0F766E;border-radius:6px;
    cursor:pointer">Copy the button</button>
    <span id="copied" style="color:#0F766E;display:none">copied ✓</span>
  </div>
</div>

<div class="note" id="manual">
  <b>If you can't drag it:</b> click <b>Copy the button</b> above, then
  <b>Bookmarks → Open Bookmarks Manager</b> → the <b>⋮</b> at the top right →
  <b>Add new bookmark</b>. Name it <b>Fill Apex</b> and paste into the URL box.
  It then lives in your Bookmarks menu — no bar needed.
</div>

<script>
document.getElementById('copybtn').onclick = function(){{
  var url = document.getElementById('thebtn').getAttribute('href');
  var done = function(){{
    var c = document.getElementById('copied');
    c.style.display = 'inline'; setTimeout(function(){{c.style.display='none';}}, 2500);
  }};
  if (navigator.clipboard) {{ navigator.clipboard.writeText(url).then(done, fallback); }}
  else fallback();
  function fallback(){{
    var t = document.createElement('textarea');
    t.value = url; document.body.appendChild(t); t.select();
    try {{ document.execCommand('copy'); done(); }} catch(e) {{ alert('Select and copy this:\\n\\n' + url); }}
    t.remove();
  }}
}};
</script>

<ol>
  <li>Log into Apex yourself, with the code it texts you.</li>
  <li>Open <b>Roster → Employees → + Add Employee</b>.</li>
  <li>Click <b>Fill Apex</b> in your bookmarks bar. A panel appears with the
      person's name and fills the boxes on that page.</li>
  <li>Check it, click <b>Save</b> in Apex.</li>
  <li>On their profile and tax pages, click <b>Fill Apex</b> again — it fills
      whatever belongs to the page you're on. The tax page is where it asks you
      for their Social.</li>
  <li>Press <b>Saved → next</b> in the panel to move to the next person.</li>
</ol>

<div class="note">
  <b>The Social is never in this page.</b> You type it into the panel on Apex's
  tax screen and it goes straight into Apex's own boxes, in your browser. It is
  not stored here, in the report, or anywhere else.
</div>

<h3>Who's in this batch</h3>
<table><tr><th>#</th><th>Name</th><th>Hire date</th><th>Needs a hand</th></tr>
{rows}
</table>
<p class="sub" style="margin-top:24px">Generated {stamp}. If the board changes,
re-run the report and open this page again — the button carries the data, so an
old bookmark holds old data. Re-drag it after a new run.</p>
"""


def build_page(people, week: str, stamp: str, notes=None) -> str:
    """The whole page: the draggable button, the steps, and who is in it."""
    notes = notes or {}
    rows = []
    for i, p in enumerate(people, 1):
        gap = notes.get(p["name"], "")
        rows.append(
            "<tr><td>%d</td><td>%s</td><td>%s</td><td class=\"%s\">%s</td></tr>"
            % (i, p["name"], p["fields"].get("Hire Date", "—"),
               "warn" if gap else "", gap or "—"))
    return PAGE.format(
        week=week, n=len(people), s="" if len(people) == 1 else "s",
        js=build_js(people, week).replace('"', "&quot;"),
        rows="\n".join(rows), stamp=stamp)
