from flask import Flask, request, jsonify, render_template, send_file, abort
import sqlite3, os, smtplib, datetime
from email.mime.text import MIMEText

app = Flask(__name__)
DB = '/var/www/artemis/leads.db'
PDF_PATH = '/var/www/artemis/static/Artemis_Resort_Investment.pdf'

def init_db():
    conn = sqlite3.connect(DB)
    conn.execute('''CREATE TABLE IF NOT EXISTS leads
        (id INTEGER PRIMARY KEY, name TEXT, email TEXT, phone TEXT,
         amount TEXT, created_at TEXT)''')
    conn.commit(); conn.close()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json or {}
    name = data.get('name','').strip()
    email = data.get('email','').strip()
    phone = data.get('phone','').strip()
    amount = data.get('amount','').strip()
    if not name or not email:
        return jsonify({'ok': False, 'error': 'Имя и email обязательны'}), 400
    conn = sqlite3.connect(DB)
    conn.execute('INSERT INTO leads(name,email,phone,amount,created_at) VALUES(?,?,?,?,?)',
        (name, email, phone, amount, datetime.datetime.now().isoformat()))
    conn.commit(); conn.close()
    try:
        msg = MIMEText(f'Новый лид\nИмя: {name}\nEmail: {email}\nТел: {phone}\nСумма: {amount}')
        msg['Subject'] = f'Artemis Resort — новый лид: {name}'
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
    return send_file(PDF_PATH, as_attachment=True, download_name='Artemis_Resort_Investment.pdf')

@app.route('/admin/leads')
def admin_leads():
    token = request.args.get('t','')
    if token != 'rovlex2025':
        abort(403)
    conn = sqlite3.connect(DB)
    rows = conn.execute('SELECT id,name,email,phone,amount,created_at FROM leads ORDER BY id DESC').fetchall()
    conn.close()
    html = '<style>body{font-family:sans-serif;padding:20px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:8px}tr:nth-child(even){background:#f5f5f5}</style>'
    html += f'<h2>Leads ({len(rows)})</h2><table><tr><th>#</th><th>Имя</th><th>Email</th><th>Тел</th><th>Сумма</th><th>Дата</th></tr>'
    for r in rows:
        html += f'<tr><td>{r[0]}</td><td>{r[1]}</td><td>{r[2]}</td><td>{r[3]}</td><td>{r[4]}</td><td>{r[5]}</td></tr>'
    html += '</table>'
    return html

if __name__ == '__main__':
    init_db()
    app.run(host='127.0.0.1', port=8082)
