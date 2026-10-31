/* Artemis Tenerife RU v3: header state, mobile sheet, ladder rise (DESIGN.md C1, C8). External file: CSP.
   C1: the header is solid by default and without JS; .is-over only while the hero picture (.hero__media)
   lies under the header strip (IntersectionObserver with the root narrowed to that strip, no scroll listener). */
(function(){
  var rm=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;
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
  function setOpen(o){
    s.classList.toggle('is-open',o); b.setAttribute('aria-expanded',o?'true':'false');
    if(o) h.classList.remove('is-over'); else if(media) paint(under());
  }
  if(b&&s&&h){
    s.hidden=false; b.setAttribute('role','button');
    b.addEventListener('click',function(ev){ev.preventDefault();setOpen(!s.classList.contains('is-open'));});
    b.addEventListener('keydown',function(ev){if(ev.key===' '){ev.preventDefault();setOpen(!s.classList.contains('is-open'));}});
    document.addEventListener('keydown',function(ev){if(ev.key==='Escape'&&s.classList.contains('is-open')){setOpen(false);b.focus();}});
  }
  var l=document.getElementById('ladder');
  if(l&&!rm&&'IntersectionObserver' in window&&l.getBoundingClientRect().top>window.innerHeight){
    l.classList.add('js-rise');
    var lio=new IntersectionObserver(function(e){if(e[0].isIntersecting){l.classList.add('is-in');lio.disconnect();}},{threshold:.3});
    lio.observe(l);
  }
})();
