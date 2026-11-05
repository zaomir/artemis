"""MAIL-02/03 preparation using the existing relay's Gmail service factory.

No transport is constructed here. The caller must supply the verified existing
sender/service after BASE-03. Uncertain sends require positive Sent-folder
readback; a missing search result never permits a blind resend.
"""
import base64
from datetime import timedelta
from email.message import EmailMessage
import hashlib
import html
import json
import re
from urllib.parse import urlencode
import funnel_store as store
from funnel_http import LABELS

TEXT={
 'en': ('Confirm your Artemis de la Cruz news subscription','A request to receive Artemis de la Cruz news was made for this address. Open the page below and press the confirmation button. The link is valid for 48 hours. If you did not request this, do nothing; no news will be sent. Project updates are available on the website without a subscription.','Your subscription is confirmed. Read the project diary for the current stage and updates.'),
 'es': ('Confirme su suscripción a las novedades de Artemis de la Cruz','Se ha solicitado recibir noticias de Artemis de la Cruz en esta dirección. Abra la página y pulse el botón de confirmación. El enlace es válido durante 48 horas. Si no lo ha solicitado, no haga nada: no recibirá novedades. Las actualizaciones están disponibles en la web sin suscripción.','Su suscripción está confirmada. Consulte el diario del proyecto para conocer la etapa actual y las novedades.'),
 'de': ('Bestätigen Sie Ihr Artemis de la Cruz Abonnement','Für diese Adresse wurden Neuigkeiten zu Artemis de la Cruz angefordert. Öffnen Sie die Seite und drücken Sie die Bestätigungstaste. Der Link ist 48 Stunden gültig. Falls Sie dies nicht angefordert haben, müssen Sie nichts tun; es werden keine Neuigkeiten gesendet. Die Projektinformationen sind ohne Abonnement auf der Website zugänglich.','Ihr Abonnement ist bestätigt. Den aktuellen Stand und Neuigkeiten finden Sie im Projekttagebuch.'),
 'fr': ('Confirmez votre abonnement aux nouvelles d’Artemis de la Cruz','Une demande de nouvelles d’Artemis de la Cruz a été faite pour cette adresse. Ouvrez la page et appuyez sur le bouton de confirmation. Le lien est valable 48 heures. Si vous n’êtes pas à l’origine de la demande, ne faites rien : aucune nouvelle ne sera envoyée. Les actualités restent accessibles sur le site sans abonnement.','Votre abonnement est confirmé. Consultez le journal du projet pour connaître son état actuel et les nouvelles.'),
 'ru': ('Подтвердите подписку на новости Artemis de la Cruz','На этот адрес поступил запрос на получение новостей Artemis de la Cruz. Откройте страницу ниже и нажмите кнопку подтверждения. Ссылка действует 48 часов. Если вы не запрашивали подписку, ничего делать не нужно: новости отправляться не будут. Материалы проекта доступны на сайте независимо от подписки.','Подписка подтверждена. Актуальная стадия и новости — в дневнике проекта.')}


def message(row,sender,reply_to,secret):
    """row: id, email, language, generation, kind, subscription_id."""
    if not store.EMAIL.fullmatch(sender) or not store.EMAIL.fullmatch(reply_to):raise ValueError('verified_sender_required')
    mid,email,loc,gen,kind,sid=row
    if kind not in ('confirmation','welcome'):raise ValueError('published_newsletter_issue_required')
    prefix='https://artemisresort.com/tenerife/'+('' if loc=='en' else loc+'/')
    labels=LABELS[loc]
    m=EmailMessage();m['From']='Artemis de la Cruz <'+sender+'>';m['To']=email;m['Reply-To']=reply_to
    m['Message-ID']='<artemis-'+mid+'@'+sender.split('@')[1]+'>'
    m['X-Artemis-Mail-Key']=mid
    if kind=='confirmation':
        token=store.token_for(secret,sid,gen,'confirm')
        url='https://artemisresort.com/tenerife/subscription/confirm/?'+urlencode({'token':token})
        subject,body=TEXT[loc][0:2];cta=labels['confirm']
    else:
        subject=labels['done']+' — Artemis de la Cruz';body=TEXT[loc][2];url=prefix+'actualizaciones/';cta=labels['diary']
    m['Subject']=subject
    unsubscribe='https://artemisresort.com/tenerife/subscription/unsubscribe/?'+urlencode(dict(id=sid,generation=gen,token=store.token_for(secret,sid,gen,'unsubscribe')))
    # Confirmation is a requested service message; future news/welcome carries
    # standards-based one-click unsubscribe as well as a browser POST page.
    if kind!='confirmation':
        m['List-Unsubscribe']='<'+unsubscribe+'>'
        m['List-Unsubscribe-Post']='List-Unsubscribe=One-Click'
    plain=body+'\n\n'+cta+': '+url+'\n'
    rich='<p>'+html.escape(body)+'</p><p><a href="'+html.escape(url,quote=True)+'">'+html.escape(cta)+'</a></p>'
    if kind!='confirmation':
        plain+='\n'+labels['unsubscribe']+': '+unsubscribe+'\n'
        rich+='<p><a href="'+html.escape(unsubscribe,quote=True)+'">'+html.escape(labels['unsubscribe'])+'</a></p>'
    m.set_content(plain);m.add_alternative(rich,subtype='html')
    return m


