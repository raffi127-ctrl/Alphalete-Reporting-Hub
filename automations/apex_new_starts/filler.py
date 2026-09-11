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
# Which of Apex's three pages each field lives on. Without this, every field
# is offered to every page and a caption that happens to repeat gets matched
# across screens: "State" (the home address, on the profile page) found the
# "State" caption under Additional Tax Amount Withheld on the TAX page and put
# "Texas" in the money box beside it. A field is only ever filled on its own
# page now.
PAGE_OF = {
    "employment": ("position", "rate", "pay_state", "pay_basis",
                   "pay_frequency", "department"),
    "profile": ("first", "middle", "last", "account_email", "dob", "gender",
                "address1", "apt", "address2", "city", "state", "zip",
                "country"),
    "tax": ("marital_status", "claim_dependents", "tax_state"),
}

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
 var KEY='apexNewStarts.%(week)s', DKEY=KEY+'.data';
 /* Stamped when the button was generated. A saved bookmarklet freezes
    whatever was in it, so the only way to tell a fixed button from the one
    saved three fixes ago is to have it say so out loud. */
 var BUILD='%(build)s', BUILT_AT=%(built_at)s;
 /* The week's people live in this browser, not inside the button. Carrying
    them meant a saved bookmark froze that week's data AND that day's code, so
    every change cost a delete, a copy and a re-drag. Saved once now; a new
    week is a paste. */
 var D=%(data)s;
 if(!D){ try{ D=JSON.parse(localStorage.getItem(DKEY)||'null'); }catch(e){} }
 if(!D||!D.length){
   var o0=document.getElementById('anspanel'); if(o0) o0.remove();
   var w0=document.createElement('div'); w0.id='anspanel';
   w0.style.cssText='position:fixed;top:14px;right:14px;z-index:2147483647;background:#fff;border:2px solid #0F766E;border-radius:10px;padding:14px 16px;font:14px -apple-system,Helvetica,sans-serif;box-shadow:0 6px 24px rgba(0,0,0,.25);max-width:340px';
   w0.innerHTML='<div style="font-weight:700">No list loaded for %(week)s</div>'+
     '<div style="color:#555;margin:4px 0 8px;font-size:12px">On the Fill Apex page click '+
     '<b>Copy this week\u0027s list</b>, then paste it here.</div>'+
     '<textarea id="anspaste" style="width:100%%;height:70px;font-size:11px"></textarea>'+
     '<div style="margin-top:8px"><button id="anssave" style="background:#0F766E;color:#fff;border:0;border-radius:6px;padding:7px 14px;cursor:pointer">Load it</button> '+
     '<span id="anspmsg" style="font-size:12px;color:#b00"></span></div>';
   document.body.appendChild(w0);
   document.getElementById('anssave').onclick=function(){
     try{
       var parsed=JSON.parse(document.getElementById('anspaste').value);
       if(!parsed||!parsed.length) throw 0;
       localStorage.setItem(DKEY,JSON.stringify(parsed));
       w0.remove();
       alert('Loaded '+parsed.length+' people for %(week)s.\nClick the button again.');
     }catch(e){ document.getElementById('anspmsg').textContent='That is not the list — copy it again.'; }
   };
   return;
 }
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
   /* The widget may live on the VISIBLE input Kendo created, not on the
      hidden one the <label> points at. Ask every element in the group before
      giving up: hidden input, visible input, wrapper span. */
   var sp0=el.parentElement?el.parentElement.querySelector('.k-widget'):null;
   var vis0=sp0?sp0.querySelector('input:not([type=hidden])'):null;
   if(vis0){ var ve=$(vis0);
     w=ve.data('kendoComboBox')||ve.data('kendoDropDownList')||
       ve.data('kendoNumericTextBox')||ve.data('kendoDatePicker')||null;
     if(w) return w; }
   if(window.kendo&&kendo.widgetInstance){
     try{ w=kendo.widgetInstance(e); }catch(x){}
     if(w&&w.value) return w;
     if(vis0){ try{ w=kendo.widgetInstance($(vis0)); }catch(xv){}
               if(w&&w.value) return w; }
     var box=el.parentElement, sp=box?box.querySelector('.k-widget'):null, hops=0;
     while(!sp&&box&&hops<2){ box=box.parentElement; sp=box?box.querySelector('.k-widget'):null; hops++; }
     if(sp){ try{ w=kendo.widgetInstance($(sp)); }catch(x2){}
             if(w&&w.value) return w; }
   }
   return null;
 }
 function settle(el){
   /* Apex wires these in TWO halves: the Kendo <select> holds the object
      (k-ng-model="vm.address.StateProvince") and a separate hidden input holds
      the id the form submits (ng-model="...StateProvince.StateProvinceID").
      What copies one into the other is ng-blur="vm.onChangeStateProvince()".
      Selecting without blurring leaves the widget showing Texas and
      StateProvinceID empty -- which is exactly the 400 Apex kept returning.
      So every set is followed by a blur on the control AND on the <select>
      inside its widget, then a digest. */
   var targets=[el], sp=el?widgetSpan(el):null, i;
   if(el&&el.tagName==='SELECT') targets.push(el);
   if(sp){ var sel=sp.querySelector('select'); if(sel) targets.push(sel);
           var vi=visibleInput(sp,el); if(vi) targets.push(vi); }
   if(el&&el.parentElement){ var s2=el.parentElement.querySelector('select');
     if(s2) targets.push(s2); }
   for(i=0;i<targets.length;i++){
     if(!targets[i]) continue;
     try{
       targets[i].dispatchEvent(new Event('change',{bubbles:true}));
       targets[i].dispatchEvent(new FocusEvent('blur',{bubbles:false}));
       targets[i].dispatchEvent(new Event('blur',{bubbles:true}));
       if(targets[i].blur) targets[i].blur();
     }catch(e){}
   }
   ngApply(el);
   runNgHooks(el);
 }
 function ngApply(el){
   if(!window.angular) return;
   try{ var sc=angular.element(el).scope();
        if(sc&&!sc.$$phase) sc.$applyAsync(); }catch(e){}
 }
 function runNgHooks(el){
   /* A blur SHOULD fire ng-blur, but which node carries it varies -- the
      hidden input, the <select>, or the widget span. Apex answered a set
      Marital Status with MaritalStatusID: "Marital Status is Required": the
      dropdown showed the words and the id the form submits was never copied
      across. So run the expression Apex put there, whichever node holds it.
      That is exactly the work ng-blur exists to do (Megan, 2026-09-10). */
   if(!window.angular||!el) return;
   var box=el, d=0;
   while(box&&d<4&&!(box.querySelector&&box.querySelector('[ng-blur],[ng-change]'))){
     box=box.parentElement; d++;
   }
   if(!box||!box.querySelectorAll) return;
   var hooks=box.querySelectorAll('[ng-blur],[ng-change]'), i, n, expr;
   for(i=0;i<hooks.length;i++){
     n=hooks[i];
     expr=n.getAttribute('ng-blur')||n.getAttribute('ng-change');
     if(!expr) continue;
     try{ var sc=angular.element(n).scope(); if(sc) sc.$eval(expr); }catch(e){}
   }
   ngApply(el);
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
   if(!el) return null;
   /* Two shapes, and only one was handled. On the profile page the hidden
      input sits BESIDE the k-widget span. On the tax page the <select> the
      label points at is INSIDE it -- so the widget is the element's own
      parent, and looking for a k-widget child of that parent finds nothing.
      That is why Marital Status opened its list and never got clicked. */
   var par=el.parentElement;
   if(par&&/(^|\s)k-widget(\s|$)/.test(par.className||'')) return par;
   if(par&&par.parentElement&&/(^|\s)k-widget(\s|$)/.test(par.parentElement.className||'')
      &&sameGroup(par.parentElement,el))
     return par.parentElement;
   return par?par.querySelector(':scope > .k-dropdown, :scope > .k-combobox, :scope > .k-widget'):null;
 }
 function popupLists(){
   /* Lists that are plainly a widget's popup, not the site's furniture. */
   var out=[], i, r, mine=document.getElementById('anspanel');
   var c=document.querySelectorAll('.k-animation-container ul, .k-list-container ul, '+
       '.k-popup ul, ul.k-list, ul.k-reset, [role="listbox"]');
   for(i=0;i<c.length;i++){ if(mine&&mine.contains(c[i])) continue;
     if(!c[i].querySelector('li,[role="option"]')) continue;
     r=c[i].getBoundingClientRect(); if(r.width>0&&r.height>0) out.push(c[i]); }
   return out;
 }
 function openLists(){
   /* Any visible list of options, however Kendo happened to class it. The
      first version demanded ul.k-list / ul.k-reset and the Gender dropdown
      opened and then sat there: the click had worked, the list was on screen,
      and nothing matched the selector. Take any visible <ul> with items, and
      anything wearing listbox/option roles, and never our own panel. */
   var mine=document.getElementById('anspanel'), out=[], i, r;
   var cands=document.querySelectorAll(
     'ul.k-list, ul.k-reset, .k-animation-container ul, .k-list-container ul, '+
     '[role="listbox"], .k-popup ul, ul');
   for(i=0;i<cands.length;i++){
     var c=cands[i];
     if(mine&&mine.contains(c)) continue;
     if(!c.querySelector('li,[role="option"]')) continue;
     r=c.getBoundingClientRect();
     if(r.width>0&&r.height>0&&out.indexOf(c)<0) out.push(c);
   }
   return out;
 }
 var TRACE=[];
 /* Apex answers a bad save with "The request is invalid" and nothing else,
    while the page itself reports no invalid field. The server knows which one
    it is -- ASP.NET model-state errors name it -- so listen for the failing
    response and show it. Installed once per page. */
 if(!window.__ansNet){
   window.__ansNet={last:null};
   var _f=window.fetch;
   if(_f) window.fetch=function(){
     var args=arguments;
     return _f.apply(this,args).then(function(r){
       if(!r.ok){ try{ r.clone().text().then(function(t){
         window.__ansNet.last={url:(args[0]&&args[0].url)||args[0],status:r.status,body:(t||'').slice(0,1200)};
       }); }catch(e){} }
       return r;
     });
   };
   var _o=XMLHttpRequest.prototype.open, _s=XMLHttpRequest.prototype.send;
   XMLHttpRequest.prototype.open=function(m,u){ this.__u=u; return _o.apply(this,arguments); };
   XMLHttpRequest.prototype.send=function(){
     var x=this;
     x.addEventListener('load',function(){
       if(x.status>=400) window.__ansNet.last={url:x.__u,status:x.status,
         body:(x.responseText||'').slice(0,1200)};
     });
     return _s.apply(this,arguments);
   };
 }
 function sameGroup(a,b){
   /* Two controls belong together only if they share a form-group. Without
      this, a widget span resolved one level too high reached into the NEXT
      field: "Texas" was typed into "Additional Tax Amount Withheld ->
      Federal", a money box on a tax record. Nothing may ever be written
      outside the field it was meant for. */
   if(!a||!b||!a.closest||!b.closest) return true;
   var ga=a.closest('.form-group'), gb=b.closest('.form-group');
   /* Only judge when BOTH sit in a real group -- that is the case on Apex's
      pages, and the case where reaching into a neighbour is possible. */
   if(!ga||!gb) return true;
   return ga===gb;
 }
 function visibleInput(sp,owner){
   var ins=sp.querySelectorAll('input'), i, r;
   for(i=0;i<ins.length;i++){
     if((ins[i].type||'text').toLowerCase()==='hidden') continue;
     if(ins[i].getAttribute('aria-hidden')==='true') continue;
     r=ins[i].getBoundingClientRect();
     if(r.width<=0||r.height<=0) continue;
     if(owner&&!sameGroup(ins[i],owner)) continue;   /* never a neighbour's box */
     return ins[i];
   }
   return null;
 }
 async function typeInto(sp,v,el){
   /* A Kendo ComboBox is a TEXT box with a list attached -- you type into it.
      Its popup never opened from a click on the wrapper (lists after 2500ms:
      0, twice), which is exactly how a combobox behaves. Typing is what it is
      for, and it is also what a person would do. */
   var inp=visibleInput(sp,el); if(!inp) return false;
   inp.focus();
   inp.value=v;
   ['input','keydown','keyup','change'].forEach(function(t){
     inp.dispatchEvent(t==='input'||t==='change'
       ? new Event(t,{bubbles:true})
       : new KeyboardEvent(t,{bubbles:true,key:'a'}));
   });
   await sleep(250);
   inp.dispatchEvent(new KeyboardEvent('keydown',{bubbles:true,key:'Enter',keyCode:13}));
   inp.blur();
   inp.dispatchEvent(new Event('blur',{bubbles:true}));
   await sleep(200);
   ngApply(inp);
   /* A ComboBox will happily keep typed text as a CUSTOM value. The screen
      then reads "Male" while the model holds the word instead of the list
      item's id -- Angular is satisfied, and the SERVER answers "The request is
      invalid". So check what the bound field actually ended up holding. */
   var bound=null, grp=el&&el.closest?el.closest('.form-group'):null;
   var hid=(grp||sp.parentElement||sp).querySelector('input[type=hidden]');
   if(hid) bound=hid.value;
   TRACE.push('typed "'+inp.value+'" bound="'+(bound===null?'?':bound)+'"');
   if(norm(inp.value)!==norm(v)) return false;
   if(hid&&(!bound||norm(bound)===norm(v))) return false;   /* free text, not a real pick */
   return true;
 }
 async function keyboardPick(sp,el,v){
   /* Kendo dropdowns support type-ahead: focus the widget and type the first
      letters and it selects the matching item itself -- which means Kendo does
      the binding, not us. Worth trying when a click updates the display and
      leaves the id empty. */
   var target=visibleInput(sp,el)||sp;
   target.focus();
   var i, ch;
   for(i=0;i<v.length&&i<12;i++){
     ch=v.charAt(i);
     target.dispatchEvent(new KeyboardEvent('keydown',{bubbles:true,key:ch}));
     target.dispatchEvent(new KeyboardEvent('keypress',{bubbles:true,key:ch}));
     target.dispatchEvent(new KeyboardEvent('keyup',{bubbles:true,key:ch}));
     await sleep(40);
   }
   target.dispatchEvent(new KeyboardEvent('keydown',{bubbles:true,key:'Enter',keyCode:13}));
   target.dispatchEvent(new KeyboardEvent('keyup',{bubbles:true,key:'Enter',keyCode:13}));
   await sleep(200);
   settle(el);
   TRACE.push('typeahead -> bound "'+String(boundValue(el)).slice(0,20)+'"');
   return bindingLooksReal(el,v);
 }
 async function kendoClick(el,v){
   TRACE=[];
   /* Drive the dropdown the way a person does: click it, wait for the list,
      click the option. This is the ONLY approach that does not depend on how
      kendo-angular wired the widget -- .data() and kendo.widgetInstance both
      came back empty on the live page, while the NumericTextBox answered fine.
      A real click can't be wrong about that. */
   var sp=widgetSpan(el);
   TRACE.push('span: '+(sp?(sp.className||'').split(' ').slice(0,2).join('.'):'NONE'));
   if(!sp) return false;
   /* Snapshot BEFORE the click, or the popup it opens is already in the
      baseline and gets diffed straight back out again. */
   var before=openLists();
   /* A combobox takes typing; a dropdown list does not. Try typing first when
      the widget has a real text box inside it. */
   if(/k-combobox/.test(sp.className||'')&&await typeInto(sp,v,el)) return true;
   fire(sp,'mousedown'); fire(sp,'mouseup'); fire(sp,'click');
   /* Only lists that appeared BECAUSE of the click. Taking every visible <ul>
      swept up the site's own nav menus -- three of them, present at 0ms -- and
      the search for "male" went hunting through "log off" and "employees".
      Snapshot first, then diff; and a proper widget popup always wins. */
   var lists=[], waited=0, i;
   function fresh(){
     var now=popupLists();
     if(now.length) return now;
     now=openLists(); var out=[];
     for(i=0;i<now.length;i++) if(before.indexOf(now[i])<0) out.push(now[i]);
     return out;
   }
   while(waited<2500){ lists=fresh(); if(lists.length) break; await sleep(100); waited+=100; }
   TRACE.push('lists after '+waited+'ms: '+lists.length);
   if(!lists.length){
     /* Some widgets only open from the arrow, or from the input inside */
     var alt=sp.querySelector('.k-select,.k-icon,.k-input')||sp;
     fire(alt,'mousedown'); fire(alt,'mouseup'); fire(alt,'click');
     waited=0;
     while(waited<1500){ lists=fresh(); if(lists.length) break; await sleep(100); waited+=100; }
     TRACE.push('after arrow click: '+lists.length);
   }
   if(!lists.length){
     if(await typeInto(sp,v,el)) return true;
     if(await keyboardPick(sp,el,v)) return true;
     return false;
   }
   var want=norm(v), i, j, items, best=null;
   for(i=0;i<lists.length&&!best;i++){
     items=lists[i].querySelectorAll('li,[role="option"]');
     for(j=0;j<items.length;j++){
       var t=norm(items[j].textContent);
       if(t===want){ best=items[j]; break; }
     }
     if(!best) for(j=0;j<items.length;j++){
       var t2=norm(items[j].textContent);
       if(t2&&(t2.indexOf(want)===0||want.indexOf(t2)===0)){ best=items[j]; break; }
     }
     if(!best) for(j=0;j<items.length;j++){
       var t3=norm(items[j].textContent);
       if(t3&&t3.indexOf(want)>=0){ best=items[j]; break; }
     }
   }
   if(!best){
     var names=[], L, M;
     for(L=0;L<lists.length;L++){ var it=lists[L].querySelectorAll('li,[role="option"]');
       for(M=0;M<it.length&&M<8;M++) names.push(norm(it[M].textContent).slice(0,18)); }
     TRACE.push('wanted "'+want+'" — saw: '+(names.join(' | ')||'(no items)'));
     fire(sp,'mousedown'); fire(document.body,'click'); return false;
   }
   best.scrollIntoView({block:'nearest'});
   fire(best,'mouseover'); fire(best,'mousedown'); fire(best,'mouseup'); fire(best,'click');
   await sleep(150);
   settle(el);
   await sleep(250);
   if(!bindingLooksReal(el,v)){
     /* Apex repopulates some of these asynchronously after the blur -- State
        and Country both showed the right text while the check said otherwise.
        Look once more before calling it a miss. */
     await sleep(500);
   }
   if(!bindingLooksReal(el,v)){
     /* The option was clicked and the display changed, but the id behind it is
        still empty -- State did exactly this. Let Kendo make the selection
        itself via type-ahead, so the binding is its own doing. */
     TRACE.push('clicked but binding empty; trying type-ahead');
     if(await keyboardPick(sp,el,v)) return true;
     return false;
   }
   return true;
 }
 function boundValue(el){
   /* What the form will actually SEND for this control. Looked for only in the
      element's own parent at first, so a group shaped even slightly
      differently returned null -- and null means "nothing to check", which
      quietly turned the verification off for exactly the fields most likely to
      need it. Widen to the form-group, and prefer an input that carries an
      ng-model, which is the one Angular submits. */
   if(el&&(el.type||'').toLowerCase()==='hidden') return el.value;
   var box=el?(el.closest?el.closest('.form-group,.col-md-6,.col-lg-4'):null):null;
   box=box||(el?el.parentElement:null);
   if(!box) return null;
   var h=box.querySelector('input[type=hidden][ng-model]')||
         box.querySelector('input[type=hidden]');
   return h?h.value:null;
 }
 function bindingLooksReal(el,v){
   /* The screen said Texas and the server said
      request.HomeAddress.StateProvinceID: "An error has occurred." -- the
      display text was right and the id behind it was never set. So a widget
      that reports success is not believed until the bound field holds
      something, and something OTHER than the words we just put on screen. */
   var b=boundValue(el);
   if(b===null) return true;              /* nothing bound: nothing to check */
   if(!String(b).trim()) return false;
   return norm(b)!==norm(v);
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
         w.trigger('change'); settle(el);
         if(!bindingLooksReal(el,v)){ TRACE.push('widget set but binding empty'); return false; }
         return true;
       }
     }
     return false;
   }
   w.value(v); w.trigger('change'); settle(el);
   return bindingLooksReal(el,v);
 }
 function vis(el){ var r=el.getBoundingClientRect(); return r.width>0&&r.height>0&&!el.disabled&&!el.hasAttribute('readonly'); }
 var BAD={checkbox:1,radio:1,button:1,submit:1,reset:1,hidden:1,file:1,image:1};
 function usable(f){
   if(!f) return false;
   /* Kendo numeric boxes carry TWO inputs: a k-formatted-value one that is
      what you see, marked aria-hidden, and the real one that holds the model.
      Writing to the pretty one changes the display and nothing else. */
   if(f.getAttribute&&f.getAttribute('aria-hidden')==='true') return false;
   if(f.tagName==='INPUT'&&BAD[(f.type||'').toLowerCase()]) return false;
   return kw(f)||widgetSpan(f)||vis(f);
 }
 function bestInput(host){
   /* Prefer the input Angular is bound to; fall back to the first usable one. */
   var all=host.querySelectorAll?host.querySelectorAll('input,select,textarea'):[];
   var i, f=null;
   for(i=0;i<all.length;i++){ if(!usable(all[i])) continue;
     if(all[i].getAttribute('ng-model')||all[i].getAttribute('k-ng-model')) return all[i];
     if(!f) f=all[i]; }
   return f;
 }
 function fieldByCaptionText(want){
   /* Neither "Claim Dependants" nor "State to be taxed in" has a <label> at
      all -- the caption is a bare text node inside the form-group, with the
      control beside it. Every other lookup here starts from a <label>, so
      those two fields were never findable by any of them. */
   var mine=document.getElementById('anspanel'), out=[];
   var w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT,null), n;
   while((n=w.nextNode())){
     if(!n.nodeValue||norm(n.nodeValue)!==want) continue;
     var host=n.parentElement;
     if(!host||(mine&&mine.contains(host))) continue;
     var grp=host.closest?(host.closest('.form-group')||host):host;
     var f=bestInput(grp)||nearInput(host);
     if(f&&out.indexOf(f)<0) out.push(f);
   }
   return out.length===1?out[0]:null;
 }
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
   var byText=fieldByCaptionText(want);
   if(byText) return byText;
   return null;
 }
 async function setVal(el,v){
   if(kendoSet(el,v)) return true;
   /* A <select> that Kendo has taken over is hidden and driven by the widget.
      Setting its .value directly moves the select and nothing else -- the
      widget never fires, so whatever ng-blur was supposed to copy across never
      runs. Only a select that is genuinely VISIBLE is a plain select. */
   if(widgetSpan(el)&&!(el.tagName==='SELECT'&&vis(el))){
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
   /* A plain box needs the blur and the ng hook just as much as a Kendo one:
      Apex copies the chosen item into the ...ID the form submits on ng-blur,
      and only the Kendo paths were doing it. */
   settle(el);
   return true;
 }
 function cleanRole(t){
   /* Every role in Apex is followed by a "?" help icon, and an exact match on
      the label text therefore matched nothing: Sales Rep was never ticked and
      page 1 refused to save with "At least one role must be assigned"
      (Megan, 2026-09-10). Compare on letters and digits only. */
   return norm(t).replace(/[^a-z0-9 ]+/g,' ').replace(/\s+/g,' ').trim();
 }
 function roleCaptions(el){
   /* The real radio is usually hidden behind a styled circle, so the caption
      can hang off any of these. Collect them all and compare each. */
   var out=[], l;
   if(el.id){ l=document.querySelector('label[for="'+CSS.escape(el.id)+'"]');
              if(l) out.push(l.innerText); }
   l=el.closest?el.closest('label'):null; if(l) out.push(l.innerText);
   if(el.getAttribute('aria-label')) out.push(el.getAttribute('aria-label'));
   if(el.value) out.push(el.value);
   if(el.nextElementSibling) out.push(el.nextElementSibling.innerText);
   if(el.parentElement) out.push(el.parentElement.innerText);
   return out;
 }
 function wantsRole(){
   return norm(document.body.innerText).indexOf('security roles')>=0;
 }
 function roleComplaint(){
   return norm(document.body.innerText)
     .indexOf('at least one role must be assigned')>=0;
 }
 function roleSection(){
   /* The container holding the Security Roles list, so a fallback click can
      never wander off into the rest of the page. */
   var els=document.querySelectorAll('h1,h2,h3,h4,h5,h6,legend,label,span,div'), i;
   for(i=0;i<els.length;i++){
     if(els[i].children.length) continue;
     if(cleanRole(els[i].textContent)!=='security roles') continue;
     /* The heading's parent is often the whole form, which would let a
        fallback click wander as far as a <option>Sales Rep</option> in the
        Position dropdown. Prefer the block that FOLLOWS the heading. */
     var after=els[i].nextElementSibling;
     if(after&&cleanRole(after.textContent).indexOf(%(role)s)>=0) return after;
     var par=els[i].parentElement;
     if(par&&par!==document.body&&par.tagName!=='HTML') return par;
     return after||par||els[i];
   }
   return null;
 }
 function ownText(el){
   /* The text of this element alone. "Sales Rep" sits beside a <b>?</b> help
      icon, so insisting on a childless element found nothing. */
   var t='', n;
   for(n=el.firstChild;n;n=n.nextSibling) if(n.nodeType===3) t+=n.nodeValue;
   return t;
 }
 function looksOn(el){
   if(!el) return false;
   if(el.getAttribute&&el.getAttribute('aria-checked')==='true') return true;
   return /(^|\s)(on|checked|selected|active|k-state-selected)(\s|$)/
     .test(String(el.className||''));
 }
 function roleTicked(){
   var rs=document.querySelectorAll('input[type=radio],input[type=checkbox]'), i, j, caps;
   for(i=0;i<rs.length;i++){
     if(!rs[i].checked) continue;
     caps=roleCaptions(rs[i]);
     for(j=0;j<caps.length;j++) if(cleanRole(caps[j])===%(role)s) return true;
   }
   return false;
 }
 function roleByClicking(){
   /* No input would take it, so click what a PERSON clicks. Apex draws each
      role as a styled circle; whether the real control underneath is an input
      at all is not something to guess at. Confined to the Security Roles
      section, and only elements that are their own leaf of text. */
   var sec=roleSection(); if(!sec) return false;
   var complained=roleComplaint();
   function won(el,before){
     /* Three ways to know it took, because which one Apex uses is not
        something to guess: a real input went checked, the control marked
        itself, or Apex stopped saying a role is missing. */
     if(roleTicked()) return true;
     if(looksOn(before)||looksOn(el)||looksOn(el.parentElement)) return true;
     if(complained&&!roleComplaint()) return true;
     return false;
   }
   var els=sec.querySelectorAll('*'), i, el, before;
   for(i=0;i<els.length;i++){
     el=els[i];
     if(cleanRole(ownText(el))!==%(role)s&&
        !(el.children.length===0&&cleanRole(el.textContent)===%(role)s)) continue;
     before=el.previousElementSibling;
     if(before){ try{ before.click(); }catch(e){} if(won(el,before)) return true; }
     try{ el.click(); }catch(e){} if(won(el,before)) return true;
     if(el.parentElement){ try{ el.parentElement.click(); }catch(e){}
       if(won(el,before)) return true; }
   }
   return false;
 }
 function roleShape(){
   /* What the Security Roles list is actually made of, for when none of the
      above works. One screenshot instead of another round of guessing. */
   var sec=roleSection();
   if(!sec) return 'no Security Roles section found';
   var els=sec.querySelectorAll('*'), i, out=[];
   for(i=0;i<els.length&&out.length<6;i++){
     if(els[i].children.length) continue;
     if(cleanRole(els[i].textContent).indexOf('sales')<0) continue;
     var e=els[i], chain=[], n=e, d=0;
     while(n&&n!==sec&&d<4){
       chain.push(n.tagName.toLowerCase()+
         (n.className?('.'+String(n.className).split(' ').slice(0,2).join('.')):''));
       n=n.parentElement; d++;
     }
     var sib=e.previousElementSibling;
     out.push(chain.join(' < ')+' | before: '+
       (sib? sib.tagName.toLowerCase()+
        (sib.className?('.'+String(sib.className).split(' ').slice(0,2).join('.')):'')+
        (sib.getAttribute&&sib.getAttribute('type')?'[type='+sib.getAttribute('type')+']':'')
        : '(none)'));
   }
   return out.length? out.join(' ;; ') : 'nothing reading "Sales Rep" in it';
 }
 function role(){
   var rs=document.querySelectorAll('input[type=radio],input[type=checkbox]');
   var i, j, caps;
   for(i=0;i<rs.length;i++){
     caps=roleCaptions(rs[i]);
     for(j=0;j<caps.length;j++){
       if(cleanRole(caps[j])!==%(role)s) continue;
       try{ rs[i].click(); }catch(e){}
       if(!rs[i].checked){
         /* click what a PERSON clicks -- the input itself may be hidden */
         var lab=(rs[i].id?document.querySelector('label[for="'+CSS.escape(rs[i].id)+'"]'):null)
                 ||(rs[i].closest?rs[i].closest('label'):null);
         if(lab) lab.click();
       }
       if(!rs[i].checked) rs[i].checked=true;
       rs[i].dispatchEvent(new Event('click',{bubbles:true}));
       rs[i].dispatchEvent(new Event('change',{bubbles:true}));
       ngApply(rs[i]);
       if(rs[i].checked) return true;
     }
   }
   /* Nothing that looks like an input took it. Apex still says the role is
      missing on a page it will not save, so try the visible control
      (Megan, 2026-09-10: "didn't pick role again" -- the first fix only ever
      met records TeleMapper had already ticked). */
   return roleByClicking();
 }
 function labelOf(el){
   /* the caption a person reads for this control, for naming it back */
   if(el.id){ var l=document.querySelector('label[for="'+CSS.escape(el.id)+'"]');
              if(l) return norm(l.textContent); }
   var box=el.closest?el.closest('.form-group,.col-md-6,div'):null;
   if(box){ var lb=box.querySelector('label'); if(lb) return norm(lb.textContent); }
   return (el.name||el.id||el.tagName).toLowerCase();
 }
 function invalidFields(){
   /* Apex answers a bad save with "The form is invalid" and names nothing.
      Angular knows exactly which controls it is unhappy with -- it stamps them
      ng-invalid -- so ask it, and hand back the captions. */
   var mine=document.getElementById('anspanel');
   var els=document.querySelectorAll('input.ng-invalid,select.ng-invalid,textarea.ng-invalid,.ng-invalid > input');
   var seen={}, out=[], i;
   for(i=0;i<els.length;i++){
     if(mine&&mine.contains(els[i])) continue;
     var n=labelOf(els[i]);
     if(!n||seen[n]) continue;
     seen[n]=1; out.push(n);
   }
   return out;
 }
 function pageName(){
   var u=(location.pathname||'').toLowerCase();
   if(u.indexOf('employment-record')>=0) return 'employment';
   if(u.indexOf('user-profile')>=0||u.indexOf('employee-profile')>=0) return 'profile';
   if(u.indexOf('bank-info')>=0||u.indexOf('tax')>=0) return 'tax';
   return '';
 }
 function fieldsHere(p){
   /* On an Apex page, ONLY that page's fields. Anywhere else (a test page, or
      a screen we don't recognise) fall back to a flat list if one was given --
      the scoping exists to stop cross-page caption collisions on Apex, not to
      make the button useless everywhere else. */
   var pg=pageName();
   if(pg&&p.pages) return p.pages[pg]||{};
   if(p.pages) return null;
   return p.fields||null;
 }
 async function fill(p){
   var done=[],miss=[],found=0,k;
   var set=fieldsHere(p);
   if(!set) return {done:[],miss:[],found:0,offpage:true};
   for(k in set){ var el=fieldFor(k);
     if(el){ found++;
       if(await setVal(el,set[k])) done.push(k); else miss.push(k+' (no matching option)'); }
     else miss.push(k); }
   if(role()){ done.push('Sales Rep role'); found++; }
   else if(wantsRole()) miss.push('Sales Rep role \u2014 '+roleShape());
   /* The answers given once in the setup form belong to this person wherever
      they are used. Only the whole-week run was reading them, so landing on
      page 2 by hand and pressing "Just this page" left Gender empty and Apex
      refused the save (Megan, 2026-09-10). */
   if(pageName()==='profile'){
     var g2=window.__ansGender[norm(p.name)];
     if(g2){ var gb2=genderBox(p);
       if(gb2&&await setVal(gb2,g2)){ done.push('Gender'); found++; }
       else miss.push('Gender'); }
   }
   if(pageName()==='tax'){
     var s2=window.__ansSSN[norm(p.name)];
     if(s2){ var bx2=ssnBoxes();
       if(bx2&&await setVal(bx2[0],s2)&&await setVal(bx2[1],s2)){
         done.push('Social'); found++; } }
   }
   /* `found` is boxes we LOCATED, which is not the same as boxes we filled.
      Without the difference, a page where every field was found but one value
      would not match got reported as "not an Apex form". */
   return {done:done,miss:miss,found:found};
 }
 var IDKEY=KEY+'.ids';
 function knownIds(){
   try{ return JSON.parse(localStorage.getItem(IDKEY)||'{}'); }catch(e){ return {}; }
 }
 function learnIds(){
   /* On the Pending list every row's Edit link carries the employee's id.
      Harvest them once and the panel can jump straight to each person after
      that -- finding 23 people by hand in a list is the slowest part of the
      whole job. */
   var map=knownIds(), links=document.querySelectorAll('a[href*="/employees/"]'), n=0, i;
   for(i=0;i<links.length;i++){
     var m=(links[i].getAttribute('href')||'').match(/\/employees\/(\d+)/);
     if(!m) continue;
     var row=links[i].closest('tr'); if(!row) continue;
     var cells=row.querySelectorAll('td'); if(cells.length<2) continue;
     var nm=norm(cells[0].textContent)+' '+norm(cells[1].textContent);
     if(!nm.trim()) continue;
     if(!map[nm.trim()]){ n++; }
     map[nm.trim()]=m[1];
   }
   try{ localStorage.setItem(IDKEY,JSON.stringify(map)); }catch(e){}
   return n;
 }
 function filterBoxes(){
   /* Tie each filter box to its COLUMN, through the table, instead of
      counting inputs in document order. Counting put the surname into the
      First Name box -- the screen showed "david" under First Name while the
      run reported David Silva as not found, with him sitting right there
      (Megan, 2026-09-10). */
   var heads=document.querySelectorAll('th'), lastTh=null, firstTh=null, i;
   for(i=0;i<heads.length;i++){
     var t=norm(heads[i].textContent);
     if(t==='last name'&&!lastTh) lastTh=heads[i];
     if(t==='first name'&&!firstTh) firstTh=heads[i];
   }
   if(!lastTh) return null;
   /* The column number has to be read off the header's OWN row. Its position
      in the page-wide list of th's is a different number the moment anything
      else on the screen uses a table. */
   function colOf(th){ var row=th.parentElement;
     return row? Array.prototype.indexOf.call(row.children,th) : -1; }
   var idx=colOf(lastTh), first=firstTh?colOf(firstTh):-1;
   if(idx<0) return null;
   var table=lastTh.closest?lastTh.closest('table'):null;
   if(!table) return null;
   var rows=table.querySelectorAll('tr'), r, cells, inp;
   for(r=0;r<rows.length;r++){
     cells=rows[r].querySelectorAll('th,td');
     if(cells.length<=idx) continue;
     inp=cells[idx].querySelector('input');
     if(!inp) continue;
     return {last: inp, lastIdx: idx, firstIdx: first,
             first: (first>=0&&cells.length>first)
                    ? cells[first].querySelector('input') : null};
   }
   return null;
 }
 function dataRows(){
   var rows=document.querySelectorAll('tr'), out=[], i, c;
   for(i=0;i<rows.length;i++){
     c=rows[i].querySelectorAll('td');
     if(c.length<2) continue;
     if(rows[i].querySelector('input')) continue;
     out.push(rows[i]);
   }
   return out;
 }
 function setBox(el,v){
   if(!el) return;
   el.value=v||'';
   el.dispatchEvent(new Event('input',{bubbles:true}));
   el.dispatchEvent(new Event('change',{bubbles:true}));
   ngApply(el);
 }
 async function settleFilter(f,given,surname){
   /* The rows repaint AFTER Apply Filters comes back. A fixed wait was reading
      the PREVIOUS person's rows: the screen showed "Russell" typed in the
      filter with Rosa Capel still listed underneath, so Russell was written
      down as absent while he was one repaint away (Megan, 2026-09-10).
      Wait until what is on screen agrees with what was typed. */
   var wantL=norm(surname), wantF=norm(given), waited=0, rows, i, c, ok;
   await sleep(500);
   while(waited<8000){
     rows=dataRows(); ok=true;
     for(i=0;i<rows.length;i++){
       c=rows[i].querySelectorAll('td');
       if(c.length<=f.lastIdx){ ok=false; break; }
       if(norm(c[f.lastIdx].textContent).indexOf(wantL)<0){ ok=false; break; }
       if(wantF&&f.firstIdx>=0&&c.length>f.firstIdx&&
          norm(c[f.firstIdx].textContent).indexOf(wantF)<0){ ok=false; break; }
     }
     /* An empty table settles too -- that is the answer "nobody by that name",
        and it is only reached after the first wait above. */
     if(ok) return true;
     await sleep(250); waited+=250;
   }
   return false;
 }
 function applyFilters(){
   var b=document.querySelectorAll('button,a'), i;
   for(i=0;i<b.length;i++){ if(norm(b[i].textContent).indexOf('apply filter')>=0){ b[i].click(); return true; } }
   return false;
 }
 function rowsById(){
   var out={}, links=document.querySelectorAll('a[href*="/employees/"]'), i;
   for(i=0;i<links.length;i++){
     var m=(links[i].getAttribute('href')||'').match(/\/employees\/(\d+)/);
     if(!m) continue;
     var row=links[i].closest('tr'); if(!row) continue;
     var c=row.querySelectorAll('td'); if(c.length<2) continue;
     out[(norm(c[0].textContent)+' '+norm(c[1].textContent)).trim()]=m[1];
   }
   return out;
 }
 async function filterTo(f,given,surname){
   setBox(f.first,given); setBox(f.last,surname);
   applyFilters();
   await settleFilter(f,given,surname);
 }
 async function lookupRow(f,p){
   /* Type the FIRST name as well as the last, so the filter lands on the exact
      person instead of everybody who shares a surname (Megan, 2026-09-10).
      Apex can hold a different first name for somebody -- a nickname, or a
      middle name sitting in the box -- and that would be a false miss, so the
      surname on its own is still tried before giving up on them. */
   var parts=norm(p.name).split(' ');
   var surname=p.find||parts[parts.length-1], given=parts[0];
   await filterTo(f,given,surname);
   var row=rowFor(p);
   if(row) return row;
   await filterTo(f,'',surname);
   return rowFor(p);
 }
 async function findEveryone(say){
   /* Clicking the button on each page of a five-page list to teach it where
      people are is exactly the kind of chore this is supposed to remove
      (Megan, 2026-09-09). The roster filters in-page, so it can look each
      person up itself. */
   var f=filterBoxes();
   if(!f){ say('No filter row on this page — open Roster then Employees, and the Pending tab.'); return; }
   var map=knownIds(), missing=[], present=0, absent=[], i;
   for(i=0;i<D.length;i++){ if(!idFor(D[i])) missing.push(D[i]); }
   if(!missing.length){ say('<b>All '+D.length+' found.</b> Ready to run the week.'); return; }
   for(i=0;i<missing.length;i++){
     var person=missing[i], want=norm(person.name);
     say('looking up '+person.name+' ('+(i+1)+' of '+missing.length+')…');
     var row=await lookupRow(f,person);
     var rows=rowsById(), key, hit=null;
     for(key in rows){ if(key===want){ hit=rows[key]; break; } }
     /* A real id if the row happens to carry a link, and otherwise nothing at
        all. Storing a placeholder here would have sent the run to
        /employees/?/edit -- the pre-flight is only allowed to REPORT. The run
        opens each person by clicking their Edit when it reaches them. */
     /* Decide presence HERE, while this person is the one being filtered for.
        Judging it afterwards against whatever rows happen to be on screen said
        22 of 23 were missing -- including Rosa, who was visible at the time. */
     if(hit){ map[want]=hit; try{ localStorage.setItem(IDKEY,JSON.stringify(map)); }catch(e){} }
     else if(row) present++;
     else absent.push(person.name);
   }
   setBox(f.first,''); setBox(f.last,''); applyFilters();
   await sleep(800);
   /* Name them. "5 not on the Pending tab" tells you there is a problem and
      nothing about which five, so it cannot be acted on (Megan, 2026-09-09).
      The list is what the loop actually failed to find, not a re-scan. */
   var still=absent;
   if(!still.length){ say('<b>All '+D.length+' found.</b> Ready to run the week.'); return; }
   say('<b style="color:#b00">Not on the Pending tab ('+still.length+'):</b><br>'+
       still.join('<br>')+
       '<div style="margin-top:6px"><a href="#" id="ansagain">look again</a> · '+
       'or add them in Apex and look again.</div>');
   var again=document.getElementById('ansagain');
   if(again) again.onclick=function(e){ e.preventDefault(); findEveryone(say); };
 }
 function idFor(p){
   var map=knownIds(), want=norm(p.name);
   if(map[want]) return map[want];
   var k; for(k in map){ if(k===want||k.indexOf(want)>=0||want.indexOf(k)>=0) return map[k]; }
   return null;
 }
 function go(id,tab){ location.href='/employees/'+id+'/edit/'+tab; }
 function ssnBoxes(){ var a=fieldFor('SSN')||fieldFor('Change SSN'),
                      b=fieldFor('Confirm SSN'); return (a&&b)?[a,b]:null; }
 function needGender(p){
   /* Ask whenever we are on the PROFILE page and the board did not supply a
      gender. This used to depend on FINDING the control first, so a lookup
      miss quietly removed the prompt and the operator only discovered the
      required field was empty when Apex refused the save. The question is
      "does this page want one", not "can I find the box". */
   if(pageName()!=='profile') return false;
   if(window.__ansGender[norm(p.name)]) return false;   /* already answered */
   var set=fieldsHere(p);
   return !(set&&set['Gender']);
 }
 function genderBox(p){ return fieldFor('Gender'); }
 function blueink(p){ return 'https://secure.blueink.com/dashboard/wall?search='+encodeURIComponent(p.find||p.name); }
 /* ------------- walking the whole week in one pass ----------------------
    Apex is an Angular ui-router app, so moving between tabs and between
    people happens IN-PAGE -- no reload, and a script survives all of it.
    That is what makes one pass over the week possible instead of 69 rounds
    of click-fill-save. Filling every field but leaving 69 Saves to a person
    was not saving anybody meaningful time (Megan, 2026-09-09).

    The Socials live in memory for the length of the run and are never
    written anywhere. */
 window.__ansSSN=window.__ansSSN||{};
 window.__ansGender=window.__ansGender||{};
 /* What is half-typed, kept apart from what is complete. Only a full nine
    digits is ever handed to Apex; the draft exists so the table can be drawn
    again without anybody retyping. */
 window.__ansDraft=window.__ansDraft||{};
 /* A gender is not a secret and it is a chore to re-answer, so it is kept.
    A Social is neither kept nor written down anywhere -- it lives in this
    tab, for this run, and goes when the tab does. */
 var GKEY=KEY+'.gender';
 try{ var gsav=JSON.parse(localStorage.getItem(GKEY)||'{}'), gk;
      for(gk in gsav){ if(!window.__ansGender[gk]) window.__ansGender[gk]=gsav[gk]; }
 }catch(e){}
 function injector(){
   try{ return angular.element(document.body).injector(); }catch(e){ return null; }
 }
 async function goSpa(path){
   var inj=injector();
   if(inj){
     try{
       var $l=inj.get('$location'), $r=inj.get('$rootScope');
       $r.$apply(function(){ $l.path(path); });
       await sleep(900);
       if((location.pathname||'').indexOf(path)>=0) return true;
     }catch(e){}
   }
   return false;      /* a reload would kill the run, so we do not do one */
 }
 function saveButton(){
   var b=document.querySelectorAll('button,a'), i;
   for(i=0;i<b.length;i++){ if(norm(b[i].textContent)==='save'&&vis(b[i])) return b[i]; }
   return null;
 }
 function shownValue(el){
   var w=kw(el);
   if(w&&w.text){ try{ return norm(String(w.text())); }catch(e){} }
   if(w&&w.value){ try{ return norm(String(w.value())); }catch(e){} }
   if(el.tagName==='SELECT'&&el.selectedIndex>=0)
     return norm(el.options[el.selectedIndex].text);
   return norm(el.value!==undefined&&el.value!==null?el.value:el.textContent);
 }
 function alreadyRight(p,which){
   /* Hands back the captions that do NOT already hold what we wanted. */
   var set=(p.pages||{})[which]||{}, k, off=[];
   for(k in set){
     var el=fieldFor(k);
     if(!el){ off.push(k); continue; }
     var want=norm(String(set[k])), got=shownValue(el);
     if(!want) continue;
     if(got.indexOf(want)<0&&want.indexOf(got)<0) off.push(k);
   }
   return off;
 }
 async function saveHere(){
   /* Apex reports a failed save with window.alert, which would stop a run
      dead behind a modal. Catch the text instead and hand it back. */
   var said=null, orig=window.alert;
   if(window.__ansNet) window.__ansNet.last=null;
   window.alert=function(m){ said=String(m||''); };
   try{
     var b=saveButton(); if(!b){ return 'no Save button on this page'; }
     b.click();
     var waited=0;
     while(waited<9000){ await sleep(300); waited+=300;
       if(said) break;
       var L=window.__ansNet&&window.__ansNet.last;
       if(L&&L.status>=400){ said='Apex refused it ('+L.status+')'; break; }
     }
   } finally { window.alert=orig; }
   return said;
 }
 async function doPage(p,which){
   var set=(p.pages||{})[which]||{}, done=[], miss=[], k;
   for(k in set){ var el=fieldFor(k);
     if(el&&await setVal(el,set[k])) done.push(k); else miss.push(k); }
   if(which==='profile'){
     var g=window.__ansGender[norm(p.name)];
     if(g){ var gb=genderBox(p); if(gb&&await setVal(gb,g)) done.push('Gender');
            else miss.push('Gender'); }
   }
   if(which==='tax'){
     var sec=window.__ansSSN[norm(p.name)];
     if(sec){ var bx=ssnBoxes();
       if(bx&&await setVal(bx[0],sec)&&await setVal(bx[1],sec)) done.push('Social');
       else miss.push('Social'); }
   }
   /* Security Roles is on the EMPLOYMENT record, and this was only ever
      attempting it on the tax tab -- so the whole-week run never ticked a role
      at all, and page 1 could not save. It read as fixed because the first
      record tried was one TeleMapper had already ticked (Megan, 2026-09-10:
      "didn't pick role again"). Ask the PAGE whether it wants one. */
   if(wantsRole()){
     if(role()) done.push('Sales Rep role');
     else miss.push('Sales Rep role \u2014 '+roleShape());
   }
   return {done:done,miss:miss};
 }
 function rowFor(person){
   var rows=document.querySelectorAll('tr'), i, c, nm;
   var want=norm(person.name), parts=want.split(' ');
   for(i=0;i<rows.length;i++){ c=rows[i].querySelectorAll('td');
     if(c.length<2) continue;
     nm=(norm(c[0].textContent)+' '+norm(c[1].textContent)).trim();
     if(nm===want) return rows[i]; }
   for(i=0;i<rows.length;i++){ c=rows[i].querySelectorAll('td');
     if(c.length<2) continue;
     nm=(norm(c[0].textContent)+' '+norm(c[1].textContent)).trim();
     if(nm.indexOf(parts[0])>=0&&nm.indexOf(parts[parts.length-1])>=0) return rows[i]; }
   return null;
 }
 function editControl(row){
   var els=row.querySelectorAll('a,button'), i;
   for(i=0;i<els.length;i++){ if(norm(els[i].textContent)==='edit') return els[i]; }
   return null;
 }
 async function openPerson(p){
   /* Do not read ids out of the page. The harvest looked for
      <a href="/employees/123/...">Edit</a> and the roster has NO such link --
      not one in the whole page -- so every person came back "not found" while
      sitting right there on screen. Filter to them, click their Edit, and read
      where the app lands. Nothing about the row's markup has to be guessed. */
   /* Already looking at the roster? Then do not route anywhere -- the filter
      row being on screen is the only thing that matters, and a needless route
      change is one more thing to go wrong. */
   var f=filterBoxes();
   if(!f){
     if(!(await goSpa('/roster'))) return null;
     await sleep(1000);
     f=filterBoxes();
   }
   var row=f? (await lookupRow(f,p)) : rowFor(p);
   if(!row) return null;
   var ed=editControl(row); if(!ed) return null;
   ed.click();
   var waited=0;
   while(waited<8000){
     await sleep(300); waited+=300;
     var m=(location.pathname||'').match(/\/employees\/(\d+)/);
     if(m){
       var map=knownIds(); map[norm(p.name)]=m[1];
       try{ localStorage.setItem(IDKEY,JSON.stringify(map)); }catch(e){}
       return m[1];
     }
   }
   return null;
 }
 /* exposed so the way in can be tested, and so a stuck run can be poked at
    from the console without re-reading this whole script */
 window.__ansOpen=openPerson;
 window.__ansAlreadyRight=alreadyRight;
 window.__ansDoPage=doPage;
 window.__ansRoleSection=roleSection;
 async function runPerson(p,say){
   var id=idFor(p);
   if(!id){ say(p.name+': finding them…'); id=await openPerson(p); }
   if(!id){ say(p.name+': not on the Pending list — skipped'); return false; }
   var tabs=[['employment','/employees/'+id+'/edit/employment-record'],
             ['profile','/employees/'+id+'/edit/user-profile'],
             ['tax','/employees/'+id+'/edit/bank-info']];
   for(var t=0;t<tabs.length;t++){
     if(!(await goSpa(tabs[t][1]))){
       say(p.name+': could not move to '+tabs[t][0]+' without a reload — stopped');
       return false;
     }
     await sleep(800);
     var r=await doPage(p,tabs[t][0]);
     var err=await saveHere();
     if(err==='no Save button on this page'){
       /* Apex maintains the employment record through TeleMapper for these
          people and offers no Save at all. Stopping the whole week on that is
          wrong when the page already holds what we wanted -- but moving on
          without looking would be worse, so look (Megan, 2026-09-10). */
       var off=alreadyRight(p,tabs[t][0]);
       if(!off.length){
         say(p.name+' · '+tabs[t][0]+': already correct, and Apex offers no '+
             'Save here — moved on');
         continue;
       }
       err='no Save button, and these are not right: '+off.join(', ');
     }
     if(err){ say(p.name+' · '+tabs[t][0]+': '+err+
                  (r.miss.length?' — missed '+r.miss.join(', '):'')); return false; }
     say(p.name+' · '+tabs[t][0]+': saved'+
         (r.miss.length?' — missed '+r.miss.join(', '):''));
   }
   return true;
 }

 var old=document.getElementById('anspanel'); if(old) old.remove();
 var p=D[Math.min(I,D.length-1)];
 var box=document.createElement('div'); box.id='anspanel';
 box.style.cssText='position:fixed;top:14px;right:14px;z-index:2147483647;background:#fff;border:2px solid #0F766E;border-radius:10px;padding:14px 16px;font:14px -apple-system,Helvetica,sans-serif;box-shadow:0 6px 24px rgba(0,0,0,.25);max-width:330px';
 var found=learnIds();
 var ssn=ssnBoxes(), gnd=needGender(p), nav=idFor(p);
 /* On somebody's record, name them. On the roster -- which is where the
    whole-week run is started from -- naming one person reads as though the
    button is about to do only them (Megan, 2026-09-10). */
 /* Hide the per-person controls only where we can POSITIVELY see a roster --
    the filter row, or the roster url. Keying off "can I name this page" hid
    them on every screen the button does not recognise, which took away the
    "Just this page" escape hatch exactly where somebody would need it. */
 var RUNNING=false;
 box.innerHTML='<div id="anshd" style="font-weight:700;font-size:16px"></div>'+
   '<div id="ansub" style="color:#555;margin:2px 0 4px"></div>'+
   '<div id="ansage" style="font-size:12px;font-weight:600"></div>'+
   (gnd?'<div style="margin-bottom:8px"><div style="font-size:12px;color:#555">Gender <span style="color:#b00">(required, not on the board)</span></div>'+
        '<select id="ansgender" style="width:100%%;padding:6px;font-size:15px">'+
        '<option value="">Pick one</option><option>Female</option><option>Male</option></select></div>':'')+
   (ssn?'<div style="margin-bottom:8px"><div style="font-size:12px;color:#555">Social Security number</div>'+
        '<input id="ansssn" type="password" style="width:100%%;padding:6px;font-size:15px">'+
        '<div style="margin-top:6px"><a href="'+blueink(p)+'" target="_blank" rel="noopener" id="ansbi" style="font-size:12px;color:#0F766E">Open their Blue Ink packet →</a>'+
        '<span style="font-size:11px;color:#888"> (I-9 → Quick View)</span></div></div>':'')+
   (nav?'<div style="margin-bottom:8px;font-size:12px">'+
        '<a href="#" id="ansg1">1 Employment</a> · <a href="#" id="ansg2">2 Profile</a>'+
        ' · <a href="#" id="ansg3">3 Tax</a></div>':
        '<div id="anshnt" style="margin-bottom:8px;font-size:11px;color:#b00">Click this once on the '+
        '<b>Pending</b> list and it will learn where everyone is, then jump you straight to them.</div>')+
   '<button id="ansrun" style="background:#0F766E;color:#fff;border:0;border-radius:6px;padding:9px 14px;font-size:14px;font-weight:700;cursor:pointer;width:100%%;margin-bottom:6px">Run the whole week</button>'+
   /* Both of these are about ONE person, so they only belong on that person's
      record. On the roster they read as clutter you have to think about
      (Megan, 2026-09-10). */
   '<span id="anspr">'+
   '<button id="ansfill" style="background:#eee;border:0;border-radius:6px;padding:8px 12px;font-size:13px;cursor:pointer">Just this page</button> '+
   '<button id="ansnext" style="background:#eee;border:0;border-radius:6px;padding:8px 12px;cursor:pointer">Saved \u2192 next</button></span>'+
   '<div id="ansout" style="margin-top:9px;font-size:12px;color:#333"></div>'+
   '<button id="ansnew" style="background:#fff;border:1px solid #0F766E;'+
   'color:#0F766E;border-radius:6px;padding:8px 12px;font-size:13px;'+
   'cursor:pointer;width:100%%;margin-top:6px">Load a different setup</button>'+
   '<div style="margin-top:8px"><a href="#" id="anserr" style="font-size:11px;color:#b00">what did Apex say?</a> · <a href="#" id="ansreset" style="font-size:11px;color:#888">start the week again</a></div>';
 document.body.appendChild(box);
 function refreshChrome(){
   /* The panel is built once and the app never reloads, so anything decided at
      build time goes stale the moment the run moves. It sat on the roster with
      one person's name at the top saying "2 of 23" while the line below it was
      looking up number 4 (Megan, 2026-09-10). Name a person only while that
      person's record is the thing on screen. */
   var path=(location.pathname||'');
   var here=(/\/roster(\/|$)/.test(path)||!!filterBoxes());
   /* The filter row vanishes for a moment every time Angular repaints the
      table, and re-deciding on that flickers the caption while a lookup runs.
      Same page, same answer. */
   if(window.__ansWas&&window.__ansWas.path===path) here=window.__ansWas.here||here;
   window.__ansWas={path:path,here:here};
   var list=(here||RUNNING);
   var h=document.getElementById('anshd'); if(!h) return;
   var head=RUNNING? 'Running the week \u00b7 %(week)s'
     : (here? 'Ready to run \u00b7 %(week)s' : p.name);
   if(h.textContent!==head) h.textContent=head;
   /* Which setup is loaded, in the one place it will be looked at. The
      bookmark runs whatever was last pasted, so "is this this week's list?"
      has to be answerable without clicking anything (Megan, 2026-09-10). */
   var sub=(list
     ? D.length+' new starts'+(I? ' \u00b7 '+I+' done already':'')
     : (I+1)+' of '+D.length+' \u00b7 %(week)s')+
     ' \u00b7 board read '+BUILD;
   var sb=document.getElementById('ansub');
   if(sb.textContent!==sub) sb.textContent=sub;
   /* This list is a SNAPSHOT of the New Starts box, taken when the setup was
      generated. The button cannot re-read a Google Sheet from inside Apex, so
      the only honest thing it can do is say how old the snapshot is and when
      that is old enough to matter (Megan, 2026-09-10). */
   var age=document.getElementById('ansage');
   if(age){
     var hrs=(Date.now()-BUILT_AT)/3600000, msg='', col='';
     if(hrs>=12){ msg='This list was read off the board '+Math.round(hrs)+
       ' hours ago. Rebuild it on the Hub before running \u2014 anyone added or '+
       'marked T since is not in it.'; col='#b00'; }
     else if(hrs>=3){ msg='Read off the board '+Math.round(hrs)+
       ' hours ago. Rebuild it if the board has moved since.'; col='#a56a00'; }
     if(age.textContent!==msg){ age.textContent=msg; age.style.color=col;
       age.style.margin=msg?'6px 0':''; }
   }
   var want=list?'none':'';
   var per=document.getElementById('anspr');
   if(per&&per.style.display!==want) per.style.display=want;
   var hint=document.getElementById('anshnt');
   if(hint&&hint.style.display!==want) hint.style.display=want;
 }
 refreshChrome();
 /* Every load of a setup started ANOTHER ticker, and the old one kept
    writing to the new panel -- so the caption alternated between what the
    previous script thought and what this one does, twice a second
    (Megan, 2026-09-10: "it's like blinking now with when it was built").
    One ticker, and the previous one goes. */
 /* clearInterval only reaches tickers this code started. A script loaded
    before that existed keeps its own going until the page reloads -- which is
    why the captions kept alternating even after the fix. So the panel's parts
    are named afresh: the old ticker looks for the names it knew, finds
    nothing, and gives up on its own. */
 if(window.__ansTick) clearInterval(window.__ansTick);
 window.__ansTick=setInterval(refreshChrome,700);
 if(nav){
   document.getElementById('ansg1').onclick=function(e){e.preventDefault();go(nav,'employment-record');};
   document.getElementById('ansg2').onclick=function(e){e.preventDefault();go(nav,'user-profile');};
   document.getElementById('ansg3').onclick=function(e){e.preventDefault();go(nav,'bank-info');};
 }
 /* The Pending list is PAGINATED. One click only sees the rows on screen, so
    with the week spread over five pages the run would stop at the first person
    it has no id for. Say how many are still missing, plainly. */
 var lack=0, li;
 for(li=0;li<D.length;li++){ if(!idFor(D[li])) lack++; }
 if(found||lack){
   document.getElementById('ansout').innerHTML=
     (found?'Learned '+found+' more. ':'')+
     (lack? '<b style="color:#b00">'+lack+' of '+D.length+' still not found.</b> '+
            '<a href="#" id="ansfind">Find them all for me</a> '+
            '(it looks each one up by surname on this list).'
          : '<b>All '+D.length+' found.</b> Ready to run the week.');
   var tell=function(m){ document.getElementById('ansout').innerHTML=m; };
   var fb=document.getElementById('ansfind');
   if(fb) fb.onclick=function(e){ e.preventDefault(); findEveryone(tell); };
   /* The lookup used to start the moment the panel opened, which meant
      watching it grind through 23 surnames before you could do anything.
      It is the first step of the RUN now: fill the form, then it goes
      (Megan, 2026-09-10). The link is still here to do it early on purpose. */
 }
 document.getElementById('ansrun').onclick=async function(){
   /* One form for the whole week, then one pass. The alternative -- filling
      every field and leaving a person to click Save 69 times -- was not
      saving anybody meaningful time. */
   var needG=[], i;
   for(i=0;i<D.length;i++){
     var pp=D[i], has=(pp.pages&&pp.pages.profile&&pp.pages.profile.Gender);
     needG.push({n:pp.name,g:!has});
   }
   var w=document.createElement('div'); w.id='anssetup';
   w.style.cssText='position:fixed;inset:0;z-index:2147483647;background:rgba(0,0,0,.45);overflow:auto;padding:30px';
   var rows='', pickOpts='';
   for(i=0;i<D.length;i++)
     pickOpts+='<option value="'+i+'"'+(i===Math.min(I,D.length-1)?' selected':'')+
       '>'+D[i].name+'</option>';
   /* Everything already answered comes BACK into the form. Nineteen Socials
      and nineteen genders were typed in, the run stopped on the first person,
      and restarting showed a blank table -- so it read as though the lot had
      been thrown away and had to be done again (Megan, 2026-09-10). */
   function opt(v,cur){ return '<option'+(v===cur?' selected':'')+'>'+v+'</option>'; }
   for(i=0;i<D.length;i++){
     var gh=window.__ansGender[norm(D[i].name)]||'';
     var sh=window.__ansSSN[norm(D[i].name)]||window.__ansDraft[norm(D[i].name)]||'';
     rows+='<tr><td style="padding:4px 8px">'+(i+1)+'</td>'+
       '<td style="padding:4px 8px">'+D[i].name+'</td>'+
       '<td style="padding:4px 8px">'+(needG[i].g?
         '<select data-g="'+i+'"><option value="">\u2014</option>'+
         opt('Female',gh)+opt('Male',gh)+'</select>'
         :'<span style="color:#888">on the board</span>')+'</td>'+
       '<td style="padding:4px 8px"><input data-s="'+i+'" type="password" size="12" '+
       'autocomplete="off" value="'+sh+'"> '+
       /* Opens their signed W-4 in the pane beside this table. Searching Blue
          Ink, opening the envelope and finding Quick View, 23 times over, is
          the slow part -- the document and the box belong on one screen
          (Megan, 2026-09-10). */
       '<a href="#" data-doc="'+i+'" style="font-size:11px;color:#0F766E">'+
       'packet</a></td></tr>';
   }
   w.innerHTML='<div style="background:#fff;max-width:1500px;margin:0 auto;border-radius:12px;padding:22px;font:14px -apple-system,Helvetica,sans-serif;display:flex;gap:18px">'+
     '<div style="flex:1;min-width:420px;max-height:82vh;overflow:auto">'+
     '<div style="font-size:20px;font-weight:700">Set up %(week)s</div>'+
     '<div style="color:#555;margin:4px 0 14px">Fill these once. Everything else '+
     'comes from Blue Ink and the board. Genders are remembered. Socials are '+
     'held in this tab only, for this run, and are never written down -- so '+
     'do not reload the page until the run is done.</div>'+
     '<table style="width:100%%;border-collapse:collapse;font-size:13px">'+
     '<tr><th></th><th style="text-align:left">Name</th><th style="text-align:left">Gender</th>'+
     '<th style="text-align:left">Social</th></tr>'+rows+'</table>'+
     '<div id="anssnwarn" style="margin-top:10px;font-size:13px;color:#b00"></div>'+
     '<div style="margin-top:16px"><button id="ansgo" style="background:#0F766E;color:#fff;border:0;border-radius:8px;padding:11px 22px;font-weight:700;cursor:pointer">Start the run</button> '+
     '<button id="anstest" style="background:#fff;border:1px solid #0F766E;'+
     'color:#0F766E;border-radius:8px;padding:11px 18px;font-weight:700;'+
     'cursor:pointer">Try one person</button> '+
     '<select id="anspick" style="font:inherit;padding:10px 8px;'+
     'border-radius:8px;border:1px solid #ccc">'+pickOpts+'</select> '+
     '<button id="anscancel" style="background:#eee;border:0;border-radius:8px;padding:11px 18px;cursor:pointer">Cancel</button> '+
     '<button id="ansclear" style="background:#fff;border:1px solid #b00;'+
     'color:#b00;border-radius:8px;padding:11px 18px;cursor:pointer">Clear '+
     'all answers</button>'+
     '<div style="font-size:12px;color:#666;margin-top:8px">'+
     '<b>Try one person</b> does whoever is picked beside it and stops \u2014 so '+
     'a fault costs one row instead of nineteen. <b>Start the run</b> goes '+
     'straight through everybody, three tabs each, without stopping to ask. '+
     'Anyone left blank is still filled, just without a Social.</div></div>'+
     '</div>'+
     '<div style="flex:1.2;min-width:420px;display:flex;flex-direction:column">'+
     '<div id="ansdocname" style="font-size:13px;color:#555;margin-bottom:6px">'+
     'Click <b>packet</b> beside a name and their signed W-4 opens here.</div>'+
     '<iframe id="ansdoc" style="flex:1;min-height:70vh;border:1px solid #ddd;'+
     'border-radius:8px;background:#fafafa"></iframe></div>'+
     '</div>';
   document.body.appendChild(w);
   /* Warm Blue Ink up straight away, in the tab the packet links will reuse,
      so the first click is not also paying for the dashboard booting. */
   var docs=w.querySelectorAll('[data-doc]'), dq;
   for(dq=0;dq<docs.length;dq++) docs[dq].onclick=function(e){
     e.preventDefault();
     var k=+this.getAttribute('data-doc'), person=D[k];
     var frame=document.getElementById('ansdoc'), nm=document.getElementById('ansdocname');
     if(person.doc){ frame.src=person.doc;
       nm.innerHTML='<b>'+person.name+'</b> \u2014 signed W-4'; }
     else { frame.removeAttribute('src');
       nm.innerHTML='<b>'+person.name+'</b> \u2014 no signed packet. '+
         '<a href="'+blueink(person)+'" target="blueinkpacket">look in Blue Ink</a>'; }
     var box=w.querySelector('[data-s="'+k+'"]'); if(box) box.focus();
   };
   /* Hold each answer AS IT IS TYPED. Capturing only on "Start the run" meant
      Cancel -- or anything that redrew the panel -- threw away nineteen
      Socials and nineteen genders (Megan, 2026-09-10). */
   function ssnProblems(){
     /* Names only. The numbers are compared here and never leave here --
        nothing about a Social is shown, logged or stored (Megan, 2026-09-10:
        "there should also be some kind of alert here if any of the socials
        are the exact same since we can't see them"). */
     var byVal={}, k, i, out={dups:[], bad:[]};
     for(i=0;i<D.length;i++){
       var nm=norm(D[i].name), v=window.__ansSSN[nm];
       var draft=(window.__ansDraft[nm]||'').replace(/-/g,'');
       if(!v){ if(draft) out.bad.push(D[i].name); continue; }
       (byVal[v]=byVal[v]||[]).push(D[i].name);
     }
     for(k in byVal){ if(byVal[k].length>1) out.dups.push(byVal[k]); }
     return out;
   }
   function showProblems(){
     var box=document.getElementById('anssnwarn'); if(!box) return;
     var pr=ssnProblems(), bits=[], i;
     for(i=0;i<pr.dups.length;i++)
       bits.push('<b>Same Social typed for '+pr.dups[i].join(' and ')+'.</b>');
     if(pr.bad.length)
       bits.push('Not nine digits yet: '+pr.bad.join(', ')+'.');
     box.innerHTML=bits.join('<br>');
   }
   var keepG=w.querySelectorAll('[data-g]'), keepS=w.querySelectorAll('[data-s]'), kq;
   for(kq=0;kq<keepG.length;kq++) keepG[kq].onchange=function(){
     var nm=norm(D[+this.getAttribute('data-g')].name);
     if(this.value) window.__ansGender[nm]=this.value; else delete window.__ansGender[nm];
     try{ localStorage.setItem(GKEY,JSON.stringify(window.__ansGender)); }catch(e){}
   };
   for(kq=0;kq<keepS.length;kq++) keepS[kq].oninput=function(){
     var nm=norm(D[+this.getAttribute('data-s')].name);
     var v=(this.value||'').replace(/-/g,'');
     window.__ansDraft[nm]=this.value||'';
     if(/^\d{9}$/.test(v)) window.__ansSSN[nm]=v; else delete window.__ansSSN[nm];
     showProblems();
   };
   showProblems();
   document.getElementById('ansclear').onclick=function(){
     /* On purpose, and only on purpose. Everything else about this form now
        holds on to what was typed, so there has to be a way to say no. */
     if(!confirm('Clear every gender and Social typed in here?')) return;
     window.__ansSSN={}; window.__ansGender={}; window.__ansDraft={};
     try{ localStorage.removeItem(GKEY); }catch(e){}
     var cg=w.querySelectorAll('[data-g]'), cs=w.querySelectorAll('[data-s]'), cq;
     for(cq=0;cq<cg.length;cq++) cg[cq].value='';
     for(cq=0;cq<cs.length;cq++) cs[cq].value='';
   };
   document.getElementById('anscancel').onclick=function(){ w.remove(); };
   async function begin(onlyOne){
     var pr=ssnProblems(), pi;
     if(pr.dups.length){
       var who=[]; for(pi=0;pi<pr.dups.length;pi++) who.push(pr.dups[pi].join(' and '));
       alert('The same Social is typed for '+who.join('; ')+'.\n\nTwo people '+
             'cannot share one, so one of them is off. Fix it before starting.');
       return;
     }
     if(pr.bad.length){
       alert('Not a full nine digits: '+pr.bad.join(', ')+'.\n\nApex will '+
             'refuse the save, so finish or clear those first.');
       return;
     }
     /* Read the picker while the form is still HERE -- it was being read
        after the form had been removed, so it always fell back to the top
        of the list. */
     var from=I, stop=D.length;
     if(onlyOne){
       var pk=document.getElementById('anspick');
       from=pk? +pk.value : I;
       stop=from+1;
       /* Running a person with nothing answered just walks into Apex refusing
          the save. Say which piece is missing and let it be a choice
          (Megan, 2026-09-10: "it didn't stop even though I didn't enter in
          any info and it didn't let me select who"). */
       var who=D[from], nm2=norm(who.name), lack=[];
       if(!window.__ansGender[nm2]&&!((who.pages||{}).profile||{})['Gender'])
         lack.push('gender');
       if(!window.__ansSSN[nm2]) lack.push('Social');
       if(lack.length&&!confirm(who.name+' has no '+lack.join(' and ')+' entered.'+
           '\n\nApex will refuse to save '+(lack.length>1?'those pages':'that page')+
           '. Try anyway?')) return;
     }
     var gs=w.querySelectorAll('[data-g]'), ss=w.querySelectorAll('[data-s]'), j;
     for(j=0;j<gs.length;j++){ if(gs[j].value)
       window.__ansGender[norm(D[+gs[j].getAttribute('data-g')].name)]=gs[j].value; }
     try{ localStorage.setItem(GKEY,JSON.stringify(window.__ansGender)); }catch(e){}
     for(j=0;j<ss.length;j++){ var v=(ss[j].value||'').replace(/-/g,'');
       if(/^\d{9}$/.test(v)) window.__ansSSN[norm(D[+ss[j].getAttribute('data-s')].name)]=v;
       ss[j].value=''; }
     /* The drafts have served their purpose; the complete ones are held. */
     window.__ansDraft={};
     w.remove();
     var log=[], out=document.getElementById('ansout');
     function say(m){ log.push(m); out.innerHTML=log.slice(-9).join('<br>'); }
     /* NO pre-sweep. It filtered to all nineteen, then the run filtered to
        each of them again -- the same search twice over, in front of somebody
        watching (Megan, 2026-09-10). The sweep could never save the second
        one either: it only remembers an id when the row carries an
        /employees/ link, and Apex's roster has none, so every person was
        looked up from scratch when their turn came anyway. Whoever is missing
        is named at the end, from the run itself. The "Find them all for me"
        link is still there to check the list before starting, on purpose. */
     RUNNING=true; refreshChrome();
     for(j=from;j<stop;j++){
       say('<b>'+D[j].name+'</b> ('+(j+1)+' of '+D.length+')…');
       var ok=await runPerson(D[j],say);
       if(!ok){ say('<b style="color:#b00">Stopped.</b> Fix that one, then press '+
                    'Run again — it picks up from here.'); break; }
       if(j===I){ I=j+1; try{ localStorage.setItem(KEY,String(I)); }catch(e){} }
       /* Trying one person is a check, not a run: say what happened and get
          out of the way. Asking "carry on?" would be asking the question the
          button already answered (Megan, 2026-09-10: filling in nineteen
          Socials to find out the first record fails is a waste of time). */
       if(onlyOne){ say('<b>'+D[j].name+' is done, all three tabs.</b> Open the '+
                        'record and check it, then Run the whole week.'); break; }
       /* No prompt in the middle. "Try one person" IS the checkpoint now, and
          asking again after number one only stands between the operator and
          the other eighteen (Megan, 2026-09-10: "it should just automatically
          move through the 3 pages of each person and nav to the next person
          automatically"). */
     }
     RUNNING=false; refreshChrome();
   }
   document.getElementById('ansgo').onclick=function(){ return begin(false); };
   document.getElementById('anstest').onclick=function(){ return begin(true); };
 };
 document.getElementById('ansfill').onclick=async function(){
   document.getElementById('ansout').innerHTML='filling...';
   var r=await fill(p);
   /* Nothing matched at all = not an Apex form. Saying so beats a wall of red
      listing every field the page was never going to have, which is what it
      did the first time somebody clicked it on the wrong tab. NOTE: block
      comments only in here -- build_js collapses this to ONE line, so a
      line comment would swallow the entire rest of the script. */
   if(r.offpage){
     document.getElementById('ansout').innerHTML=
       '<b>Nothing on this page belongs to '+p.name+'.</b><br>Open one of '+
       'their three tabs: Employment Record, User Profile \u0026 Account, or '+
       'Tax \u0026 Bank Information.';
     return;
   }
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
     else msg+='; <span style="color:#b00">gender would not set — '+
       (gb?TRACE.join(' / '):'no Gender box found')+'</span>'; }
   else if(gnd) msg+='<br><span style="color:#b00">Gender is required and '+
     'still empty — pick one above and Fill again, or Apex will refuse to '+
     'save this page.</span>';
   var s=document.getElementById('ansssn');
   if(s&&s.value){ var b=ssnBoxes(); if(b){ await setVal(b[0],s.value); await setVal(b[1],s.value); s.value=''; msg+='; Social entered'; } }
   if(r.miss.length) msg+='<br><span style="color:#b00">Not found here: '+r.miss.join(', ')+'</span>'+
     ' <a href="#" id="answhy" style="font-size:11px">why?</a>';
   var bad=invalidFields();
   if(bad.length) msg+='<br><span style="color:#b00">Apex still says these are '+
     'invalid: '+bad.join(', ')+'</span>';
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
       out.push('text in: '+chain.join(' \u003c ')+'<br>parent kids: '+sibs.join(', '));
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
   box.remove();
   if(I>=D.length){ alert('That was the last one.'); return; }
   var nid=idFor(D[I]);
   if(nid){ go(nid,'employment-record'); }        /* straight to the next person */
   else alert('Next: '+D[I].name+'\n\nOpen their record and click the button again.');
 };
 document.getElementById('ansnew').onclick=function(e){
   if(e&&e.preventDefault) e.preventDefault();
   /* Hand back to the loader. This is how a fix reaches somebody now: the
      bookmark never changes, the setup behind it does. */
   var pan=document.getElementById('anspanel'); if(pan) pan.remove();
   if(window.__ansPaste) window.__ansPaste();
   else alert('Click Fill Apex again and paste the new setup.');
 };
 document.getElementById('anserr').onclick=function(e){ e.preventDefault();
   var L=window.__ansNet&&window.__ansNet.last;
   document.getElementById('ansout').innerHTML = L
     ? '<b>'+L.status+'</b> '+String(L.url).slice(0,70)+
       '<div style="font-size:11px;white-space:pre-wrap;max-height:180px;overflow:auto;'+
       'background:#f6f6f6;padding:6px;margin-top:4px">'+
       String(L.body).replace(/</g,'\u0026lt;')+'</div><div style="font-size:11px">screenshot this</div>'
     : 'Nothing failed yet. Click Save in Apex first, then come back here.';
 };
 document.getElementById('ansreset').onclick=function(e){ e.preventDefault();
   try{ localStorage.setItem(KEY,'0'); }catch(err){} box.remove(); alert('Back to the first person.'); };
})();
"""


def _now_ms() -> int:
    import datetime as _dt
    return int(_dt.datetime.now().timestamp() * 1000)


def _now_stamp() -> str:
    import datetime as _dt
    return _dt.datetime.now().strftime("%b %d %H:%M")


def _guard(out: str) -> str:
    """A bookmarklet is served inside an href, and the browser DECODES HTML
    entities before running it. A single "&#39;" turned into a real apostrophe
    inside a single-quoted string -- a syntax error, and the whole script
    silently did nothing when clicked. Unicode escapes survive; entities must
    never appear.
    """
    import re as _re
    # Named entities only from the ones a browser actually decodes here, plus
    # numeric. A loose [a-z]+ pattern matched "&&n;" in `for(var k=0;k<3&&n;`.
    bad = _re.findall(r"&(?:#\d+|amp|lt|gt|quot|apos|nbsp);", out)
    if bad:
        raise RuntimeError(
            "the bookmarklet contains HTML entities, which the browser will "
            f"decode and break: {sorted(set(bad))[:5]}")
    return out


_STUB = r"""
(function(){
 /* The LOADER. This is the thing that gets bookmarked, and it is the only
    part that must never change: everything real lives under CODEKEY in this
    browser and arrives by paste. A saved bookmarklet freezes whatever was
    inside it, so shipping a fix used to mean asking for the bookmark to be
    deleted, re-copied and re-dragged -- which happened four times in one
    afternoon, and three of those the old button was still what ran
    (Megan, 2026-09-10). */
 var CODEKEY='apexNewStarts.code';
 function panel(msg){
   var old=document.getElementById('ansload'); if(old) old.remove();
   var b=document.createElement('div'); b.id='ansload';
   b.style.cssText='position:fixed;top:14px;right:14px;z-index:2147483647;'+
     'background:#fff;border:2px solid #0F766E;border-radius:10px;'+
     'padding:14px 16px;font:14px -apple-system,Helvetica,sans-serif;'+
     'box-shadow:0 6px 24px rgba(0,0,0,.25);width:320px';
   b.innerHTML='<div style="font-weight:700;font-size:16px">Load this week</div>'+
     '<div style="color:#555;margin:4px 0 8px;font-size:12px">'+msg+'</div>'+
     '<textarea id="ansblob" style="width:100%;height:64px;font-size:11px"></textarea>'+
     '<div style="margin-top:8px">'+
     '<button id="ansloadgo" style="background:#0F766E;color:#fff;border:0;'+
     'border-radius:6px;padding:9px 14px;font-weight:700;cursor:pointer">Load it</button> '+
     '<button id="ansloadno" style="background:#eee;border:0;border-radius:6px;'+
     'padding:9px 12px;cursor:pointer">Cancel</button></div>'+
     '<div id="ansloadmsg" style="margin-top:8px;font-size:12px;color:#b00"></div>';
   document.body.appendChild(b);
   document.getElementById('ansloadno').onclick=function(){ b.remove(); };
   document.getElementById('ansloadgo').onclick=function(){
     var t=(document.getElementById('ansblob').value||'').trim();
     if(t.indexOf('javascript:')===0) t=t.slice(11);
     var say=document.getElementById('ansloadmsg');
     if(t.length<2000){
       say.textContent='That is not the setup. On the Fill Apex page click '+
         'Copy this week\u0027s setup, then paste here.'; return; }
     try{ localStorage.setItem(CODEKEY,t); }
     catch(e){ say.textContent='This browser would not store it: '+e.message; return; }
     b.remove(); run();
   };
   document.getElementById('ansblob').focus();
 }
 /* The loaded script offers "load a new setup"; this is what it calls. */
 window.__ansPaste=function(){
   try{ localStorage.removeItem(CODEKEY); }catch(e){}
   panel('Paste the new setup here.');
 };
 function run(){
   var c=null; try{ c=localStorage.getItem(CODEKEY); }catch(e){}
   if(!c){ panel('On the <b>Fill Apex</b> page click <b>Copy this week\u0027s '+
     'setup</b>, then paste it here. Only needed when the week changes.'); return; }
   /* Apex serves no Content-Security-Policy, so this is allowed to run. */
   try{ (new Function(c))(); }
   catch(e){ panel('The saved setup would not run ('+e.message+'). '+
     'Paste a fresh one.'); }
 }
 run();
})()
"""


def build_stub() -> str:
    """The bookmarklet that gets saved ONCE and never again.

    It carries no report logic and no data -- only enough to run whatever was
    last pasted in. Every fix and every new week then ships through the paste
    that already happened weekly, instead of through a re-drag that kept not
    happening.
    """
    return _guard("javascript:" + " ".join(_STUB.split()))


def build_js(people=None, week: str = "", build: str = "") -> str:
    """The bookmarklet.

    With `people` it embeds them (what the tests use). Without, it is CODE ONLY
    and reads the week's list out of localStorage -- which is what the page
    ships, so the bookmark is saved once and never again. A saved bookmarklet
    freezes whatever was inside it, so carrying the data meant every change to
    either the data or the code cost a delete, a copy and a re-drag.
    """
    js = _JS % {"data": json.dumps(people, separators=(",", ":"))
                        if people is not None else "null",
                "week": week.replace("'", ""),
                "build": (build or _now_stamp()).replace("'", ""),
                "built_at": str(int(_now_ms())),
                "role": json.dumps(SECURITY_ROLE_LABEL.lower())}
    return _guard("javascript:" + " ".join(js.split()))


def data_json(people: List[Dict]) -> str:
    """The week's list, for the page's copy button."""
    return json.dumps(people, separators=(",", ":"))


def rows_for(values: Dict[str, str]) -> Dict[str, Dict[str, str]]:
    """{page: {Apex label: value}} -- only the fields we have, per page."""
    out: Dict[str, Dict[str, str]] = {}
    for page, keys in PAGE_OF.items():
        got = {LABEL_FOR[k]: values[k] for k in keys
               if k in LABEL_FOR and values.get(k)}
        if got:
            out[page] = got
    return out


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
<div class="sub">{n} new start{s} ready · button built <b>{build}</b></div>

<div class="note">
  <b>Left this tab open?</b> Reload it (⌘R) first — a tab from earlier still
  holds the older setup. The panel in Apex prints the same <b>built</b> stamp
  at the bottom; if it doesn't say <b>{build}</b>, click <b>load a new
  setup</b> there and paste this page's setup in. The bookmark itself stays
  put.
</div>

<div class="drag">
  <div style="margin-bottom:12px;font-size:15px">Save this <b>once, ever</b> —
  drag it to your bookmarks bar. It holds no report and no people, so it never
  needs replacing again:</div>
  <a class="btn" href="{js}" id="thebtn">Fill Apex</a>
  <div style="margin-top:16px;font-size:14px;color:#555">
    No bookmarks bar? <button id="copybtn" style="font:inherit;padding:6px 12px;
    border:1px solid #0F766E;background:#fff;color:#0F766E;border-radius:6px;
    cursor:pointer">Copy the button</button>
    <span id="copied" style="color:#0F766E;display:none">copied ✓</span>
  </div>
  <div style="margin-top:20px;padding-top:16px;border-top:1px solid #dde">
    <div style="font-size:15px;margin-bottom:10px"><b>Every week</b> (and any
    time this page shows a newer <b>built</b> stamp), load it in:</div>
    <button id="databtn" style="font:inherit;padding:10px 20px;border:0;
    background:#0F766E;color:#fff;border-radius:8px;cursor:pointer;
    font-weight:700">Copy this week's setup</button>
    <span id="datacopied" style="color:#0F766E;display:none"> copied ✓ — now
    click Fill Apex on any Apex page and paste it in</span>
    <textarea id="thedata" style="position:absolute;left:-9999px"
    readonly>{data}</textarea>
  </div>
</div>

<div class="note" id="manual">
  <b>If you can't drag it:</b> click <b>Copy the button</b> above, then
  <b>Bookmarks → Open Bookmarks Manager</b> → the <b>⋮</b> at the top right →
  <b>Add new bookmark</b>. Name it <b>Fill Apex</b> and paste into the URL box.
  It then lives in your Bookmarks menu — no bar needed.
</div>

<script>
document.getElementById('databtn').onclick = function(){{
  var t = document.getElementById('thedata');
  var done = function(){{
    var c = document.getElementById('datacopied');
    c.style.display = 'inline'; setTimeout(function(){{c.style.display='none';}}, 6000);
  }};
  if (navigator.clipboard) {{ navigator.clipboard.writeText(t.value).then(done, back); }}
  else back();
  function back(){{ t.style.position='static'; t.style.left='0'; t.select();
    try {{ document.execCommand('copy'); done(); }} catch(e) {{}} }}
}};
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
  <li><b>Once, ever:</b> save the green button above (drag it, or use
      <b>Copy the button</b>). It is a loader — it carries no report logic and
      no people — so it is never the thing that goes stale.</li>
  <li><b>Each week, and after any fix:</b> click <b>Copy this week's
      setup</b>, then click <b>Fill Apex</b> on any Apex page and paste it into
      the box that appears. Already loaded an older one? The panel has
      <b>load a new setup</b> at the bottom.</li>
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
            % (i, p["name"], p.get("hire") or "—",
               "warn" if gap else "", gap or "—"))
    build = _now_stamp()
    return PAGE.format(
        week=week, n=len(people), s="" if len(people) == 1 else "s", build=build,
        # CODE ONLY -- the people are copied separately, so the saved bookmark
        # never goes stale.
        # A LOADER, saved once and never again. Everything that changes --
        # the week's people and every fix to the code -- rides in on the
        # paste below, which was already a weekly step.
        js=build_stub().replace('"', "&quot;"),
        # & FIRST, then < -- the other order turns "&lt;" into "&amp;lt;"
        # and the textarea hands back the wrong characters.
        data=build_js(people, week, build)[len("javascript:"):]
             .replace("&", "&amp;").replace("<", "&lt;"),
        rows="\n".join(rows), stamp=stamp)
