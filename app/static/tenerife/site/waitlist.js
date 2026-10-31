/* Artemis Tenerife waitlist form (external file: CSP script-src 'self'). */
(function(){
  var f=document.getElementById('wl-form'); if(!f) return;
  var m=document.getElementById('wl-msg'), b=document.getElementById('wl-submit');
  function show(cls,t){m.className='msg '+cls;m.textContent=t;}
  if(/[?&]ok=1/.test(location.search)) show('ok','Спасибо! Вы в листе ожидания.');
  if(!window.fetch) return;
  f.addEventListener('submit',function(e){
    e.preventDefault();
    var el=f.elements;
    var d={name:el['name'].value.trim(),contact:el['contact'].value.trim(),language:el['language'].value,
           consent:el['consent'].checked,website:el['website'].value,page:el['page'].value};
    if(!d.name||d.contact.length<5){show('err','Укажите имя и контакт (email, телефон или Telegram).');return;}
    if(!d.consent){show('err','Нужно согласие на обработку данных.');return;}
    b.disabled=true;
    fetch('/api/tenerife/waitlist',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)})
      .then(function(r){return r.json();})
      .then(function(r){ if(r.ok){show('ok','Спасибо! Вы в листе ожидания. Мы свяжемся с вами.');f.reset();} else {show('err',r.error||'Ошибка. Попробуйте ещё раз.');} })
      .catch(function(){show('err','Ошибка сети. Попробуйте ещё раз.');})
      .then(function(){b.disabled=false;});
  });
})();
