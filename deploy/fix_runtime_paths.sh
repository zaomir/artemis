#!/bin/bash
# Ensure artemis systemd + nginx point at app/ (not legacy root app.py)
set -euo pipefail

SITE_DIR=/var/www/artemis
APP_PORT=8082

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

python3 - << 'PYEOF'
import re
path = '/etc/nginx/sites-available/artemisresort.com'
with open(path) as f:
    content = f.read()
new_block = """location /static/ {
        alias /var/www/artemis/app/static/;
        expires -1;
        add_header Cache-Control "no-store, no-cache, must-revalidate, max-age=0";
        add_header Pragma "no-cache";
    }"""
content = re.sub(r'location /static/\s*\{[^}]+\}', new_block, content, count=1)
with open(path, 'w') as f:
    f.write(content)
print('nginx: static -> app/static')
PYEOF

systemctl daemon-reload
systemctl restart artemis
nginx -t
systemctl reload nginx
systemctl is-active artemis
curl -fsS "http://127.0.0.1:$APP_PORT/" | grep -q 'v[0-9]' && echo 'smoke: version footer OK'
