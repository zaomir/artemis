"""HTTP integration, explicitly disabled until runtime discovery and release QA.

Uses the existing endpoint/SQLite, never a parallel lead store or CRM service.
"""
import json
import os
import re
import sqlite3
import uuid
from flask import current_app, make_response, render_template, request
import funnel_store as store

LABELS={
 'en': dict(name='Name',channel='How may we reply?',contact='Email or Facebook profile',optional_email='Email for updates (optional for a Facebook contact)',opt_in='I want email news about Artemis de la Cruz: the site search, concept development and project progress. I can unsubscribe at any time.',consent='Use my details to respond to this enquiry.',privacy='Privacy',submit='Send enquiry',success='Your enquiry is saved. If you requested email updates, check your inbox for the confirmation request. You can read the project diary now.',confirm='Confirm subscription',unsubscribe='Unsubscribe',done='Your preference has been saved.',diary='Project diary'),
 'es': dict(name='Nombre',channel='¿Cómo podemos responderle?',contact='Email o perfil de Facebook',optional_email='Email para novedades (opcional con contacto de Facebook)',opt_in='Quiero recibir por email noticias de Artemis de la Cruz: búsqueda del terreno, desarrollo del concepto y avances. Puedo darme de baja en cualquier momento.',consent='Utilicen mis datos para responder a esta consulta.',privacy='Privacidad',submit='Enviar consulta',success='Su consulta se ha guardado. Si ha solicitado novedades por email, revise su bandeja para confirmar la suscripción. Ya puede leer el diario del proyecto.',confirm='Confirmar suscripción',unsubscribe='Darse de baja',done='Su preferencia se ha guardado.',diary='Diario del proyecto'),
 'de': dict(name='Name',channel='Wie dürfen wir antworten?',contact='E-Mail oder Facebook-Profil',optional_email='E-Mail für Neuigkeiten (bei Facebook-Kontakt optional)',opt_in='Ich möchte E-Mail-Neuigkeiten zu Artemis de la Cruz erhalten: Grundstückssuche, Konzeptentwicklung und Projektfortschritt. Ich kann mich jederzeit abmelden.',consent='Meine Angaben dürfen zur Beantwortung dieser Anfrage verwendet werden.',privacy='Datenschutz',submit='Anfrage senden',success='Ihre Anfrage wurde gespeichert. Falls Sie E-Mail-Neuigkeiten angefordert haben, prüfen Sie Ihr Postfach für die Bestätigung. Das Projekttagebuch ist bereits zugänglich.',confirm='Abonnement bestätigen',unsubscribe='Abmelden',done='Ihre Auswahl wurde gespeichert.',diary='Projekttagebuch'),
 'fr': dict(name='Nom',channel='Comment pouvons-nous vous répondre ?',contact='Email ou profil Facebook',optional_email='Email pour les nouvelles (facultatif avec un contact Facebook)',opt_in="Je souhaite recevoir par email les nouvelles d’Artemis de la Cruz : recherche du terrain, développement du concept et avancement du projet. Je peux me désabonner à tout moment.",consent='Utilisez mes coordonnées pour répondre à cette demande.',privacy='Confidentialité',submit='Envoyer la demande',success='Votre demande a été enregistrée. Si vous avez demandé des nouvelles par email, consultez votre boîte pour confirmer l’abonnement. Le journal du projet est déjà accessible.',confirm='Confirmer l’abonnement',unsubscribe='Se désabonner',done='Votre préférence a été enregistrée.',diary='Journal du projet'),
 'ru': dict(name='Имя',channel='Как вам ответить?',contact='Email или профиль Facebook',optional_email='Email для новостей (необязательно при контакте Facebook)',opt_in='Хочу получать по email новости Artemis de la Cruz: о выборе участка, разработке концепции и ходе проекта. Отписаться можно в любой момент.',consent='Используйте мои данные для ответа на это обращение.',privacy='Конфиденциальность',submit='Отправить заявку',success='Ваша заявка сохранена. Если вы выбрали новости по email, проверьте почту для подтверждения подписки. Уже сейчас можно читать дневник проекта.',confirm='Подтвердить подписку',unsubscribe='Отписаться',done='Ваш выбор сохранён.',diary='Дневник проекта')}


