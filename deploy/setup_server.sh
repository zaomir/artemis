#!/bin/bash
# ARTEMIS RESORT — First-time server setup
# Run as root: GITHUB_TOKEN=... bash setup_server.sh   (token needed only for clone / pull)
set -euo pipefail

# QA PR24-01 (31.10.2026): the remote URL never carries a token. clone/pull get the token from the
# environment through a temporary GIT_ASKPASS script, so it is not written to .git/config and is
# not visible in the argv of git / git-remote-https (ps).
REPO_URL="https://github.com/zaomir/artemis.git"
SITE_DIR=/var/www/artemis
APP_PORT=8082

git_with_token() {
  # QA PR24-06: the token is checked only here, i.e. only where it is really needed.
  : "${GITHUB_TOKEN:?set GITHUB_TOKEN (needed for git clone/pull)}"
  local askpass rc=0
  askpass="$(mktemp)"
  chmod 700 "$askpass"
  trap 'rm -f "$askpass"' EXIT
  cat > "$askpass" << 'ASKPASS'
#!/bin/sh
case "$1" in
  Username*) printf '%s\n' x-access-token ;;
  *) printf '%s\n' "$GITHUB_TOKEN" ;;
esac
ASKPASS
  GITHUB_TOKEN="$GITHUB_TOKEN" GIT_ASKPASS="$askpass" GIT_TERMINAL_PROMPT=0 \
    git -c credential.helper= "$@" || rc=$?
  rm -f "$askpass"
  trap - EXIT
  return "$rc"
}

echo "=== Artemis Resort — Setup ==="

# Clone repo
if [ -d "$SITE_DIR/.git" ]; then
  echo "Repo exists — pulling..."
  cur_url="$(git -C "$SITE_DIR" remote get-url origin 2>/dev/null || true)"
  case "$cur_url" in
    *@github.com*)
      # old setup wrote https://<token>@github.com/... into .git/config: drop the credential
      git -C "$SITE_DIR" remote set-url origin "$REPO_URL"
      echo "origin URL reset to $REPO_URL (credential removed from .git/config)"
      ;;
  esac
  git_with_token -C "$SITE_DIR" pull
else
  git_with_token clone "$REPO_URL" "$SITE_DIR"
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
# QA PR24-05: same Cloudflare realip snippet as the deploy config (deploy/nginx-artemisresort.com.origin.conf);
# CF-Connecting-IP is always overwritten with the realip-resolved client address.
# QA PR24-07: the snippet comes from the repo; without it we stop instead of configuring nginx without realip.
REALIP_SRC="$SITE_DIR/deploy/nginx-snippets/cloudflare-realip.conf"
REALIP_SNIPPET=/etc/nginx/snippets/cloudflare-realip.conf
if [ ! -s "$REALIP_SRC" ]; then
  echo "ERROR: $REALIP_SRC not found in the checkout - cannot install the Cloudflare realip snippet" >&2
  exit 1
fi
install -D -m 644 "$REALIP_SRC" "$REALIP_SNIPPET"
if ! grep -q '^real_ip_header CF-Connecting-IP;' "$REALIP_SNIPPET"; then
  echo "ERROR: $REALIP_SNIPPET has no 'real_ip_header CF-Connecting-IP' - refusing to configure nginx without realip" >&2
  exit 1
fi
cat > /etc/nginx/sites-available/artemisresort.com << NGX
server {
    listen 80;
    server_name artemisresort.com www.artemisresort.com;
    server_tokens off;
    include /etc/nginx/snippets/cloudflare-realip.conf;
    location /static/ {
        alias $SITE_DIR/app/static/;
        expires -1;
        add_header Cache-Control "no-store, no-cache, must-revalidate, max-age=0";
        add_header Pragma "no-cache";
    }
    location /deploy-hook { proxy_pass http://127.0.0.1:9001; proxy_set_header X-Hook-Secret \$http_x_hook_secret; proxy_set_header CF-Connecting-IP \$remote_addr; proxy_set_header X-Real-IP \$remote_addr; }
    location / { proxy_pass http://127.0.0.1:$APP_PORT; proxy_set_header Host \$host; proxy_set_header CF-Connecting-IP \$remote_addr; proxy_set_header X-Real-IP \$remote_addr; }
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
