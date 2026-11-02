/* Artemis Tenerife RU v3 calculator (DESIGN.md C9). Reads the #cs-model island (= model.json subset);
   no figures in this file. Defaults are server-rendered, so the page is complete without JS.
   2026-11-02: цены — пределами (min/max), дивиденд в процентах и евро, рассрочка со скидкой. */
(function(){
  var M, f=document.getElementById('calc-form'), res=document.getElementById('calc-res');
  if(!f||!res) return;
  try{M=JSON.parse(document.getElementById('cs-model').textContent);}catch(e){return;}
  var rm=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var hu=function(n){return Math.floor(n+0.5);};
  var nf=new Intl.NumberFormat('ru-RU',{maximumFractionDigits:0}), pf=new Intl.NumberFormat('ru-RU',{minimumFractionDigits:1,maximumFractionDigits:1,roundingMode:'halfExpand'});
  var eur=function(n){return nf.format(hu(n)).replace(/\s/g,'\u00a0')+'\u00a0€';};
  var rng=function(a,b){return eur(a)+'–'+eur(b);};
  var step=function(id){for(var i=0;i<M.steps.length;i++) if(M.steps[i].id===id) return M.steps[i];};
  var hand=M.steps.filter(function(s){return s.entry===false;})[0];
  var out=document.getElementById('calc-m2-out'), range=document.getElementById('calc-m2');
  var cur=M.steps.filter(function(s){return s.current;})[0].id;
  var disc=(M.installments.discount_pct||0)/100, months=M.installments.months;
  var val=function(n,dflt){var r=f.querySelector('input[name='+n+']:checked'); return r?r.value:dflt;};
  var hid={};['m2','step','pay'].forEach(function(k){hid[k]=document.getElementById('wl-calc-'+k);});
  function set(k,v){var d=res.querySelector('[data-k="'+k+'"]'); if(!d||d.textContent===v) return;
    if(!rm){d.classList.add('is-updating');setTimeout(function(){d.classList.remove('is-updating');},120);} d.textContent=v;}
  function calc(){
    var m2=+range.value, id=val('step',cur), pay=val('pay','m'+months), st=step(id);
    var lo=m2*st.min, hi=m2*st.max;
    out.textContent=m2+' м²';
    M.types.forEach(function(t){var r=f.querySelector('input[name=type][value='+t.id+']'); if(r) r.checked=m2>=t.min&&m2<=t.max;});
    set('sum',rng(lo,hi));
    set('month',pay==='now'?'—':rng(lo*(1-disc)/months, hi*(1-disc)/months));
    set('handover',rng(m2*hand.min, m2*hand.max));
    set('div',eur(m2*M.dividend_eur_per_share_year));
    set('pct',pf.format(M.dividend_pct_range[0])+'–'+pf.format(M.dividend_pct_range[1])+'%');
    if(hid.m2){hid.m2.value=m2;hid.step.value=id;hid.pay.value=pay;}
  }
  f.addEventListener('input',function(ev){
    if(ev.target.name==='type'){var t=M.types.filter(function(x){return x.id===ev.target.value;})[0]; if(t) range.value=hu((t.min+t.max)/2);}
    calc();
  });
  f.addEventListener('change',calc);
})();
