/* Artemis Tenerife RU v3: header state and mobile sheet (focus trap). External file: CSP.
   C1: the header is solid by default and without JS; .is-over only while the hero picture (.hero__media)
   lies under the header strip (IntersectionObserver with the root narrowed to that strip, no scroll listener). */
(function(){
  var h=document.getElementById('site-header'), media=document.querySelector('#hero .hero__media'),
      s=document.getElementById('sheet'), b=document.getElementById('burger'), io=null;
  function hh(){return h.offsetHeight;}
  function under(){var r=media.getBoundingClientRect();return r.top<hh()&&r.bottom>=hh();}
  function paint(over){h.classList.toggle('is-over',over&&!(s&&s.classList.contains('is-open')));}
  function watch(){
    if(io) io.disconnect();
    io=new IntersectionObserver(function(e){paint(e[e.length-1].isIntersecting);},
      {rootMargin:(1-hh())+'px 0px '+(hh()-window.innerHeight)+'px 0px',threshold:0});
    io.observe(media);
  }
  if(h&&media&&'IntersectionObserver' in window){
    paint(under()); watch();
    var rt; window.addEventListener('resize',function(){clearTimeout(rt);rt=setTimeout(function(){paint(under());watch();},100);});
  }
  /* QA T3-06: while the sheet is open it is a modal menu: everything else is inert (skip link, brand, desktop nav,
     main, footer), Tab cycles burger -> sheet links, Esc closes; on close focus returns to the burger. */
  function bg(){var r=[].slice.call(document.querySelectorAll('body > *:not(header):not(script)'));
    [h.querySelector('.brand'),h.querySelector('.nav'),h.querySelector('.langs')].forEach(function(x){if(x) r.push(x);}); return r;}
  function ring(){return [b].concat([].slice.call(s.querySelectorAll('a[href]')));}
  function isOpen(){return s.classList.contains('is-open');}
  function setOpen(o,back){
    s.classList.toggle('is-open',o); b.setAttribute('aria-expanded',o?'true':'false');
    bg().forEach(function(x){if(o) x.setAttribute('inert',''); else x.removeAttribute('inert');});
    if(o){h.classList.remove('is-over'); var f=s.querySelector('a[href]'); if(f) f.focus();}
    else{if(media) paint(under()); if(back) b.focus();}
  }
  if(b&&s&&h){
    s.hidden=false; b.setAttribute('role','button');
    b.addEventListener('click',function(ev){ev.preventDefault();setOpen(!isOpen(),true);});
    b.addEventListener('keydown',function(ev){if(ev.key===' '){ev.preventDefault();setOpen(!isOpen(),true);}});
    s.addEventListener('click',function(ev){
      var a=ev.target.closest('a[href]');
      if(!a||a.getAttribute('href').charAt(0)!=='#') return;
      setOpen(false,false);
      var target=document.querySelector(a.getAttribute('href'));
      if(target){var input=target.querySelector('input:not([type=hidden])'); if(input) input.focus({preventScroll:true});}
    });
    document.addEventListener('keydown',function(ev){
      if(!isOpen()) return;
      if(ev.key==='Escape'){ev.preventDefault();setOpen(false,true);return;}
      if(ev.key!=='Tab') return;
      var r=ring(), i=r.indexOf(document.activeElement);
      if(ev.shiftKey&&i<=0){ev.preventDefault();r[r.length-1].focus();}
      else if(!ev.shiftKey&&(i===-1||i===r.length-1)){ev.preventDefault();r[0].focus();}
    });
    /* burger hidden (desktop width) while open -> close, so the page never stays inert */
    window.addEventListener('resize',function(){if(isOpen()&&!b.offsetParent) setOpen(false,false);});
  }
  /* «Ещё» (<details> в меню ≥1024): Esc закрывает и возвращает фокус на summary (design v3, components.html) */
  document.addEventListener('keydown',function(ev){
    if(ev.key!=='Escape') return;
    var d=document.querySelector('.nav details[open]'); if(!d) return;
    d.open=false; var sm=d.querySelector('summary'); if(sm) sm.focus();
  });
})();
