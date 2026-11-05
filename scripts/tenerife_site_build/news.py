"""Validated news registry; feeds the existing static builder, no new site stack."""
from datetime import date
import html
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
LANGS = ('en','es','de','fr','ru')
UI = {
 'en': ['Project diary','Current stage: concept search','What changed','Still open','Next step','Sources','Read the update','Follow the project','Updates are open to everyone. No account or subscription is needed.'],
 'es': ['Diario del proyecto','Etapa actual: búsqueda del concepto','Qué ha cambiado','Cuestiones abiertas','Siguiente paso','Fuentes','Leer la actualización','Seguir el proyecto','Las novedades están abiertas a todos. No se necesita cuenta ni suscripción.'],
 'de': ['Projekttagebuch','Aktuelle Phase: Konzeptsuche','Was sich geändert hat','Offene Fragen','Nächster Schritt','Quellen','Update lesen','Projekt verfolgen','Die Neuigkeiten stehen allen offen. Ein Konto oder Abonnement ist nicht erforderlich.'],
 'fr': ['Journal du projet','Étape actuelle : recherche du concept','Ce qui a changé','Questions ouvertes','Prochaine étape','Sources','Lire la mise à jour','Suivre le projet','Les nouvelles sont accessibles à tous, sans compte ni abonnement.'],
 'ru': ['Дневник проекта','Текущая стадия: поиск концепции','Что изменилось','Что ещё не определено','Следующий шаг','Источники','Читать обновление','Следить за проектом','Обновления открыты всем. Аккаунт и подписка не нужны.'],
}


def load_registry(path=None):
    data=json.loads(Path(path or HERE/'news_registry.json').read_text())
    assert data['schema']=='artemis-news/1'
    seen=set()
    for a in data['articles']:
        assert re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',a['slug'])
        assert a['news_id'] not in seen; seen.add(a['news_id'])
        assert type(a['revision']) is int and a['revision']>=1
        assert a['editorial_status'] in ('draft','ready','published','withdrawn')
        assert date.fromisoformat(a['event_date']) <= date.fromisoformat(a['publication_date'])
        assert a['sources']
        for source in a['sources']:
            assert source['label'].strip()
            if source.get('visibility')=='internal':
                assert source.get('url') is None and source.get('evidence_ref')
            else:
                assert source['url'].startswith('https://')
        assert a['history'][-1]['revision']==a['revision']
        for loc,t in a['translations'].items():
            assert loc in LANGS
            assert all(t[k].strip() for k in ('title','summary','changed','open','next'))
    return data


def locale_url(loc, slug=''):
    return '/tenerife/'+('' if loc=='en' else loc+'/')+'actualizaciones/'+(slug+'/' if slug else '')


def build_pages(render, locale):
    """render(title, description, body, URL, available locales) uses v3 simple.html."""
    articles=[a for a in load_registry()['articles'] if a['editorial_status'] in ('ready','published') and locale in a['translations']]
    esc=html.escape
    u=UI[locale]
    output={}
    cards=[]
    for a in articles:
        t=a['translations'][locale]
        url=locale_url(locale,a['slug'])
        body=f'<h1 id="h1">{esc(t["title"])}</h1><p class="hero__lead">{esc(t["summary"])}</p>'
        body+=f'<p><time datetime="{a["publication_date"]}">{a["publication_date"]}</time> · {esc(a["author"])}</p>'
        for asset in a['assets']:
            caption=asset['captions'][locale]
            body+=f'<figure><picture class="frame"><img src="{esc(asset["path"],quote=True)}" alt="{esc(caption,quote=True)}" width="{asset["width"]}" height="{asset["height"]}" loading="lazy"></picture><figcaption class="micro">{esc(caption)}</figcaption></figure>'
        for idx,key in [(2,'changed'),(3,'open'),(4,'next')]:
            body+=f'<h2>{u[idx]}</h2><p>{esc(t[key])}</p>'
        citations=[]
        for source in a['sources']:
            label=esc(source.get('labels',{}).get(locale,source['label']))
            citations.append('<li>'+label+'</li>' if source.get('visibility')=='internal' else
                f'<li><a href="{esc(source["url"],quote=True)}">{label}</a></li>')
        body+=f'<h2>{u[5]}</h2><ul>'+''.join(citations)+'</ul>'
        body+=f'<p><a href="{locale_url(locale)}">{u[0]}</a></p>'
        output['actualizaciones/'+a['slug']]=render(t['title'],t['summary'],body,url,list(a['translations']))
        cards.append(f'<article><h2><a href="{url}">{esc(t["title"])}</a></h2><p>{esc(t["summary"])}</p><time datetime="{a["publication_date"]}">{a["publication_date"]}</time></article>')
    body=f'<h1 id="h1">{u[0]}</h1><p class="hero__lead">{u[1]}</p><p>{u[8]}</p>'+''.join(cards)
    output['actualizaciones']=render(u[0],u[1],body,locale_url(locale),list(LANGS))
    return output
