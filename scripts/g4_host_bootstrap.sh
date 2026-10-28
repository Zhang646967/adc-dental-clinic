#!/bin/sh
# Dedicated, newly purchased Ubuntu host only. Never run on the Mac or an
# existing application host. No DB, volume, firewall or SSH configuration edits.
set -eu
[ "${1:-}" = "--new-course-server" ]
[ "$(id -u)" = 0 ]
. /etc/os-release
[ "$ID" = ubuntu ] && [ "$VERSION_ID" = 24.04 ]
[ "$(uname -m)" = x86_64 ]
if command -v docker >/dev/null 2>&1; then
    [ -z "$(docker --context default ps -q)" ]
fi
# Refuse existing public services; the operator must identify their owner.
[ -z "$(ss -H -ltn 'sport = :80 or sport = :443')" ]
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl python3 python3-venv age certbot
if ! command -v docker >/dev/null 2>&1; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    printf '%s\n' 'Types: deb' 'URIs: https://download.docker.com/linux/ubuntu' 'Suites: noble' \
      'Components: stable' 'Architectures: amd64' 'Signed-By: /etc/apt/keyrings/docker.asc' \
      > /etc/apt/sources.list.d/adc-course-docker.sources
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker
docker --context default compose version >/dev/null
printf 'Dedicated Ubuntu course host dependencies ready. No cloud acceptance granted.\n'
