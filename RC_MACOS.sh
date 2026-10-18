#!/bin/bash
# macOS Bash 3.2+ / Linux. Use the installed local Docker engine only.
set -euo pipefail
umask 077
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
cd "$ROOT"

usage() {
  echo 'RC_MACOS.sh verify | prepare | new-demo --synthetic-empty-only'
  echo 'RC_MACOS.sh import-copy --trusted-synthetic-copy | start | stop | status'
}
die() { printf 'STOP: %s\n' "$*" >&2; exit 2; }
ACTION="${1:-}"
# An uncommitted/archive checkout cannot claim an identified application commit.
ADC_SOURCE_COMMIT=unknown
if command -v git >/dev/null 2>&1 && [ -z "$(git status --porcelain 2>/dev/null)" ]; then
  ADC_SOURCE_COMMIT="$(git rev-parse --verify HEAD 2>/dev/null || printf unknown)"
fi

case "$ACTION" in
  -h|--help|help) usage; exit 0 ;;
  new-demo) [ "$#" = 2 ] && [ "$2" = --synthetic-empty-only ] || { usage; exit 2; } ;;
  import-copy) [ "$#" = 2 ] && [ "$2" = --trusted-synthetic-copy ] || { usage; exit 2; } ;;
  verify|prepare|start|stop|status) [ "$#" = 1 ] || { usage; exit 2; } ;;
  *) usage; exit 2 ;;
esac

BIN="${ADC_DOCKER_BIN:-docker}"
if ! BIN="$(command -v "$BIN")"; then
  BIN=/Applications/Docker.app/Contents/Resources/bin/docker
  [ -x "$BIN" ] || die 'Docker CLI missing. Install and start Docker Desktop.'
fi
case "${DOCKER_HOST:-}" in ''|unix://*) ;; *) die 'Remote DOCKER_HOST rejected.' ;; esac
CTX="${DOCKER_CONTEXT:-$("$BIN" context show)}"
ENDPOINT="$("$BIN" context inspect "$CTX" --format '{{.Endpoints.docker.Host}}')"
case "$ENDPOINT" in unix://*) ;; *) die 'Use a local Unix-socket Docker context.' ;; esac
unset DOCKER_HOST DOCKER_DEFAULT_PLATFORM DOCKER_CONTEXT
for K in COMPOSE_FILE COMPOSE_PROJECT_NAME COMPOSE_PROFILES COMPOSE_ENV_FILES COMPOSE_PATH_SEPARATOR COMPOSE_REMOVE_ORPHANS RC_PROJECT RC_APP_SECRET RC_DB_PASSWORD RC_WEB_PORT RC_READ_ONLY; do
  unset "$K"
done
export COMPOSE_DISABLE_ENV_FILE=1
D=("$BIN" --context "$CTX")
[ "$("${D[@]}" info --format '{{.OSType}}')" = linux ] || die 'Start Docker Desktop with its local Linux engine.'

if [ "$ACTION" = verify ]; then
  export PATH="$(dirname -- "$BIN"):$PATH" DOCKER_CONTEXT="$CTX"
  exec /bin/bash "$ROOT/VERIFY_ISOLATED_MAC.sh"
fi
config() {
  "${D[@]}" run --rm --network none \
    --mount "type=bind,source=$ROOT,target=/workspace" -w /workspace \
    python:3.13-slim python scripts/rc_config.py "$1" --root /workspace
}
if [ "$ACTION" = prepare ]; then config prepare; exit 0; fi
[ -f .rc/compose.env ] || die 'Run ./RC_MACOS.sh prepare in this new working folder first.'
config validate
IFS= read -r PROJECT < .rc/project.txt
DC=("${D[@]}" compose --env-file "$ROOT/.rc/compose.env" --project-directory "$ROOT" -p "$PROJECT" -f "$ROOT/compose.rc.yaml")

fresh() {
  [ ! -e .rc/READY ] || die 'This RC instance was already initialized.'
  [ ! -e .env ] || die 'Use a clean working folder, without a previous .env.'
  VOLUMES="$("${D[@]}" volume ls --filter "name=^${PROJECT}_rc_data$" --format '{{.Name}}')"
  [ -z "$VOLUMES" ] || die 'The RC data volume already exists. Preserve it and diagnose before retrying.'
}
case "$ACTION" in
  new-demo)
    fresh
    "${DC[@]}" build --build-arg "ADC_SOURCE_COMMIT=$ADC_SOURCE_COMMIT"
    "${DC[@]}" up -d --wait db
    "${DC[@]}" run --rm schema
    "${DC[@]}" run --rm --no-deps bootstrap python manage.py bootstrap_release_demo > .rc/private/demo-credentials.txt
    printf 'synthetic-demo\n' > .rc/READY
    printf 'fresh-demo\n' > .rc/SOURCE_MODE
    echo 'Synthetic demo prepared. Credentials are in .rc/private/demo-credentials.txt.'
    echo 'Next: ./RC_MACOS.sh start'
    ;;
  import-copy)
    [ -f .rc/private/source.dump ] || die 'Missing the trusted synthetic backup at .rc/private/source.dump.'
    fresh
    "${DC[@]}" build --build-arg "ADC_SOURCE_COMMIT=$ADC_SOURCE_COMMIT"
    "${DC[@]}" up -d --wait db
    "${DC[@]}" run --rm --no-deps web python scripts/rc_database_guard.py
    "${DC[@]}" exec -T db pg_restore --list < .rc/private/source.dump > .rc/private/restore-contents.txt
    "${DC[@]}" exec -T db pg_restore --no-owner --no-privileges --single-transaction --exit-on-error -U adc_rc_owner -d adc_rc_demo < .rc/private/source.dump
    "${DC[@]}" exec -T db psql -X -U adc_rc_owner -d adc_rc_demo -At < scripts/rc_legacy_snapshot.sql > .rc/private/before-upgrade.txt
    "${DC[@]}" run --rm schema
    "${DC[@]}" exec -T db psql -X -U adc_rc_owner -d adc_rc_demo -At < scripts/rc_legacy_snapshot.sql > .rc/private/after-upgrade.txt
    cmp .rc/private/before-upgrade.txt .rc/private/after-upgrade.txt > .rc/private/upgrade-compare.txt
    printf 'imported-copy\n' > .rc/READY
    printf 'imported-v07-copy\n' > .rc/SOURCE_MODE
    echo 'Backup restored to a new RC database and the bounded legacy summary matched.'
    echo 'Review the private records before ./RC_MACOS.sh start.'
    ;;
  start)
    [ -f .rc/READY ] || die 'Initialize a new demo or a trusted backup copy before starting.'
    # Build the current checkout before stopping the previous runtime. A failed
    # build leaves that runtime available; schema uses the newly built image.
    "${DC[@]}" build --build-arg "ADC_SOURCE_COMMIT=$ADC_SOURCE_COMMIT"
    "${DC[@]}" --profile worker stop gateway web notification-worker
    "${DC[@]}" run --rm schema
    "${DC[@]}" --profile worker up -d web gateway notification-worker
    "${DC[@]}" --profile worker ps
    PORT="$(awk -F= '$1 == "RC_WEB_PORT" {print $2}' .rc/compose.env)"
    printf 'Local course demo: http://127.0.0.1:%s\n' "$PORT"
    ;;
  stop) "${DC[@]}" --profile worker stop gateway web notification-worker db ;;
  status) "${DC[@]}" --profile worker ps ;;
esac
