/* Full upfront investment and one cash exit. All financial inputs come from #cs-model. */
(function(){
  var f=document.getElementById('calc-form'),res=document.getElementById('calc-res'),M;
  if(!f||!res)return;
  try{M=JSON.parse(document.getElementById('cs-model').textContent);}catch(e){return;}
  var range=document.getElementById('calc-m2'),out=document.getElementById('calc-m2-out');
  var budget=document.getElementById('calc-budget-out');
  var euro=function(n){return String(Math.floor(n+0.5)).replace(/\B(?=(\d{3})+(?!\d))/g,'\u00a0')+'\u00a0€';};
  var hid={};['m2','step','pay'].forEach(function(k){hid[k]=document.getElementById('wl-calc-'+k);});
  function set(k,v){var node=res.querySelector('[data-k="'+k+'"]');if(node)node.textContent=v;
    document.querySelectorAll('[data-calc-value="'+k+'"]').forEach(function(n){n.textContent=v;});}
  function calc(){
    var quantity=+range.value,total=quantity*M.steps[0].price_eur_m2;
    var result=total*Math.pow(1+M.investment.target_annual,M.investment.exit_months/12);
    out.textContent=quantity+' '+M.unit;
    if(budget)budget.textContent=euro(total);
    range.setAttribute('aria-valuetext',euro(total)+' · '+quantity+' '+M.unit);
    M.types.forEach(function(t){var r=f.querySelector('input[name=type][value='+t.id+']');if(r)r.checked=quantity===t.quantity;});
    set('sum',euro(total));set('exit',euro(result));set('gain',euro(result-total));
    if(hid.m2){hid.m2.value=quantity;hid.step.value=M.steps[0].id;hid.pay.value='now';}
  }
  f.addEventListener('input',function(event){
    if(event.target.name==='type'){var t=M.types.filter(function(x){return x.id===event.target.value;})[0];if(t)range.value=t.quantity;}
    calc();
  });
  f.addEventListener('change',calc);
  calc();
})();
