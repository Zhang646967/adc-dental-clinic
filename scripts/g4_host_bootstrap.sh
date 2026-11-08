#!/bin/sh
# Dedicated, newly purchased Ubuntu host only. Never run on the Mac or an
# existing application host. --preflight performs only read-only checks.
set -eu
case "${1:-}" in
    --preflight|--new-course-server) ;;
    *) exit 2 ;;
esac
reject() {
    printf '%s\n' "$1" >&2
    exit 1
}
[ "$(id -u)" = 0 ] || reject 'Course publication requires root or non-interactive sudo.'
. /etc/os-release
[ "$ID" = ubuntu ] && [ "$VERSION_ID" = 24.04 ] || reject 'Use a dedicated Ubuntu 24.04 host.'
[ "$(uname -m)" = x86_64 ] || reject 'Use an amd64 host for the reviewed application image.'
docker_root=/var/lib/docker
if command -v docker >/dev/null 2>&1; then
    running="$(docker --context default ps -q)"
    [ -z "$running" ] || reject 'The target already has running containers.'
    if [ "$1" = "--preflight" ]; then
        docker_root="$(docker --context default info --format '{{.DockerRootDir}}')"
    fi
fi
listeners="$(ss -H -ltn 'sport = :80 or sport = :443')"
[ -z "$listeners" ] || reject 'Identify the existing HTTP or HTTPS listener before publication.'
if [ "$1" = "--preflight" ]; then
    python3 - "$2" "$3" "$docker_root" <<'PY'
from pathlib import Path
import os
import sys

gib = 1024 ** 3
release, archive_bytes, docker = Path(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3])
if release.exists() or release.is_symlink():
    sys.exit('The first-publication directory already exists; inspect its retained state.')

def existing_parent(path):
    while not path.exists():
        path = path.parent
    return path

required = {}
for path, needed in ((release.parent, archive_bytes + 2 * gib),
                     (docker, max(8 * gib, 2 * archive_bytes))):
    parent = existing_parent(path)
    device = parent.stat().st_dev
    required[device] = (parent, required.get(device, (None, 0))[1] + needed)
for parent, needed in required.values():
    fs = os.statvfs(parent)
    if fs.f_bavail * fs.f_frsize < needed:
        sys.exit('Insufficient free space for the release archives and Docker data.')

memory = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
if (int(memory['MemTotal'].split()[0]) < 3 * 1024 ** 2
        or int(memory['MemAvailable'].split()[0]) < 2 * 1024 ** 2):
    sys.exit('Insufficient memory for first initialization: need 3 GiB total and 2 GiB available.')
print('HOST_PREFLIGHT_READY')
PY
    exit
fi
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
