/* Artemis Tenerife waitlist form (external file: CSP script-src 'self').
   QA T3-10: errors sit under their field (p.field__err, linked by aria-describedby) and set aria-invalid;
   the server names the field ({"field": "name|contact|language|consent"}); other errors go to #wl-msg.
   r4: every text comes from the form's data-msg-* (copy_en/17_forma.md «Form messages», put there by build_v3.py).
   The answer is read only when it is the app's JSON: fetch rejected -> network text; 429 -> rate text;
   5xx or not JSON (proxy / HTML error page) -> server text; JSON with a field -> that field's own text. */
(function(){
  var f=document.getElementById('wl-form'); if(!f) return;
  var m=document.getElementById('wl-msg'), b=document.getElementById('wl-submit'), M=f.dataset;
  var ids={name:'wl-name',contact:'wl-contact',language:'wl-lang',consent:'wl-consent'};
  var fieldMsg={name:M.msgName,contact:M.msgContact,language:M.msgLanguage,consent:M.msgConsent};
  var okText=M.msgOkTitle+' '+M.msgOkNext;
  function show(cls,t){m.className='msg '+cls;m.textContent=t;}
  function clear(){show('','');for(var k in ids){var el=document.getElementById(ids[k]);el.removeAttribute('aria-invalid');
    document.getElementById(ids[k]+'-err').textContent='';}}
  function fieldErr(k,t){var el=document.getElementById(ids[k]); if(!el){show('err',t);return;}
    el.setAttribute('aria-invalid','true'); document.getElementById(ids[k]+'-err').textContent=t; el.focus();}
  if(/[?&]ok=1/.test(location.search)) show('ok',okText);
  if(!window.fetch) return;
  f.addEventListener('submit',function(e){
    e.preventDefault();
    var el=f.elements;
    var d={name:el['name'].value.trim(),contact:el['contact'].value.trim(),language:el['language'].value,
           consent:el['consent'].checked,website:el['website'].value,page:el['page'].value};
    /* calculator page: hidden calc_m2, calc_step, calc_pay go with the lead (server recomputes them) */
    for(var i=0;i<el.length;i++){ if(/^calc_/.test(el[i].name)) d[el[i].name]=el[i].value; }
    clear();
    if(!d.name){fieldErr('name',fieldMsg.name);return;}
    if(d.contact.length<5){fieldErr('contact',fieldMsg.contact);return;}
    if(!d.language){fieldErr('language',fieldMsg.language);return;}
    if(!d.consent){fieldErr('consent',fieldMsg.consent);return;}
    var label=b.textContent; b.disabled=true; b.textContent=M.msgSending;
    fetch('/api/tenerife/waitlist',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)})
      .then(function(r){
        if(r.status===429) return {ok:false,error:M.msgRate};
        var json=/application\/json/.test(r.headers.get('Content-Type')||'');
        if(r.status>=500||!json) return {ok:false,error:M.msgServer};
        return r.json().then(null,function(){return {ok:false,error:M.msgServer};});
      },function(){return {ok:false,error:M.msgNetwork};})
      .then(function(r){ if(r&&r.ok===true){show('ok',okText);f.reset();}
        else if(r&&r.field&&ids[r.field]){fieldErr(r.field,fieldMsg[r.field]||M.msgServer);}
        else {show('err',(r&&r.error)||M.msgServer);} })
      .then(function(){b.disabled=false;b.textContent=label;});
  });
})();
