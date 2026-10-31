#!/usr/bin/env bash
# Artemis production deploy (server-side, no GitHub Actions, no webhook).
# Installed copy: /usr/local/sbin/artemis-deploy.sh  (run as root on vps2402)
#
#   artemis-deploy.sh            # fetch origin/main, ff-only merge, restart, smoke
#   artemis-deploy.sh --check    # smoke only, no changes
#
# Safety: flock (no parallel runs), refuses dirty tree, ff-only (never rewrites
# history), smoke-checks local gunicorn + public Crete pages; on any failure
# resets to the previous HEAD, restarts and exits non-zero.
set -Eeuo pipefail

APP_DIR="${ARTEMIS_DIR:-/var/www/artemis}"
SERVICE="${ARTEMIS_SERVICE:-artemis}"
BRANCH="${ARTEMIS_BRANCH:-main}"
LOCAL="http://127.0.0.1:8082"
PUBLIC="${ARTEMIS_PUBLIC_URL:-https://artemisresort.com}"
LOG="${ARTEMIS_DEPLOY_LOG:-/var/log/artemis-deploy.log}"
G=(git -c "safe.directory=${APP_DIR}" -C "${APP_DIR}")

exec 9>/run/artemis-deploy.lock
flock -n 9 || { echo "another artemis deploy is running" >&2; exit 2; }

log() { echo "$(date -u +%FT%TZ) $*" | tee -a "$LOG"; }

PATHS=(/en/ /ru/ /es/ /fr/ /en/privacy/ /ru/privacy/ /es/privacy/ /fr/privacy/
       /en/terms/ /ru/terms/ /es/terms/ /fr/terms/)
# Tenerife RU prod (/tenerife/): must be 200 locally and via Cloudflare.
# Pages the author has not delivered yet (producto, construccion, proceso, faq) are
# added here when they ship (see app/tenerife_site/README.md).
TENERIFE_PATHS=(/tenerife/ /tenerife/norte/ /static/tenerife/site/style.css /static/tenerife/site/waitlist.js /sitemap.xml /robots.txt)
EXTRA_PATHS=(${ARTEMIS_EXTRA_SMOKE:-/tenerife-preview/})

smoke() {
  local fail=0 code p
  sleep 2
  for i in 1 2 3 4 5; do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "${LOCAL}/en/" || true)
    [[ "$code" == 200 ]] && break; sleep 2
  done
  for p in "${PATHS[@]}" "${TENERIFE_PATHS[@]}"; do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "${LOCAL}${p}" || true)
    [[ "$code" == 200 ]] || { log "SMOKE FAIL local ${p} -> ${code}"; fail=1; }
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "${PUBLIC}${p}" || true)
    [[ "$code" == 200 ]] || { log "SMOKE FAIL public ${p} -> ${code}"; fail=1; }
  done
  for p in "${EXTRA_PATHS[@]}"; do
    # optional pages: must not 5xx (404 tolerated if the route is not shipped yet)
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "${LOCAL}${p}" || true)
    [[ "$code" =~ ^(200|404)$ ]] || { log "SMOKE FAIL local ${p} -> ${code}"; fail=1; }
  done
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "${LOCAL}/admin/leads" || true)
  [[ "$code" == 403 ]] || { log "SMOKE FAIL /admin/leads without token -> ${code} (want 403)"; fail=1; }
  return $fail
}

if [[ "${1:-}" == "--check" ]]; then
  smoke && { log "check OK"; exit 0; } || { log "check FAILED"; exit 1; }
fi

[[ $EUID -eq 0 ]] || { echo "run as root" >&2; exit 1; }
if [[ -n "$("${G[@]}" status --porcelain --untracked-files=no)" ]]; then
  log "ABORT: tracked changes in ${APP_DIR} (hotfix on server?) — commit them to the repo first"
  exit 1
fi
cur=$("${G[@]}" rev-parse --abbrev-ref HEAD)
[[ "$cur" == "$BRANCH" ]] || { log "ABORT: ${APP_DIR} is on ${cur}, expected ${BRANCH}"; exit 1; }

OLD=$("${G[@]}" rev-parse HEAD)
"${G[@]}" fetch -q origin "$BRANCH"
NEW=$("${G[@]}" rev-parse "origin/${BRANCH}")
if [[ "$OLD" == "$NEW" ]]; then
  log "up to date at ${OLD:0:7}; running smoke"
  smoke && { log "smoke OK"; exit 0; } || { log "smoke FAILED (no change deployed)"; exit 1; }
fi

log "deploy ${OLD:0:7} -> ${NEW:0:7}"
"${G[@]}" merge --ff-only -q "origin/${BRANCH}"
chown www-data:www-data "${APP_DIR}/leads.db" 2>/dev/null || true
systemctl restart "$SERVICE"

if smoke; then
  log "deploy OK at ${NEW:0:7}"
else
  log "ROLLBACK to ${OLD:0:7}"
  "${G[@]}" reset -q --hard "$OLD"
  systemctl restart "$SERVICE"
  smoke && log "rollback OK" || log "ROLLBACK SMOKE ALSO FAILED — manual attention"
  exit 1
fi
