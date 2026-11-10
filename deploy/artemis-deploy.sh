#!/usr/bin/env bash
# Artemis production deploy (server-side, no GitHub Actions, no webhook).
# Installed copy: /usr/local/sbin/artemis-deploy.sh  (run as root on vps2402)
#
#   artemis-deploy.sh            # fetch origin/main, unit tests, ff-only merge, reload, smoke
#   artemis-deploy.sh --check    # smoke only, no changes
#
# Tests (31.10.2026): before prod is switched, the NEW commit is exported to a temp dir and
# `python -m unittest discover -s tests` runs there with the app venv (has Flask). Any failure
# (or timeout) aborts the deploy — prod checkout and service are not touched.
#
# Zero-downtime switch (QA PS-06, 31.10.2026): gunicorn gets SIGHUP instead of `systemctl restart`. The master
# keeps the listening socket, starts new workers (no --preload, so they import the new code) and only then
# stops the old ones gracefully - no window without a listener on 127.0.0.1:8082 (the restart caused a 502).
# If the service is not running, the master exits/changes after HUP, or the workers are not all replaced
# within 60 s, it falls back to restart.
# HUP goes to MainPID with plain `kill` (QA PR27-02: the systemctl kill "whom" option exists only in systemd >= 252).
#
# Safety: flock (no parallel runs), refuses dirty tree, ff-only (never rewrites
# history), smoke-checks local gunicorn + public Crete pages; on any failure
# resets to the previous HEAD, restarts and exits non-zero.
# QA PR27-01 (31.10.2026): once the code is switched, ANY error (ERR trap) or a failed reload ends in
# smoke -> ROLLBACK, never in a silent exit. State in $ARTEMIS_STATE_DIR (/var/lib/artemis-deploy):
#   pending   "OLD NEW" while a switch is not verified yet (left behind if the run was killed)
#   last_good last commit that passed smoke
#   failed    commit that was rolled back - not redeployed again unless ARTEMIS_RETRY_FAILED=1
# A rerun that finds the checkout "up to date" but failing smoke rolls back to the pre-deploy commit
# (pending) or last_good instead of reporting "no change deployed".
set -Eeuo pipefail

APP_DIR="${ARTEMIS_DIR:-/var/www/artemis}"
SERVICE="${ARTEMIS_SERVICE:-artemis}"
BRANCH="${ARTEMIS_BRANCH:-main}"
LOCAL="${ARTEMIS_LOCAL_URL:-http://127.0.0.1:8082}"
PUBLIC="${ARTEMIS_PUBLIC_URL:-https://artemisresort.com}"
LOG="${ARTEMIS_DEPLOY_LOG:-/var/log/artemis-deploy.log}"
TEST_PY="${ARTEMIS_TEST_PYTHON:-${APP_DIR}/venv/bin/python}"
TEST_TIMEOUT="${ARTEMIS_TEST_TIMEOUT:-600}"
RELOAD_TIMEOUT="${ARTEMIS_RELOAD_TIMEOUT:-60}"
STATE_DIR="${ARTEMIS_STATE_DIR:-/var/lib/artemis-deploy}"
PENDING="${STATE_DIR}/pending"
LAST_GOOD="${STATE_DIR}/last_good"
FAILED="${STATE_DIR}/failed"
G=(git -c "safe.directory=${APP_DIR}" -C "${APP_DIR}")

exec 9>"${ARTEMIS_LOCK:-/run/artemis-deploy.lock}"
flock -n 9 || { echo "another artemis deploy is running" >&2; exit 2; }

log() { echo "$(date -u +%FT%TZ) $*" | tee -a "$LOG"; }

# /health: app liveness JSON {"ok":true} (PR #23), must be 200 locally and via Cloudflare.
PATHS=(/health /en/ /ru/ /es/ /fr/ /en/privacy/ /ru/privacy/ /es/privacy/ /fr/privacy/
       /en/terms/ /ru/terms/ /es/terms/ /fr/terms/)
