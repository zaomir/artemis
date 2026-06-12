from flask import Flask, request, jsonify, render_template, send_file, abort, make_response, redirect
import sqlite3, os, smtplib, datetime, subprocess, json
from email.mime.text import MIMEText

app = Flask(__name__, 
    template_folder='templates',
    static_folder='static')

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
TRANS_DIR  = os.path.join(BASE_DIR, "translations")
SUPPORTED  = ["ru", "en", "es", "fr"]
DEFAULT    = "ru"
OG_LOCALE  = {"ru": "ru_RU", "en": "en_US", "es": "es_ES", "fr": "fr_FR"}

TRANSLATIONS = {}
for _lang in SUPPORTED:
    with open(os.path.join(TRANS_DIR, f"{_lang}.json"), encoding="utf-8") as _f:
        TRANSLATIONS[_lang] = json.load(_f)

def _pick_language():
    c = request.cookies.get("lang")
    if c in SUPPORTED:
        return c
    return request.accept_languages.best_match(SUPPORTED) or DEFAULT

def _render_site(lang):
    resp = make_response(render_template(
        "index.html",
        t=TRANSLATIONS[lang], lang=lang, og_locale=OG_LOCALE[lang],
        version=get_version(),
    ))
    resp.set_cookie("lang", lang, max_age=60*60*24*365, samesite="Lax")
    return no_cache(resp)

@app.route("/")
def root():
    return redirect(f"/{_pick_language()}/", code=302)

@app.route("/<lang>/")
def localized(lang):
    if lang not in SUPPORTED:
        abort(404)
    return _render_site(lang)

DB = os.path.join(os.path.dirname(__file__), 'leads.db')
PDF_PATH = os.path.join(os.path.dirname(__file__), 'static', 'Artemis_Resort_Investment.pdf')

def get_version():
    try:
        count = subprocess.check_output(
            ['git', '-C', '/var/www/artemis', 'rev-list', '--count', 'HEAD'],
            stderr=subprocess.DEVNULL).decode().strip()
        short = subprocess.check_output(
            ['git', '-C', '/var/www/artemis', 'log', '-1', '--format=%h'],
            stderr=subprocess.DEVNULL).decode().strip()
        date = subprocess.check_output(
            ['git', '-C', '/var/www/artemis', 'log', '-1', '--format=%ci'],
            stderr=subprocess.DEVNULL).decode().strip()[:10]
        return f"v{count} · {short} · {date}"
    except:
        return "v1.0"

def no_cache(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

def init_db():
    conn = sqlite3.connect(DB)
    conn.execute('''CREATE TABLE IF NOT EXISTS leads
        (id INTEGER PRIMARY KEY, name TEXT, email TEXT, phone TEXT,
         amount TEXT, created_at TEXT)''')
    conn.commit(); conn.close()

@app.route('/api/register', methods=['POST'])
def register():
    d = request.json or {}
    name = d.get('name','').strip()
    email = d.get('email','').strip()
    phone = d.get('phone','').strip()
    amount = d.get('amount','').strip()
    if not name or not email:
        return jsonify({'ok': False, 'error': 'Имя и email обязательны'}), 400
    conn = sqlite3.connect(DB)
    conn.execute('INSERT INTO leads(name,email,phone,amount,created_at) VALUES(?,?,?,?,?)',
        (name, email, phone, amount, datetime.datetime.now().isoformat()))
    conn.commit(); conn.close()
    try:
        msg = MIMEText(f'Лид: {name} | {email} | {phone} | {amount}')
        msg['Subject'] = f'Artemis — лид: {name}'
        msg['From'] = 'noreply@artemisresort.com'
        msg['To'] = 'ROVLEX@ROVLEX.COM'
        with smtplib.SMTP('localhost', 25, timeout=5) as s:
            s.sendmail(msg['From'], [msg['To']], msg.as_string())
    except: pass
    return jsonify({'ok': True})

@app.route('/download-pdf')
def download_pdf():
    if not os.path.exists(PDF_PATH):
        abort(404)
    return send_file(PDF_PATH, as_attachment=True,
                     download_name='Artemis_Resort_Investment.pdf')

@app.route('/admin/leads')
def admin_leads():
    if request.args.get('t','') != 'rovlex2025': abort(403)
    conn = sqlite3.connect(DB)
    rows = conn.execute('SELECT id,name,email,phone,amount,created_at FROM leads ORDER BY id DESC').fetchall()
    conn.close()
    v = get_version()
    h = '<style>body{font-family:sans-serif;padding:20px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:8px}tr:nth-child(even){background:#f9f9f9}</style>'
    h += f'<h2>Artemis Leads ({len(rows)})</h2><p style="color:#888;font-size:12px">{v}</p>'
    h += '<table><tr><th>#</th><th>Имя</th><th>Email</th><th>Тел</th><th>Сумма</th><th>Дата</th></tr>'
    for r in rows:
        h += f'<tr><td>{r[0]}</td><td>{r[1]}</td><td>{r[2]}</td><td>{r[3]}</td><td>{r[4]}</td><td>{r[5]}</td></tr>'
    resp = make_response(h + '</table>')
    return no_cache(resp)


# ── Telegram support bot: forward incoming messages to ops group ──
import urllib.request, urllib.parse, json as _json
TG_TOKEN = os.environ.get('TG_BOT_TOKEN', '8982488539:AAEVjyZ_KM1NdNA5LF32rMvzuhtpeW8CSYI')
TG_GROUP = '-5168641824'

def tg_send(chat_id, text):
    if not TG_TOKEN:
        return
    try:
        data = urllib.parse.urlencode({'chat_id': chat_id, 'text': text}).encode()
        urllib.request.urlopen(
            f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage', data=data, timeout=5)
    except Exception:
        pass

@app.route('/tg-webhook', methods=['POST'])
def tg_webhook():
    upd = request.get_json(silent=True) or {}
    msg = upd.get('message') or upd.get('edited_message') or {}
    chat = msg.get('chat', {})
    frm = msg.get('from', {})
    text = msg.get('text', '')
    # Only react to private chats with the bot (a user contacting support)
    if chat.get('type') == 'private':
        uname = frm.get('username', '')
        name = (frm.get('first_name','') + ' ' + frm.get('last_name','')).strip()
        uid = frm.get('id', '')
        handle = f'@{uname}' if uname else f'id{uid}'
        notify = (f'🔔 Обращение в саппорт Artemis\n'
                  f'От: {name} ({handle})\n'
                  f'Сообщение: {text}')
        tg_send(TG_GROUP, notify)
        # auto-reply to the user
        tg_send(chat.get('id'),
                'Спасибо за обращение! Команда Artemis Resort свяжется с вами в ближайшее время.')
    return jsonify({'ok': True})


if __name__ == '__main__':
    init_db()
    app.run(host='127.0.0.1', port=8082, debug=False)
