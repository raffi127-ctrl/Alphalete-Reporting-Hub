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
    # Hire Date and User Name are READ-ONLY text on the Edit pages -- already
    # correct on the Pending record, and not ours to change.
    "country": "Country", "pay_frequency": "Pay Frequency",
    "position": "Position", "rate": "Rate of Pay",
    "pay_state": "State Working In", "pay_basis": "Basis of Pay",
    "department": "Department",
    "dob": "Date of Birth", "gender": "Gender",
    "address1": "Street Address", "apt": "Apt/PO Box",
    "address2": "Street Address 2", "city": "City", "state": "State",
    "zip": "Zip Code", "home_phone": "Home Phone",
    "mobile_phone": "Mobile Phone",
    "claim_dependents": "Claim Dependants",   # Apex spells it with an A
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
 function kw(el){
   /* Apex's dropdowns are Kendo UI widgets on AngularJS, not <select>s. The
      <label for> points at a HIDDEN input holding the id, and the thing you
      see is a k-dropdown span beside it. Setting .value on that input changes
      nothing: Angular never hears about it and the widget keeps its own state.
      So anything Kendo-backed has to be driven through Kendo's own API. */
   var $=window.jQuery||window.$; if(!$||!el) return null;
   var e=$(el), w=e.data('kendoDropDownList')||e.data('kendoComboBox')||
          e.data('kendoNumericTextBox')||e.data('kendoDatePicker')||
          e.data('kendoMaskedTextBox')||null;
   if(w) return w;
   /* The NumericTextBox answers to .data(); the DropDownLists on this page do
      not -- kendo-angular can hang the widget somewhere else entirely. Ask
      Kendo itself, then look at the k-widget span sitting beside the hidden
      input, which is the thing the user actually sees. */
   if(window.kendo&&kendo.widgetInstance){
     try{ w=kendo.widgetInstance(e); }catch(x){}
     if(w&&w.value) return w;
     var box=el.parentElement, sp=box?box.querySelector('.k-widget'):null, hops=0;
     while(!sp&&box&&hops<2){ box=box.parentElement; sp=box?box.querySelector('.k-widget'):null; hops++; }
     if(sp){ try{ w=kendo.widgetInstance($(sp)); }catch(x2){}
             if(w&&w.value) return w; }
   }
   return null;
 }
 function ngApply(el){
   if(!window.angular) return;
   try{ var sc=angular.element(el).scope();
        if(sc&&!sc.$$phase) sc.$applyAsync(); }catch(e){}
 }
 function sleep(ms){ return new Promise(function(r){ setTimeout(r,ms); }); }
 function fire(el,type){
   el.dispatchEvent(new MouseEvent(type,{bubbles:true,cancelable:true,view:window}));
 }
 function widgetSpan(el){
   /* The thing a person actually clicks: the k-dropdown span sitting beside
      the hidden input the <label> points at -- in the SAME parent, and only
      there. Walking up the tree looked more forgiving and was wrong: it found
      a neighbouring field's dropdown and declared a plain text box
      Kendo-backed, so City stopped filling. */
   var box=el.parentElement;
   return box?box.querySelector(':scope > .k-dropdown, :scope > .k-combobox, :scope > .k-widget'):null;
 }
 function openLists(){
   var uls=document.querySelectorAll('ul.k-list,ul.k-reset'), out=[], i;
   for(i=0;i<uls.length;i++){ var r=uls[i].getBoundingClientRect();
     if(r.width>0&&r.height>0) out.push(uls[i]); }
   return out;
 }
 async function kendoClick(el,v){
   /* Drive the dropdown the way a person does: click it, wait for the list,
      click the option. This is the ONLY approach that does not depend on how
      kendo-angular wired the widget -- .data() and kendo.widgetInstance both
      came back empty on the live page, while the NumericTextBox answered fine.
      A real click can't be wrong about that. */
   var sp=widgetSpan(el); if(!sp) return false;
   fire(sp,'mousedown'); fire(sp,'mouseup'); fire(sp,'click');
   var lists=[], waited=0;
   while(waited<2000){ lists=openLists(); if(lists.length) break; await sleep(100); waited+=100; }
   if(!lists.length) return false;
   var want=norm(v), i, j, items, best=null;
   for(i=0;i<lists.length&&!best;i++){
     items=lists[i].querySelectorAll('li');
     for(j=0;j<items.length;j++){
       var t=norm(items[j].textContent);
       if(t===want){ best=items[j]; break; }
     }
     if(!best) for(j=0;j<items.length;j++){
       var t2=norm(items[j].textContent);
       if(t2&&(t2.indexOf(want)===0||want.indexOf(t2)===0)){ best=items[j]; break; }
     }
   }
   if(!best){ fire(sp,'mousedown'); fire(document.body,'click'); return false; }
   best.scrollIntoView({block:'nearest'});
   fire(best,'mouseover'); fire(best,'mousedown'); fire(best,'mouseup'); fire(best,'click');
   await sleep(150);
   ngApply(el);
   return true;
 }
 function kendoSet(el,v){
   var w=kw(el); if(!w) return false;
   if(w.dataSource&&w.dataSource.data&&w.options&&w.value){
     var d=w.dataSource.data()||[], want=norm(v),
         tf=w.options.dataTextField, vf=w.options.dataValueField, i, t;
     for(i=0;i<d.length;i++){
       t=norm(tf&&d[i][tf]!==undefined?d[i][tf]:(d[i].Text||d[i].text||d[i]));
       if(t===want||(t&&(t.indexOf(want)===0||want.indexOf(t)===0))){
         w.value(vf&&d[i][vf]!==undefined?d[i][vf]:(d[i].Value||d[i].value||d[i]));
         w.trigger('change'); ngApply(el); return true;
       }
     }
     return false;
   }
   w.value(v); w.trigger('change'); ngApply(el); return true;
 }
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
       /* A Kendo-backed input is legitimately hidden -- accept it anyway.
          Either it answers to the widget API, or there is a k-dropdown span
          beside it that a person would click. Both count; the plain rule
          ("never touch something invisible") holds everywhere else. */
       if(f && (kw(f) || widgetSpan(f) ||
                (vis(f) && !(f.tagName==='INPUT'&&BAD[(f.type||'').toLowerCase()])))) out.push(f);
     }
     if(out.length===1) return out[0];
   }
   var all=document.querySelectorAll('div,span,td,th,p,legend,strong,b'), cands=[];
   var mine=document.getElementById('anspanel');
   for(i=0;i<all.length;i++){
     if(mine&&mine.contains(all[i])) continue;   /* never match our own panel */
     if(all[i].children.length>2) continue;
     if(norm(all[i].textContent)!==want) continue;
     var f=nearInput(all[i]);
     if(f&&cands.indexOf(f)<0) cands.push(f);
   }
   if(cands.length===1) return cands[0];
   return null;
 }
 async function setVal(el,v){
   if(kendoSet(el,v)) return true;
   if(el.tagName!=='SELECT'&&widgetSpan(el)){
     if(await kendoClick(el,v)) return true;
     /* A Kendo control that would not take the value must NOT fall through to
        el.value: that input is hidden and holds an id, so writing 'Astronaut'
        into it sets a value the widget disowns and the page still shows
        'Select' -- wrong, and invisible. An honest miss is reported instead. */
     return false;
   }
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
 async function fill(p){
   var done=[],miss=[],found=0,k;
   for(k in p.fields){ var el=fieldFor(k);
     if(el){ found++;
       if(await setVal(el,p.fields[k])) done.push(k); else miss.push(k+' (no matching option)'); }
     else miss.push(k); }
   if(role()){ done.push('Sales Rep role'); found++; }
   /* `found` is boxes we LOCATED, which is not the same as boxes we filled.
      Without the difference, a page where every field was found but one value
      would not match got reported as "not an Apex form". */
   return {done:done,miss:miss,found:found};
 }
 function ssnBoxes(){ var a=fieldFor('SSN')||fieldFor('Change SSN'),
                      b=fieldFor('Confirm SSN'); return (a&&b)?[a,b]:null; }
 function genderBox(p){
   /* Required on the profile page. Ask for it here when the board's Gender
      column was empty -- which it usually is by the time this runs. Without
      it Apex refuses the whole page with "The request is invalid", naming
      nothing. */
   if(p.fields['Gender']) return null;
   return fieldFor('Gender');
 }
 function blueink(p){ return 'https://secure.blueink.com/dashboard/wall?search='+encodeURIComponent(p.find||p.name); }
 var old=document.getElementById('anspanel'); if(old) old.remove();
 var p=D[Math.min(I,D.length-1)];
 var box=document.createElement('div'); box.id='anspanel';
 box.style.cssText='position:fixed;top:14px;right:14px;z-index:2147483647;background:#fff;border:2px solid #0F766E;border-radius:10px;padding:14px 16px;font:14px -apple-system,Helvetica,sans-serif;box-shadow:0 6px 24px rgba(0,0,0,.25);max-width:330px';
 var ssn=ssnBoxes(), gnd=genderBox(p);
 box.innerHTML='<div style="font-weight:700;font-size:16px">'+p.name+'</div>'+
   '<div style="color:#555;margin:2px 0 10px">'+(I+1)+' of '+D.length+' · %(week)s</div>'+
   (gnd?'<div style="margin-bottom:8px"><div style="font-size:12px;color:#555">Gender <span style="color:#b00">(required, not on the board)</span></div>'+
        '<select id="ansgender" style="width:100%%;padding:6px;font-size:15px">'+
        '<option value="">Pick one</option><option>Female</option><option>Male</option></select></div>':'')+
   (ssn?'<div style="margin-bottom:8px"><div style="font-size:12px;color:#555">Social Security number</div>'+
        '<input id="ansssn" type="password" style="width:100%%;padding:6px;font-size:15px">'+
        '<div style="margin-top:6px"><a href="'+blueink(p)+'" target="_blank" rel="noopener" id="ansbi" style="font-size:12px;color:#0F766E">Open their Blue Ink packet →</a>'+
        '<span style="font-size:11px;color:#888"> (I-9 → Quick View)</span></div></div>':'')+
   '<button id="ansfill" style="background:#0F766E;color:#fff;border:0;border-radius:6px;padding:8px 14px;font-size:14px;cursor:pointer">Fill this page</button> '+
   '<button id="ansnext" style="background:#eee;border:0;border-radius:6px;padding:8px 12px;cursor:pointer">Saved → next</button>'+
   '<div id="ansout" style="margin-top:9px;font-size:12px;color:#333"></div>'+
   '<div style="margin-top:8px"><a href="#" id="ansreset" style="font-size:11px;color:#888">start the week again</a></div>';
 document.body.appendChild(box);
 document.getElementById('ansfill').onclick=async function(){
   document.getElementById('ansout').innerHTML='filling...';
   var r=await fill(p);
   /* Nothing matched at all = not an Apex form. Saying so beats a wall of red
      listing every field the page was never going to have, which is what it
      did the first time somebody clicked it on the wrong tab. NOTE: block
      comments only in here -- build_js collapses this to ONE line, so a
      line comment would swallow the entire rest of the script. */
   if(!r.found && !ssnBoxes()){
     document.getElementById('ansout').innerHTML=
       '<b>This isn\'t an Apex form.</b><br>Open <b>Roster → Employees → '+
       'Pending</b>, click <b>Edit</b> on '+p.name+', then click the button '+
       'on each of the three tabs.';
     return;
   }
   var msg='Filled: '+(r.done.join(', ')||'nothing on this page');
   var g=document.getElementById('ansgender');
   if(g&&g.value){ var gb=genderBox(p);
     if(gb&&await setVal(gb,g.value)){ msg+='; gender '+g.value; }
     else msg+='; <span style="color:#b00">gender would not set</span>'; }
   else if(gnd) msg+='<br><span style="color:#b00">Gender is required and '+
     'still empty — pick one above and Fill again, or Apex will refuse to '+
     'save this page.</span>';
   var s=document.getElementById('ansssn');
   if(s&&s.value){ var b=ssnBoxes(); if(b){ await setVal(b[0],s.value); await setVal(b[1],s.value); s.value=''; msg+='; Social entered'; } }
   if(r.miss.length) msg+='<br><span style="color:#b00">Not found here: '+r.miss.join(', ')+'</span>'+
     ' <a href="#" id="answhy" style="font-size:11px">why?</a>';
   document.getElementById('ansout').innerHTML=msg+'<br><b>Check it, then click Save in Apex.</b>';
   var w=document.getElementById('answhy');
   if(w) w.onclick=function(e){ e.preventDefault();
     /* Show the markup around the FIRST field we could not place, so the
        shape of the page can be fixed once instead of guessed at twice. */
     /* Skip our OWN panel: it lists every missing field name, so the first
        scan matched its own red text and reported the panel's markup. And
        diagnose a field that is actually ON this page -- 'Street Address'
        belongs to the profile screen and being absent here is correct. */
     var panel=document.getElementById('anspanel'), want=null;
     for(var m=0;m<r.miss.length&&!want;m++){
       var cand=r.miss[m], probe=document.querySelectorAll('*');
       for(var q=0;q<probe.length;q++){
         if(probe[q].children.length||panel.contains(probe[q])) continue;
         if(norm(probe[q].textContent)===norm(cand)){ want=cand; break; }
       }
     }
     if(!want) want=r.miss[0];
     var out=['<b>'+want+'</b>'], seen=0;
     var all=document.querySelectorAll('*');
     for(var i=0;i<all.length&&seen<3;i++){
       var el=all[i];
       if(el.children.length||panel.contains(el)) continue;
       if(norm(el.textContent).indexOf(norm(want))<0) continue;
       seen++;
       var chain=[], n=el, d=0;
       while(n&&d<4){ chain.push(n.tagName.toLowerCase()+(n.id?'#'+n.id:'')); n=n.parentElement; d++; }
       var par=el.parentElement, sibs=[], sb=par?par.children:[];
       for(var j=0;j<sb.length&&j<8;j++) sibs.push(sb[j].tagName.toLowerCase()+(sb[j].id?'#'+sb[j].id:''));
       out.push('text in: '+chain.join(' &lt; ')+'<br>parent kids: '+sibs.join(', '));
     }
     if(seen===0) out.push('that caption text is not on this page at all');
     var lab=null, ls=document.querySelectorAll('label');
     for(var z=0;z<ls.length;z++) if(norm(ls[z].innerText)===norm(want)) lab=ls[z];
     if(lab){
       var tgt=lab.htmlFor?document.getElementById(lab.htmlFor):null;
       var $$=window.jQuery||window.$;
       out.push('label for='+(lab.htmlFor||'(none)')+
         '<br>target: '+(tgt?tgt.tagName.toLowerCase()+'[type='+(tgt.type||'')+']':'(missing)')+
         '<br>jQuery: '+(!!$$)+' kendo: '+(!!window.kendo)+
         ' widgetInstance: '+(!!(window.kendo&&kendo.widgetInstance))+
         '<br>kw(): '+(tgt?(kw(tgt)?'FOUND '+(kw(tgt).options?'has options':'no options'):'null'):'n/a')+
         '<br>siblings: '+(tgt&&tgt.parentElement?Array.prototype.slice.call(tgt.parentElement.children).map(function(c){return c.tagName.toLowerCase()+'.'+(c.className||'').split(' ')[0];}).join(', '):''));
     }
     document.getElementById('ansout').innerHTML=out.join('<hr style="border:0;border-top:1px solid #eee">')+
       '<div style="margin-top:6px;font-size:11px">screenshot this</div>';
   };
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
  <li>Open <b>Roster → Employees</b> and click the <b>Pending</b> tab. Everyone
      below is already there — their account exists, their profile is empty.</li>
  <li>Click <b>Edit</b> on the person the panel names.</li>
  <li>Click <b>Fill Apex</b>. It fills whatever belongs to the tab you're on,
      then you click <b>Save</b> in Apex.</li>
  <li>Do the same on their other tabs — <b>Employment Record</b>,
      <b>User Profile &amp; Account</b>, <b>Tax &amp; Bank Information</b>.
      The tax tab is where it asks you for their Social.</li>
  <li>Press <b>Saved → next</b> in the panel to move to the next person.</li>
</ol>

<div class="note">
  <b>Nobody is being created.</b> These people are already in Apex on the
  Pending tab, so their name, user name and email are left exactly as they are.
  This only fills in what's blank.
</div>

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
