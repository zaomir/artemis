#!/bin/bash
# ARTEMIS RESORT — First-time server setup
# Run as root: bash setup_server.sh
set -e

REPO="https://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@github.com/zaomir/artemis.git"
SITE_DIR=/var/www/artemis
APP_PORT=8082

echo "=== Artemis Resort — Setup ==="

# Clone repo
if [ -d "$SITE_DIR/.git" ]; then
  echo "Repo exists — pulling..."
  cd "$SITE_DIR" && git pull
else
  git clone "$REPO" "$SITE_DIR"
fi

# Venv
python3 -m venv "$SITE_DIR/venv"
"$SITE_DIR/venv/bin/pip" install -q flask gunicorn

# Systemd (WorkingDirectory = app/ subdir)
cat > /etc/systemd/system/artemis.service << SVC
[Unit]
Description=Artemis Resort
After=network.target
[Service]
User=www-data
WorkingDirectory=$SITE_DIR/app
ExecStart=$SITE_DIR/venv/bin/gunicorn -w 2 -b 127.0.0.1:$APP_PORT app:app
Restart=always
[Install]
WantedBy=multi-user.target
SVC

systemctl daemon-reload
systemctl enable artemis
systemctl restart artemis
sleep 2
systemctl is-active artemis && echo "artemis: OK"

# Nginx (if not already configured)
if [ ! -f /etc/nginx/sites-enabled/artemisresort.com ]; then
cat > /etc/nginx/sites-available/artemisresort.com << NGX
server {
    listen 80;
    server_name artemisresort.com www.artemisresort.com;
    location /static/ { alias $SITE_DIR/app/static/; expires 30d; }
    location /deploy-hook { proxy_pass http://127.0.0.1:9001; proxy_set_header X-Hook-Secret \$http_x_hook_secret; }
    location / { proxy_pass http://127.0.0.1:$APP_PORT; proxy_set_header Host \$host; proxy_set_header X-Real-IP \$remote_addr; }
}
NGX
ln -sf /etc/nginx/sites-available/artemisresort.com /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
fi

# DB
"$SITE_DIR/venv/bin/python3" -c "
import sqlite3, os
db = '$SITE_DIR/app/leads.db'
conn=sqlite3.connect(db)
conn.execute('CREATE TABLE IF NOT EXISTS leads (id INTEGER PRIMARY KEY, name TEXT, email TEXT, phone TEXT, amount TEXT, created_at TEXT)')
conn.commit(); conn.close(); print('DB: OK')
"
chown -R www-data:www-data "$SITE_DIR/"

echo "=== DONE: https://artemisresort.com ==="
