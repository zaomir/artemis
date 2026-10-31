#!/usr/bin/env bash
# Artemis production deploy (server-side, no GitHub Actions, no webhook).
# Installed copy: /usr/local/sbin/artemis-deploy.sh  (run as root on vps2402)
#
#   artemis-deploy.sh            # fetch origin/main, unit tests, ff-only merge, restart, smoke
#   artemis-deploy.sh --check    # smoke only, no changes
#
# Tests (31.10.2026): before prod is switched, the NEW commit is exported to a temp dir and
# `python -m unittest discover -s tests` runs there with the app venv (has Flask). Any failure
# (or timeout) aborts the deploy — prod checkout and service are not touched.
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
TEST_PY="${ARTEMIS_TEST_PYTHON:-${APP_DIR}/venv/bin/python}"
TEST_TIMEOUT="${ARTEMIS_TEST_TIMEOUT:-600}"
G=(git -c "safe.directory=${APP_DIR}" -C "${APP_DIR}")

exec 9>/run/artemis-deploy.lock
flock -n 9 || { echo "another artemis deploy is running" >&2; exit 2; }

log() { echo "$(date -u +%FT%TZ) $*" | tee -a "$LOG"; }

# /health: app liveness JSON {"ok":true} (PR #23), must be 200 locally and via Cloudflare.
PATHS=(/health /en/ /ru/ /es/ /fr/ /en/privacy/ /ru/privacy/ /es/privacy/ /fr/privacy/
       /en/terms/ /ru/terms/ /es/terms/ /fr/terms/)
# Tenerife RU prod (/tenerife/): must be 200 locally and via Cloudflare.
# Pages the author has not delivered yet (producto, construccion, proceso, faq) are
# added here when they ship (see app/tenerife_site/README.md).
TENERIFE_PATHS=(/tenerife/ /tenerife/norte/ /tenerife/producto/ /tenerife/acciones/ /tenerife/calculadora/
  /tenerife/alquiler/ /tenerife/energia/ /tenerife/construccion/ /tenerife/proceso/ /tenerife/faq/
  /tenerife/simon/ /tenerife/mercado/ /tenerife/boris/ /tenerife/impressum/ /tenerife/privacy/
  /static/tenerife/site/style.css /static/tenerife/site/site.css /static/tenerife/site/waitlist.js
  /static/tenerife/site/calc.js /static/tenerife/site/site.js /static/tenerife/site/model.json /sitemap.xml /robots.txt)
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
    # optional pages: must not 5xx (404 tolerated if the route is not shipped yet;
    # 301 since r4/T47: /tenerife-preview/ is retired and redirects to /tenerife/)
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "${LOCAL}${p}" || true)
    [[ "$code" =~ ^(200|301|404)$ ]] || { log "SMOKE FAIL local ${p} -> ${code}"; fail=1; }
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

run_tests() {
  local dir rc=0
  dir=$(mktemp -d /tmp/artemis-deploy-test.XXXXXX)
  "${G[@]}" archive "$NEW" | tar -x -C "$dir"
  log "tests: python -m unittest discover -s tests @ ${NEW:0:7}"
  ( cd "$dir" && HOME="$dir" timeout "$TEST_TIMEOUT" "$TEST_PY" -m unittest discover -s tests ) \
    >"$dir.log" 2>&1 || rc=$?
  log "tests: $(grep -E '^(Ran |OK|FAILED)' "$dir.log" | tr '\n' ' ')(rc=${rc})"
  if [[ $rc -ne 0 ]]; then
    cp "$dir.log" "/var/log/artemis-deploy-tests-${NEW:0:7}.log" 2>/dev/null || true
    log "tests log: /var/log/artemis-deploy-tests-${NEW:0:7}.log"
  fi
  rm -rf "$dir" "$dir.log"
  return $rc
}

if ! run_tests; then
  log "ABORT: tests failed for ${NEW:0:7}; prod stays at ${OLD:0:7} (nothing changed)"
  exit 1
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
