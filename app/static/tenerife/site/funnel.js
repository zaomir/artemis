/* Explicit typed capture; kept separate from the legacy compatibility handler. */
(function(){
  var f=document.querySelector('form[data-funnel-version]');
  if(!f) return;
  var channel=f.elements.contact_type,contact=f.elements.contact;
  function channelChanged(){contact.type=channel.value==='email'?'email':'text';}
  channel.addEventListener('change',channelChanged);channelChanged();
  var query=new URLSearchParams(location.search);
  ['source_id','utm_source','utm_medium','utm_campaign','form_id'].forEach(function(key){
    var value=query.get(key);
    if(value&&/^[A-Za-z0-9_.:-]{1,100}$/.test(value)){
      var input=document.createElement('input');input.type='hidden';input.name=key;input.value=value;f.appendChild(input);
    }
  });
  /* Preserve allowlisted campaign values when the user follows a language link. */
  document.querySelectorAll('a[hreflang], .langs a, .lang a').forEach(function(a){
    var u=new URL(a.href,location.origin);
    if(u.origin!==location.origin)return;
    ['source_id','utm_source','utm_medium','utm_campaign','form_id'].forEach(function(key){
      var value=query.get(key);if(value&&/^[A-Za-z0-9_.:-]{1,100}$/.test(value))u.searchParams.set(key,value);
    });a.href=u.href;
  });
  if(!window.fetch)return;
  f.addEventListener('submit',function(e){
    e.preventDefault();if(!f.reportValidity())return;
    var data={};new FormData(f).forEach(function(v,k){data[k]=v;});
    data.newsletter_opt_in=f.elements.newsletter_opt_in.checked;
    data.consent=f.elements.consent?f.elements.consent.checked:false;
    var button=f.querySelector('button[type=submit]');button.disabled=true;
    fetch(f.action,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)})
      .then(function(r){if(!r.ok)throw new Error('Request failed ('+r.status+')');return r.json();})
      .then(function(r){if(!r.ok)throw new Error('Request failed');
        /* Commit acknowledged before leaving; no PII/source receipt in URL. */
        if(/^\/tenerife\/(?:[a-z]{2}\/)?actualizaciones\/$/.test(r.next_url)){
          var status=document.getElementById('af-status');status.textContent=r.message+' ';
          var link=document.createElement('a');link.href=r.next_url;link.textContent=r.next_label;status.appendChild(link);
        }
      }).catch(function(err){document.getElementById('af-status').textContent=err.message;button.disabled=false;});
  });
})();
