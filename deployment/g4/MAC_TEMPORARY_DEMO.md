# Free temporary Mac course demonstration

Logic chain: separate synthetic read-only instance → free HTTPS tunnel → browser
checks → share the temporary address → stop the tunnel when the demo ends.

The user selected this topology on 2026-10-13. No server, domain purchase,
Cloudflare account, DNS change or router port forwarding is required. Cloudflare
Quick Tunnel assigns a random `*.trycloudflare.com` hostname and public HTTPS.
The URL changes when the tunnel restarts and stops working when the tunnel exits.
The Mac must remain awake and connected, with Docker Desktop running.

This is a course demonstration（课程演示）using new synthetic data, business
read-only mode and disabled external AI. Session login/context selection still
work; business commands and the notification writer remain disabled. The
existing Mac RC project and its port 18000 stay separate.

## Local preparation

Use a reviewed source revision, `Dockerfile.production` image ID, pinned PG17
and Nginx digests. The application container uses UID 10001; owner maintenance
and runtime database credentials remain separate. Download `cloudflared` only
from the official release and verify the release asset SHA-256 before executing.
The client and all `.g4` configuration, logs, seed credentials and backups are
private and excluded from Git/Docker build context.

Create a new `.g4` bundle with `g4_prepare.py prepare --mode mac_tunnel`, a
temporary placeholder `pending.trycloudflare.com`, and `--http-port 18020`.
Use the full source commit and immutable images as in the main guide. The
placeholder is only for local initialization; the start helper replaces it with
the actual assigned hostname before making the app available.

Every Docker operation must select `--context desktop-linux`, `-p` with the exact
project from `.g4/plan.json`, `--env-file .g4/compose.env`, and
`-f .g4/compose.yaml`. Render all profiles into a mode-600 private JSON and inspect
with `g4_prepare.py inspect --rendered-compose` before starting anything.
Start DB, run schema, and seed a fresh demo once with stdout redirected to a
mode-600 private credential file. Never seed existing data. Start Web/gateway
locally; inspect role privileges, health and Nginx configuration.

Only `127.0.0.1:18020` publishes the HTTP origin. Web/PG have no published ports.
Public TLS terminates at Cloudflare; its authenticated outbound tunnel carries
requests to the loopback origin. Cloudflare overwrites client-supplied
`X-Forwarded-Proto`; the dedicated Nginx configuration redirects HTTP and sets
the upstream scheme itself. Never bind this HTTP origin to a public/LAN address.
There is no origin certificate verification bypass.

## Start, inspect and stop

From the Mac project directory, after the separate local gateway is initialized:

```sh
python3 scripts/g4_mac_demo.py start \
  --cloudflared .runtime/tools/cloudflared-2026.10.0
python3 scripts/g4_mac_demo.py status
python3 scripts/g4_mac_demo.py stop
```

The start helper checks the actual gateway binding, uses a dedicated empty
Cloudflare configuration, and keeps logs private. It records the assigned host
in runtime/maintenance/Nginx configuration, validates rendered Compose, and
recreates only this project's Web/gateway. Source images, database identity,
passwords and read-only mode remain pinned. A failed startup stops its tunnel.

The stop helper compares both recorded PID and process start/command information
before signalling it. A reused PID is never killed. Stopping closes the public
entry without deleting or stopping the database. Restart via `start` after the
previous tunnel has stopped; use the new printed URL for sharing. Never use an
old address as evidence that the current demo is reachable.

## Acceptance scope

Verify the actual public hostname with `g4_https_probe.py`: trusted HTTPS,
canonical HTTP redirect, static files, secure cookies, HSTS, Host/proxy behavior.
Use a real browser for staff/patient login, role/workspace routing, CSRF and
read-only refusal. Compare business facts before and after rejected commands.
Check service restart and independent private backup/restore without modifying
the existing Mac project. Keep a private backup outside this Mac for host loss.

A temporary URL and browser PASS establish bounded demonstration evidence.
They do not establish continuous availability, an independently recovered
server, production capacity, or recovery of the reset Windows database. Record
these components separately in G4; retain RC1 while release requirements remain.

Cloudflare Quick Tunnels are for development/testing, have no uptime SLA, and
currently limit concurrent in-flight requests to 200. This is a provider limit,
not a measured capacity of this Django app. The demo does not use SSE.

References checked 2026-10-13:

- [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)
- [Cloudflare request headers](https://developers.cloudflare.com/fundamentals/reference/http-request-headers/)
- [Official client release 2026.10.0](https://github.com/cloudflare/cloudflared/releases/tag/2026.10.0)

## Recorded demonstration result

The temporary demo passed 7 public HTTPS checks from both this Mac and an
independent GitHub runner, 43 real Chrome checks across 9 seeded accounts, and
a private restore into a different empty PostgreSQL project. Stable business
facts remained unchanged after rejected writes. Web/gateway service restart
also passed; the source image, business schema and data volume were preserved.

Evidence: [bounded acceptance](../../docs/evidence_g4/mac-public-demo.json),
[external runner](../../docs/evidence_g4/external-network.json) and
[regression](../../docs/evidence_g4/mac-postgresql-gate.json). The local regression
passed 828 source checks and 705 Django tests. Off-host recovery, whole-Mac reboot
and measured capacity remain unexecuted; overall G4 is partial and RC1 retained.

Read the active URL and private accounts in `.g4/private/DEMO_ACCESS.md` on this
Mac. Credentials and database dumps are never committed to GitHub.
