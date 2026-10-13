#!/bin/bash
# macOS (Bash 3.2+) / Linux. Docker only; no host Python, no application .env.
set -euo pipefail
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
cd "$ROOT"
command -v docker >/dev/null || { echo 'Docker CLI missing. Start Docker Desktop first.'; exit 2; }
case "${DOCKER_HOST:-}" in ''|unix://*|npipe://*) ;; *) echo 'Remote DOCKER_HOST rejected.'; exit 2;; esac
CTX="$(docker context show)"
ENDPOINT="$(docker context inspect "$CTX" --format '{{.Endpoints.docker.Host}}')"
case "$ENDPOINT" in unix://*|npipe://*) ;; *) echo 'Remote Docker context rejected.'; exit 2;; esac
unset DOCKER_HOST DOCKER_DEFAULT_PLATFORM
for K in COMPOSE_FILE COMPOSE_PROJECT_NAME COMPOSE_PROFILES COMPOSE_ENV_FILES COMPOSE_PATH_SEPARATOR COMPOSE_REMOVE_ORPHANS; do unset "$K"; done
export COMPOSE_DISABLE_ENV_FILE=1
D=(docker --context "$CTX")
[ "$("${D[@]}" info --format '{{.OSType}}')" = linux ] || { echo 'Use the local Linux engine.'; exit 2; }
PROJECT="adc_verify_$(date -u +%Y%m%d%H%M%S)_$$_${RANDOM}"
EMPTY_ENV="$(mktemp "${TMPDIR:-/tmp}/adc_verify.XXXXXX")"
printf '# Empty: never load the application .env\n' > "$EMPTY_ENV"
mkdir -p "$ROOT/evidence/verification"
CONFIG="$ROOT/evidence/verification/config-$PROJECT.json"
DC=("${D[@]}" compose --env-file "$EMPTY_ENV" --project-directory "$ROOT" -p "$PROJECT" -f "$ROOT/compose.verify.yaml")
STARTED=0
finish() {
  RESULT=$?
  trap - EXIT INT TERM
  CLEANUP=0
  if [ "$STARTED" = 1 ]; then
    "${DC[@]}" down --remove-orphans || CLEANUP=$?
  fi
  rm -f -- "$EMPTY_ENV"
  printf 'Verification exit: %s; cleanup exit: %s\n' "$RESULT" "$CLEANUP"
  printf 'Evidence: %s/evidence/verification\n' "$ROOT"
  echo 'No existing ADC project or data volume was upgraded/deleted.'
  if [ "$CLEANUP" != 0 ]; then exit 1; fi
  exit "$RESULT"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
"${DC[@]}" config --format json > "$CONFIG"
# Validate before creating project services; only a network-disabled Python helper
# sees the source/config mounts. No Docker socket is mounted.
"${D[@]}" run --rm --network none \
  --mount "type=bind,source=$ROOT,target=/src,readonly" \
  --mount "type=bind,source=$CONFIG,target=/isolation.json,readonly" \
  -w /src python:3.13-slim \
  python scripts/verify_isolated.py --validate-config /isolation.json --source-root "$ROOT"
STARTED=1
"${DC[@]}" up --build --abort-on-container-exit --exit-code-from verify
