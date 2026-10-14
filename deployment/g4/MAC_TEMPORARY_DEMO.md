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
Cloudflare configuration, and keeps logs private. It waits for actual tunnel
registration before changing the host and again after origin readiness. The
default `--protocol auto` permits QUIC-to-HTTP/2 fallback, with up to three
minutes for initial registration; `--protocol http2` is available on networks
without UDP egress. The actual registered protocol is recorded separately from
the configured preference. It records the assigned host
in runtime/maintenance/Nginx configuration, validates rendered Compose, and
recreates only this project's Web/gateway. Source images, database identity,
passwords and read-only mode remain pinned. A failed startup stops its tunnel.
After readiness succeeds, it also refreshes the links in the private
`.g4/private/DEMO_ACCESS.md`, preserving existing account/password entries.

`status` checks the recorded process identity, the actual loopback gateway's
database health response and the latest registration/termination event in the
private log. `RUNNING` requires registration plus healthy origin checks;
`DEGRADED` covers an unavailable origin, retired/reconnecting tunnel or missing
registration evidence. A retired tunnel is never offered as a sharing URL. `STOPPED`
does not print an obsolete sharing URL. Status exits nonzero for either failure
state and performs no restart or business write. It reports public HTTPS as
`NOT_CHECKED`; use the HTTPS probe separately to establish public reachability.

The stop helper compares both recorded PID and process start/command information
before signalling it. A reused PID is never killed. It also works when the
origin is unhealthy. Metadata from another project is refused, and
process-group/malformed PIDs are never signalled. Stopping closes the public
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
remain unexecuted; measured course capacity is tracked separately in
[capacity and stability](CAPACITY_AND_STABILITY.md). Overall G4 is partial and
RC1 retained.

Read the active URL and private accounts in `.g4/private/DEMO_ACCESS.md` on this
Mac. Credentials and database dumps are never committed to GitHub.

The operations follow-up passed 14 focused checks and 5 controlled Mac CLI/HTTP
cases, including an unavailable origin and an unrelated HTTP 200 response.
Private login-link refresh preserved account entries. The live origin and all
7 public HTTPS checks passed with the current tunnel still running; hostname
refresh was exercised in the private fixture. The latest regression passed
839 source checks and 705 Django tests. Evidence:
[status rehearsal](../../docs/evidence_g4/mac-status-reliability.json),
[live HTTPS](../../docs/evidence_g4/mac-status-network.json) and
[regression](../../docs/evidence_g4/mac-status-postgresql-gate.json).

The capacity follow-up passed the declared small-dataset read-only envelope:
20 users/20 GETs per second at origin, and a repeated public 10-user/10 GETs per
second run with 6,000/6,000 successes over ten minutes (p95 565.652 ms). Explicit
overload throttling, recovery and POST-only password budgeting passed. The
current hostname also passed 43 Chrome checks. Credentials, backup and business
facts were preserved. Earlier reconnect failures remain in the evidence;
continuous availability and write/large-dataset capacity remain unestablished.
The regression passed 859 source checks and 705 Django/PostgreSQL tests. See
[method and limits](CAPACITY_AND_STABILITY.md),
[measured evidence](../../docs/evidence_g4/capacity-and-stability.json) and
[regression](../../docs/evidence_g4/capacity-postgresql-gate.json).