# Tenerife dual-path smoke (EN r2 vs legacy multi-locale pre-EN).
# Mode is chosen in smoke() by probing /tenerife/condiciones/ once:
#   200 -> EN r2 (condiciones + acciones + inversores; model.json/calc.js must 404; calculadora must 301)
#   else -> legacy (calculadora + calc.js + model.json + locale prefixes must 200; no strict EN 404/301)
# So the SAME installed script still passes smoke after ROLLBACK to a pre-EN tree.
TENERIFE_PATHS_EN=(/tenerife/ /tenerife/norte/ /tenerife/producto/ /tenerife/condiciones/
  /tenerife/energia/ /tenerife/construccion/ /tenerife/proceso/ /tenerife/faq/
  /tenerife/simon/ /tenerife/mercado/ /tenerife/boris/ /tenerife/inversores/ /tenerife/impressum/ /tenerife/privacy/
  /static/tenerife/site/style.css /static/tenerife/site/site.css /static/tenerife/site/waitlist.js
  /static/tenerife/site/site.js /sitemap.xml /robots.txt)
TENERIFE_404_EN=(/static/tenerife/site/model.json /static/tenerife/site/calc.js)
TENERIFE_PATHS_LEGACY=(/tenerife/ /tenerife/norte/ /tenerife/producto/ /tenerife/inversores/ /tenerife/calculadora/
  /tenerife/alquiler/ /tenerife/energia/ /tenerife/construccion/ /tenerife/proceso/ /tenerife/faq/
  /tenerife/simon/ /tenerife/mercado/ /tenerife/boris/ /tenerife/impressum/ /tenerife/privacy/
  /tenerife/ru/ /tenerife/ru/norte/ /tenerife/ru/producto/ /tenerife/ru/inversores/ /tenerife/ru/calculadora/
  /tenerife/ru/alquiler/ /tenerife/ru/energia/ /tenerife/ru/construccion/ /tenerife/ru/proceso/
  /tenerife/ru/faq/ /tenerife/ru/simon/ /tenerife/ru/mercado/ /tenerife/ru/boris/
  /tenerife/ru/impressum/ /tenerife/ru/privacy/
  /tenerife/es/ /tenerife/es/norte/ /tenerife/es/impressum/ /tenerife/es/privacy/
  /tenerife/de/ /tenerife/de/norte/ /tenerife/de/impressum/ /tenerife/de/privacy/
  /tenerife/fr/ /tenerife/fr/norte/ /tenerife/fr/impressum/ /tenerife/fr/privacy/
  /tenerife/equipo/ /tenerife/ru/equipo/
  /tenerife/es/inversores/ /tenerife/es/equipo/ /tenerife/es/calculadora/
  /tenerife/de/inversores/ /tenerife/de/equipo/ /tenerife/de/calculadora/
  /tenerife/fr/inversores/ /tenerife/fr/equipo/ /tenerife/fr/calculadora/
  /static/tenerife/site/style.css /static/tenerife/site/site.css /static/tenerife/site/waitlist.js
  /static/tenerife/site/calc.js /static/tenerife/site/site.js /static/tenerife/site/model.json /sitemap.xml /robots.txt)
EXTRA_PATHS=(${ARTEMIS_EXTRA_SMOKE:-/tenerife-preview/})

# MainPID of the unit, "0" if none / not a number
main_pid() {
  local p
  p=$(systemctl show -p MainPID --value "$SERVICE" 2>/dev/null) || p=0
  [[ "$p" =~ ^[0-9]+$ ]] || p=0
  echo "$p"
}

# child PIDs of the gunicorn master; empty output (master gone / no workers) is not an error (QA PR27-01)
workers() { { pgrep -P "$1" 2>/dev/null || true; } | sort; }

restart_app() {
  log "reload: $1 - restart"
  systemctl reset-failed "$SERVICE" 2>/dev/null || true
  systemctl restart "$SERVICE" || { log "reload: systemctl restart ${SERVICE} failed"; return 1; }
}

# graceful reload of gunicorn: SIGHUP to the master, wait until every old worker is replaced.
# Never aborts the script: every failure is logged, falls back to restart, and the caller runs smoke.
reload_app() {
  local main now old new n=0
  main=$(main_pid)
  if ! systemctl is-active -q "$SERVICE" || [[ "$main" == 0 ]]; then
    restart_app "${SERVICE} not running"; return
  fi
  old=$(workers "$main")
  if ! kill -s HUP "$main" 2>/dev/null; then
    restart_app "HUP to gunicorn ${main} failed"; return
  fi
  while (( n < RELOAD_TIMEOUT )); do
    sleep 1; n=$((n + 1))
    now=$(main_pid)
    if [[ "$now" != "$main" ]] || ! kill -0 "$main" 2>/dev/null; then
      restart_app "gunicorn master ${main} gone after HUP (MainPID now ${now}, ${n}s)"; return
    fi
    new=$(workers "$main")
    if [[ -n "$new" ]] && (( $(wc -l <<<"$new") >= $(wc -l <<<"$old") )) && [[ -z "$(comm -12 <(echo "$old") <(echo "$new"))" ]]; then
      log "reload: gunicorn ${main} HUP, workers replaced in ${n}s"; return 0
    fi
  done
  restart_app "workers not replaced in ${RELOAD_TIMEOUT}s"
}

