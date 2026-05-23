#!/bin/bash
# ARTEMIS RESORT — Server Setup
# Run as root: bash setup_server.sh
set -e

REPO="https://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@github.com/zaomir/artemis.git"
SITE_DIR=/var/www/artemis
APP_PORT=8082

echo "=== Artemis Resort — Deploy from GitHub ==="

# 1. Clone / pull repo
if [ -d "$SITE_DIR/.git" ]; then
  echo "[1/6] Pulling latest..."
  cd "$SITE_DIR" && git pull
else
  echo "[1/6] Cloning repo..."
  git clone "$REPO" "$SITE_DIR"
fi

# 2. Venv
echo "[2/6] Python venv..."
python3 -m venv "$SITE_DIR/venv"
"$SITE_DIR/venv/bin/pip" install -q flask gunicorn 2>&1 | tail -2

# 3. Systemd
echo "[3/6] Systemd service..."
cat > /etc/systemd/system/artemis.service << SVC
[Unit]
Description=Artemis Resort Flask App
After=network.target
[Service]
User=www-data
WorkingDirectory=$SITE_DIR/app
ExecStart=$SITE_DIR/venv/bin/gunicorn -w 2 -b 127.0.0.1:$APP_PORT app:app
Restart=always
RestartSec=5
Environment=FLASK_ENV=production
[Install]
WantedBy=multi-user.target
SVC

systemctl daemon-reload
systemctl enable artemis
systemctl restart artemis
sleep 2
systemctl is-active artemis && echo "artemis: RUNNING" || { journalctl -u artemis -n 20; exit 1; }

# 4. Nginx
echo "[4/6] Nginx config..."
cat > /etc/nginx/sites-available/artemisresort.com << NGX
server {
    listen 80;
    server_name artemisresort.com www.artemisresort.com;
    location /static/ {
        alias $SITE_DIR/app/static/;
        expires 30d;
    }
    location / {
        proxy_pass http://127.0.0.1:$APP_PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
NGX

ln -sf /etc/nginx/sites-available/artemisresort.com /etc/nginx/sites-enabled/artemisresort.com
nginx -t && systemctl reload nginx && echo "nginx: OK"

# 5. DB
echo "[5/6] Init DB..."
"$SITE_DIR/venv/bin/python3" -c "
import sqlite3
conn = sqlite3.connect('$SITE_DIR/app/leads.db')
conn.execute('CREATE TABLE IF NOT EXISTS leads (id INTEGER PRIMARY KEY, name TEXT, email TEXT, phone TEXT, amount TEXT, created_at TEXT)')
conn.commit(); conn.close()
print('DB: OK')
"
chown -R www-data:www-data "$SITE_DIR/"

# 6. Update script (for future deploys)
echo "[6/6] Update script..."
cat > /usr/local/bin/artemis-update << UPDATE
#!/bin/bash
cd $SITE_DIR && git pull
systemctl restart artemis
echo "Updated OK"
UPDATE
chmod +x /usr/local/bin/artemis-update

echo ""
echo "========================================"
echo " DONE: http://artemisresort.com"
echo " Leads: http://artemisresort.com/admin/leads?t=rovlex2025"
echo " Update: artemis-update"
echo " SSL: certbot --nginx -d artemisresort.com -d www.artemisresort.com -m ROVLEX@ROVLEX.COM --agree-tos --no-eff-email"
echo "========================================"