def find_accepted(service,message_id,key):
    query='in:sent rfc822msgid:'+message_id.strip('<>')
    result=service.users().messages().list(userId='me',q=query,maxResults=100).execute()
    if result.get('nextPageToken'):raise RuntimeError('ambiguous_sent_search')
    matches=[]
    for item in result.get('messages',[]):
        read=service.users().messages().get(userId='me',id=item['id'],format='metadata',metadataHeaders=['X-Artemis-Mail-Key','Message-ID']).execute()
        headers={h['name'].lower():h['value'] for h in read.get('payload',{}).get('headers',[])}
        if headers.get('x-artemis-mail-key')==key and headers.get('message-id')==message_id:matches.append(item['id'])
    if len(matches)>1:raise RuntimeError('duplicate_provider_messages')
    return matches[0] if matches else None


def deliver_one(conn,service,sender,reply_to,secret,now=None):
    now=now or store.utcnow()
    row=conn.execute('''SELECT m.id,s.email,s.language,m.generation,m.message_type,s.id,m.state
        FROM artemis_mail_outbox m JOIN artemis_subscriptions s ON s.id=m.subscription_id
        WHERE m.state IN ('queued','retrying','uncertain') AND (m.next_attempt_at IS NULL OR m.next_attempt_at<=?)
        ORDER BY m.created_at LIMIT 1''',(now.isoformat(),)).fetchone()
    if not row:return None
    m=message(row[:6],sender,reply_to,secret)
    mid=row[0]
    # Positive provider readback is always safe after a timeout/crash. Search
    # absence is not evidence that Gmail rejected the original request.
    if row[6]=='uncertain':
        found=find_accepted(service,m['Message-ID'],mid)
        if found:
            conn.execute("UPDATE artemis_mail_outbox SET state='accepted',provider_id=?,last_error=NULL WHERE id=?",(found,mid));conn.commit()
            return {'state':'accepted','message_id':mid,'provider_id':found}
        conn.execute('UPDATE artemis_mail_outbox SET next_attempt_at=? WHERE id=?',((now+timedelta(hours=1)).isoformat(),mid));conn.commit()
        return {'state':'uncertain','message_id':mid}
    conn.execute('BEGIN IMMEDIATE')
    # Selection is advisory: another worker may have claimed this row while we
    # waited for the short write transaction. Never suppress its in-flight send.
    state=conn.execute('SELECT state FROM artemis_mail_outbox WHERE id=?',(mid,)).fetchone()
    if not state or state[0] not in ('queued','retrying'):
        conn.rollback();return None
    if not store.eligible_mail(conn,mid,now):
        conn.execute("UPDATE artemis_mail_outbox SET state='suppressed' WHERE id=?",(mid,));conn.commit()
        return {'state':'suppressed','message_id':mid}
    # This commit is the dispatch boundary. Eligibility and generation are
    # checked atomically with the claim. An unsubscribe committed before this
    # boundary prevents dispatch; an already-started provider request cannot be
    # recalled. It must not block new enquiries or the unsubscribe itself.
    conn.execute("UPDATE artemis_mail_outbox SET state='uncertain',attempts=attempts+1,next_attempt_at=?,last_error=NULL WHERE id=?",
        ((now+timedelta(minutes=10)).isoformat(),mid));conn.commit()
    try:
        result=service.users().messages().send(userId='me',body={'raw':base64.urlsafe_b64encode(m.as_bytes()).decode()}).execute()
        if not result.get('id'):raise RuntimeError('missing_provider_id')
    except Exception as exc:
        conn.execute("UPDATE artemis_mail_outbox SET last_error=?,next_attempt_at=? WHERE id=? AND state='uncertain'",(type(exc).__name__,(now+timedelta(minutes=10)).isoformat(),mid));conn.commit()
        return {'state':'uncertain','message_id':mid}
    conn.execute("UPDATE artemis_mail_outbox SET state='accepted',provider_id=?,last_error=NULL WHERE id=?",(result['id'],mid));conn.commit()
    return {'state':'accepted','message_id':mid,'provider_id':result['id']}
