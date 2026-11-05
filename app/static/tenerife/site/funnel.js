/* Explicit typed capture; kept separate from the legacy compatibility handler. */
(function(){
  var f=document.querySelector('form[data-funnel-version]');
  if(!f) return;
  var channel=f.elements.contact_type,contact=f.elements.contact;
  var problem=f.dataset.msgProblem, opt=f.elements.newsletter_opt_in, newsEmail=f.elements.newsletter_email;
  function channelChanged(){contact.type=channel.value==='email'?'email':'text';
    if(newsEmail){newsEmail.disabled=!opt.checked;newsEmail.required=opt.checked&&channel.value==='facebook';}}
  channel.addEventListener('change',channelChanged);channelChanged();
  opt.addEventListener('change',channelChanged);
  var query=new URLSearchParams(location.search);
  ['source_id','utm_source','utm_medium','utm_campaign','form_id'].forEach(function(key){
    var value=query.get(key);
    if(value&&/^[A-Za-z0-9_.:-]{1,100}$/.test(value)){
      var input=f.querySelector('input[name="'+key+'"]');
      if(!input){input=document.createElement('input');input.type='hidden';input.name=key;f.appendChild(input);}
      input.value=value;
    }
  });
  /* Preserve allowlisted campaign values when the user follows a language link. */
  document.querySelectorAll('a[hreflang], .langs a, .sheet__langs a, .lang-ru a, .lang a').forEach(function(a){
    var u=new URL(a.href,location.origin);
    if(u.origin!==location.origin)return;
    ['source_id','utm_source','utm_medium','utm_campaign','form_id'].forEach(function(key){
      var value=query.get(key);if(value&&/^[A-Za-z0-9_.:-]{1,100}$/.test(value))u.searchParams.set(key,value);
    });a.href=u.href;
  });
  if(!window.fetch)return;
  f.addEventListener('submit',function(e){
    e.preventDefault();if(!f.reportValidity())return;
    Array.prototype.forEach.call(f.querySelectorAll('[aria-invalid]'),function(input){input.removeAttribute('aria-invalid');});
    var data={};new FormData(f).forEach(function(v,k){data[k]=v;});
    data.newsletter_opt_in=f.elements.newsletter_opt_in.checked;
    data.consent=f.elements.consent?f.elements.consent.checked:false;
    var button=f.querySelector('button[type=submit]');button.disabled=true;
    fetch(f.action,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)})
      .then(function(r){
        if(!/application\/json/.test(r.headers.get('Content-Type')||''))return {ok:false,error:problem};
        return r.json().then(null,function(){return {ok:false,error:problem};});
      })
      .then(function(r){if(!r||r.ok!==true){
          document.getElementById('af-status').textContent=r&&typeof r.error==='string'?r.error:problem;
          button.disabled=false;var field=r&&r.field&&f.elements[r.field];
          if(field&&field.focus){field.setAttribute('aria-invalid','true');field.focus();}return;
        }
        /* Commit acknowledged before leaving; no PII/source receipt in URL. */
        if(/^\/tenerife\/(?:[a-z]{2}\/)?actualizaciones\/$/.test(r.next_url)){
          var status=document.getElementById('af-status');status.textContent=r.message+' ';
          var link=document.createElement('a');link.href=r.next_url;link.textContent=r.next_label;status.appendChild(link);
        }
      }).catch(function(){document.getElementById('af-status').textContent=problem;button.disabled=false;});
  });
})();
