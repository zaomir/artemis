/* Artemis Tenerife RU v3 calculator (DESIGN.md C9). Reads the #cs-model island (= model.json subset);
   no figures in this file. Defaults are server-rendered, so the page is complete without JS. */
(function(){
  var M, f=document.getElementById('calc-form'), res=document.getElementById('calc-res');
  if(!f||!res) return;
  try{M=JSON.parse(document.getElementById('cs-model').textContent);}catch(e){return;}
  var rm=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  /* one site rounding rule: ROUND HALF-UP (model.json rounding); all amounts are positive */
  var hu=function(n){return Math.floor(n+0.5);};
  /* same shape in every language: U+00A0 groups, comma decimal, «€» after the number (= server-rendered values) */
  var pf=new Intl.NumberFormat('ru-RU',{minimumFractionDigits:1,maximumFractionDigits:1,roundingMode:'halfExpand'});
  var eur=function(n){return String(hu(n)).replace(/\B(?=(\d{3})+(?!\d))/g,'\u00a0')+'\u00a0€';};
  var pct1=function(x){return pf.format(x)+'%';};
  var price=function(id){for(var i=0;i<M.steps.length;i++) if(M.steps[i].id===id) return M.steps[i].price_eur_m2;};
  var hand=M.steps.filter(function(s){return s.entry===false;})[0].price_eur_m2;
  var out=document.getElementById('calc-m2-out'), range=document.getElementById('calc-m2');
  var cur=M.steps.filter(function(s){return s.current;})[0].id;
  /* C9 short (04) has no step / pay choice: the current step and 12 months, as rendered server-side */
  var val=function(n,dflt){var r=f.querySelector('input[name='+n+']:checked'); return r?r.value:dflt;};
  /* hidden fields of the C13 «calculadora» form: exactly calc_m2, calc_step, calc_pay (DESIGN.md C9/C13) */
  var hid={};['m2','step','pay'].forEach(function(k){hid[k]=document.getElementById('wl-calc-'+k);});
  function set(k,v){var d=res.querySelector('[data-k="'+k+'"]'); if(!d||d.textContent===v) return;
    if(!rm){d.classList.add('is-updating');setTimeout(function(){d.classList.remove('is-updating');},120);} d.textContent=v;}
  function calc(){
    var m2=+range.value, step=val('step',cur), pay=val('pay','m12'), p=price(step), sum=m2*p;
    out.textContent=m2+' '+(M.unit||'м²');
    M.types.forEach(function(t){var r=f.querySelector('input[name=type][value='+t.id+']'); if(r) r.checked=m2>=t.min&&m2<=t.max;});
    set('sum',eur(sum));
    var disc=(M.installments.discount_pct||0)/100;
    set('month',pay==='now'?'—':eur(sum*(1-disc)/M.installments.months));
    set('handover',eur(m2*hand));
    var pr=M.dividend_pct_range||[2.5,3.5];
    set('pct',pct1(pr[0])+'–'+pct1(pr[1]));
    /* the server recomputes everything else from these with the current model.json (tenerife_calc.py) */
    if(hid.m2){hid.m2.value=m2;hid.step.value=step;hid.pay.value=pay;}
  }
  f.addEventListener('input',function(ev){
    if(ev.target.name==='type'){var t=M.types.filter(function(x){return x.id===ev.target.value;})[0]; if(t) range.value=hu((t.min+t.max)/2);} /* type = middle of its range, half-up */
    calc();
  });
  f.addEventListener('change',calc);
})();