smoke() {
  local fail=0 code p en_mode=0
  local -a tenerife_paths=() tenerife_404=()
  sleep 2
  for i in 1 2 3 4 5; do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "${LOCAL}/en/" || true)
    [[ "$code" == 200 ]] && break; sleep 2
  done
  # Version probe: EN r2 serves /tenerife/condiciones/ as 200; pre-EN trees do not.
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "${LOCAL}/tenerife/condiciones/" || true)
  if [[ "$code" == 200 ]]; then
    en_mode=1
    tenerife_paths=("${TENERIFE_PATHS_EN[@]}")
    tenerife_404=("${TENERIFE_404_EN[@]}")
    log "smoke: Tenerife EN mode (condiciones=${code})"
  else
    tenerife_paths=("${TENERIFE_PATHS_LEGACY[@]}")
    log "smoke: Tenerife legacy mode (condiciones=${code})"
  fi
  for p in "${PATHS[@]}" "${tenerife_paths[@]}"; do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "${LOCAL}${p}" || true)
    [[ "$code" == 200 ]] || { log "SMOKE FAIL local ${p} -> ${code}"; fail=1; }
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "${PUBLIC}${p}" || true)
    [[ "$code" == 200 ]] || { log "SMOKE FAIL public ${p} -> ${code}"; fail=1; }
  done
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "${PUBLIC}/tenerife/?lang=en" || true)
  [[ "$code" == 200 ]] || { log "SMOKE FAIL public /tenerife/?lang=en -> ${code}"; fail=1; }
  for p in "${EXTRA_PATHS[@]}"; do
    # optional pages: must not 5xx (404 tolerated if the route is not shipped yet;
    # 301 since r4/T47: /tenerife-preview/ is retired and redirects to /tenerife/)
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "${LOCAL}${p}" || true)
    [[ "$code" =~ ^(200|301|404)$ ]] || { log "SMOKE FAIL local ${p} -> ${code}"; fail=1; }
  done
  if (( en_mode )); then
    for p in "${tenerife_404[@]}"; do
      code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "${LOCAL}${p}" || true)
      [[ "$code" == 404 ]] || { log "SMOKE FAIL local ${p} -> ${code} (want 404)"; fail=1; }
    done
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "${LOCAL}/tenerife/calculadora/" || true)
    [[ "$code" == 301 ]] || { log "SMOKE FAIL /tenerife/calculadora/ -> ${code} (want 301 to /tenerife/condiciones/)"; fail=1; }
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "${LOCAL}/tenerife/acciones/" || true)
    [[ "$code" == 301 ]] || { log "SMOKE FAIL /tenerife/acciones/ -> ${code} (want 301 to /tenerife/inversores/)"; fail=1; }
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "${LOCAL}/tenerife/alquiler/" || true)
    [[ "$code" == 301 ]] || { log "SMOKE FAIL /tenerife/alquiler/ -> ${code} (want 301 to /tenerife/)"; fail=1; }
  fi
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "${LOCAL}/admin/leads" || true)
  [[ "$code" == 403 ]] || { log "SMOKE FAIL /admin/leads without token -> ${code} (want 403)"; fail=1; }
  return $fail
}

if [[ "${1:-}" == "--check" ]]; then
  smoke && { log "check OK"; exit 0; } || { log "check FAILED"; exit 1; }
fi

[[ $EUID -eq 0 || "${ARTEMIS_SKIP_ROOT_CHECK:-0}" == 1 ]] || { echo "run as root" >&2; exit 1; }
mkdir -p "$STATE_DIR"
if [[ -n "$("${G[@]}" status --porcelain --untracked-files=no)" ]]; then
  log "ABORT: tracked changes in ${APP_DIR} (hotfix on server?) — commit them to the repo first"
  exit 1
fi
cur=$("${G[@]}" rev-parse --abbrev-ref HEAD)
[[ "$cur" == "$BRANCH" ]] || { log "ABORT: ${APP_DIR} is on ${cur}, expected ${BRANCH}"; exit 1; }

