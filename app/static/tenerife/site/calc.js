/* Artemis Tenerife RU v3 calculator (DESIGN.md C9). Reads the #cs-model island (= model.json subset);
   no figures in this file. Defaults are server-rendered, so the page is complete without JS. */
(function(){
  var M, f=document.getElementById('calc-form'), res=document.getElementById('calc-res');
  if(!f||!res) return;
  try{M=JSON.parse(document.getElementById('cs-model').textContent);}catch(e){return;}
  var rm=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  /* one site rounding rule: ROUND HALF-UP (model.json rounding); all amounts are positive */
  var hu=function(n){return Math.floor(n+0.5);};
  var nf=new Intl.NumberFormat('ru-RU',{maximumFractionDigits:0}), pf=new Intl.NumberFormat('ru-RU',{minimumFractionDigits:1,maximumFractionDigits:1,roundingMode:'halfExpand'});
  var eur=function(n){return nf.format(hu(n)).replace(/\s/g,'\u00a0')+'\u00a0€';};
  var price=function(id){for(var i=0;i<M.steps.length;i++) if(M.steps[i].id===id) return M.steps[i].price_eur_m2;};
  var hand=M.steps.filter(function(s){return s.entry===false;})[0].price_eur_m2;
  var out=document.getElementById('calc-m2-out'), range=document.getElementById('calc-m2');
  var val=function(n){var r=f.querySelector('input[name='+n+']:checked'); return r?r.value:'';};
  var hid={m2:document.getElementById('wl-calc-m2'),step:document.getElementById('wl-calc-step'),pay:document.getElementById('wl-calc-pay')};
  function set(k,v){var d=res.querySelector('[data-k="'+k+'"]'); if(!d||d.textContent===v) return;
    if(!rm){d.classList.add('is-updating');setTimeout(function(){d.classList.remove('is-updating');},120);} d.textContent=v;}
  function calc(){
    var m2=+range.value, step=val('step'), pay=val('pay'), p=price(step), sum=m2*p;
    out.textContent=m2+' м²';
    M.types.forEach(function(t){var r=f.querySelector('input[name=type][value='+t.id+']'); if(r) r.checked=m2>=t.min&&m2<=t.max;});
    set('sum',eur(sum));
    set('month',pay==='m12'?eur(sum/M.installments.months):'—');
    set('handover',eur(m2*hand));
    set('div',eur(m2*M.dividend_eur_per_share_year));
    set('pct',pf.format(M.dividend_eur_per_share_year/p*100)+'%');
    if(hid.m2){hid.m2.value=m2;hid.step.value=step;hid.pay.value=pay;}
  }
  f.addEventListener('input',function(ev){
    if(ev.target.name==='type'){var t=M.types.filter(function(x){return x.id===ev.target.value;})[0]; if(t) range.value=hu((t.min+t.max)/2);} /* type = middle of its range, half-up */
    calc();
  });
  f.addEventListener('change',calc);
})();