def enabled():
    return os.environ.get('ARTEMIS_FUNNEL_ENABLED')=='1' and len(secret())>=32


def secret():
    return os.environ.get('ARTEMIS_NEWSLETTER_SECRET','')


def form(locale,page,intent_override=None):
    prefix='/tenerife/'+('' if locale=='en' else locale+'/')
    intent=intent_override or ('investor' if '/inversores/' in page or '/calculadora/' in page else 'buyer' if '/producto/' in page else 'other')
    return render_template('tenerife/funnel_form.html',locale=locale,page=page,
        intent=intent,submission_id=str(uuid.uuid4()),labels=LABELS[locale],privacy_url=prefix+'privacy/')


for _loc,_pending in {
 'en':'Your subscription request has been saved. Check your inbox to confirm. The project diary is available now.',
 'es':'Su solicitud de suscripción se ha guardado. Revise su correo para confirmar. El diario del proyecto ya está disponible.',
 'de':'Ihre Abonnementanfrage wurde gespeichert. Prüfen Sie Ihr Postfach zur Bestätigung. Das Projekttagebuch ist bereits zugänglich.',
 'fr':'Votre demande d’abonnement a été enregistrée. Consultez votre boîte pour confirmer. Le journal du projet est déjà accessible.',
 'ru':'Запрос подписки сохранён. Проверьте почту для подтверждения. Дневник проекта уже доступен.'}.items():
    LABELS[_loc]['newsletter_pending']=_pending


def token_response(title,body,locale='en'):
    import html
    shell=f'<!doctype html><html lang="{locale}"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>{html.escape(title)}</title><link rel="stylesheet" href="/static/tenerife/site/site.css"><body><main class="wrap"><h1>{html.escape(title)}</h1>{body}</main></body></html>'
    r=make_response(shell)
    r.headers.update({'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Robots-Tag':'noindex,nofollow','Content-Security-Policy':"default-src 'none'; style-src 'self'; font-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"})
    return r


def register(bp,db_path):
    @bp.route('/tenerife/subscription/confirm/',methods=['GET','POST'])
    def confirm_subscription():
        if not enabled():return '',503
        token=str(request.values.get('token',''))
        if not re.fullmatch('[a-f0-9]{64}',token):return '',400
        with sqlite3.connect(db_path(),timeout=5) as conn:
            row=conn.execute('SELECT language FROM artemis_subscriptions WHERE token_hash=?',(store.hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
            loc=row[0] if row else 'en';labels=LABELS[loc]
            if request.method=='POST':
                conn.execute('BEGIN IMMEDIATE')
                if not store.confirm(conn,token):return '',400
                return token_response(labels['done'],'<p>'+labels['done']+'</p>',loc)
        return token_response(labels['confirm'],f'<form method="post"><input type="hidden" name="token" value="{token}"><button type="submit">{labels["confirm"]}</button></form>',loc)

    @bp.route('/tenerife/subscription/unsubscribe/',methods=['GET','POST'])
    def unsubscribe():
        if not enabled():return '',503
        sid=str(request.values.get('id',''));token=str(request.values.get('token',''))
        if not re.fullmatch('[a-f0-9-]{36}',sid) or not re.fullmatch('[a-f0-9]{64}',token):return '',400
        try:gen=int(request.values.get('generation',0))
        except (ValueError,TypeError):return '',400
        with sqlite3.connect(db_path(),timeout=5) as conn:
            row=conn.execute('SELECT language FROM artemis_subscriptions WHERE id=?',(sid,)).fetchone()
            loc=row[0] if row else 'en';labels=LABELS[loc]
            if request.method=='POST':
                conn.execute('BEGIN IMMEDIATE')
                if not store.unsubscribe(conn,sid,gen,token,secret()):return '',400
                return token_response(labels['done'],'<p>'+labels['done']+'</p>',loc)
        return token_response(labels['unsubscribe'],f'<form method="post"><input type="hidden" name="id" value="{sid}"><input type="hidden" name="generation" value="{gen}"><input type="hidden" name="token" value="{token}"><button type="submit">{labels["unsubscribe"]}</button></form>',loc)