# restore $1, restart, smoke; always exits 1 (the deploy did not go through)
rollback() {
  local to=$1
  trap - ERR
  log "ROLLBACK to ${to:0:7} ($2)"
  "${G[@]}" reset -q --hard "$to" || log "ROLLBACK: git reset --hard ${to:0:7} failed"
  systemctl reset-failed "$SERVICE" 2>/dev/null || true
  systemctl restart "$SERVICE" || log "ROLLBACK: systemctl restart ${SERVICE} failed"
  if smoke; then
    log "rollback OK"
    echo "$to" >"$LAST_GOOD"; rm -f "$PENDING"
  else
    log "ROLLBACK SMOKE ALSO FAILED — manual attention"
  fi
  exit 1
}

on_err() {  # ERR trap after the code switch: no silent exit, always smoke + rollback
  trap - ERR
  log "ERROR: rc=$1 at line $2 after switching ${OLD:0:7} -> ${NEW:0:7}"
  echo "$NEW" >"$FAILED" 2>/dev/null || true
  rollback "$OLD" "deploy step failed"
}

OLD=$("${G[@]}" rev-parse HEAD)
"${G[@]}" fetch -q origin "$BRANCH"
NEW=$("${G[@]}" rev-parse "origin/${BRANCH}")
if [[ "$OLD" == "$NEW" ]]; then
  log "up to date at ${OLD:0:7}; running smoke"
  p_old="" p_new=""
  if [[ -s "$PENDING" ]]; then read -r p_old p_new <"$PENDING" || true; fi
  if [[ -n "$p_old" && "$p_new" == "$OLD" && "$p_old" != "$OLD" ]]; then
    # previous run switched the code and died before smoke/rollback: make sure the workers run this code
    log "previous deploy ${p_old:0:7} -> ${OLD:0:7} did not finish - reload before smoke"
    reload_app || log "reload: failed (rc=$?) - checking with smoke"
  fi
  if smoke; then
    log "smoke OK"; echo "$OLD" >"$LAST_GOOD"; rm -f "$PENDING"; exit 0
  fi
  log "smoke FAILED at ${OLD:0:7} (up to date)"
  if [[ -n "$p_old" && "$p_new" == "$OLD" && "$p_old" != "$OLD" ]]; then
    echo "$OLD" >"$FAILED"
    rollback "$p_old" "unfinished deploy ${p_old:0:7} -> ${OLD:0:7}"
  fi
  systemctl reset-failed "$SERVICE" 2>/dev/null || true
  systemctl restart "$SERVICE" || log "systemctl restart ${SERVICE} failed"
  if smoke; then
    log "recovered by restart at ${OLD:0:7}"; echo "$OLD" >"$LAST_GOOD"; exit 0
  fi
  lg=$(cat "$LAST_GOOD" 2>/dev/null || true)
  if [[ -n "$lg" && "$lg" != "$OLD" ]] && "${G[@]}" merge-base --is-ancestor "$lg" "$OLD" 2>/dev/null; then
    echo "$OLD" >"$FAILED"
    rollback "$lg" "last good commit"
  fi
  log "smoke FAILED at ${OLD:0:7}, no known-good commit to roll back to — manual attention"
  exit 1
fi
if [[ "$(cat "$FAILED" 2>/dev/null || true)" == "$NEW" && "${ARTEMIS_RETRY_FAILED:-0}" != 1 ]]; then
  log "ABORT: ${NEW:0:7} already failed and was rolled back; prod stays at ${OLD:0:7}. Push a fix or rerun with ARTEMIS_RETRY_FAILED=1"
  exit 1
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
printf '%s %s\n' "$OLD" "$NEW" >"$PENDING"
trap 'on_err $? $LINENO' ERR
"${G[@]}" merge --ff-only -q "origin/${BRANCH}"
chown www-data:www-data "${APP_DIR}/leads.db" 2>/dev/null || true
reload_app || log "reload: failed (rc=$?) - checking with smoke"

if smoke; then
  trap - ERR
  log "deploy OK at ${NEW:0:7}"
  echo "$NEW" >"$LAST_GOOD"; rm -f "$PENDING" "$FAILED"
else
  echo "$NEW" >"$FAILED"
  rollback "$OLD" "smoke failed for ${NEW:0:7}"
fi
