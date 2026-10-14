# Bounded Mac course-demo capacity and stability

Logic chain: declare workload（负载）→ record the first failure → fix → ramp →
sustained public run（持续公网测试）→ compare business facts → regression.

The selected target is the separate synthetic, business-read-only Mac G4
instance. Its immutable application image, PostgreSQL 17 database, runtime
role, data volume, timezone and external-AI-disabled state remain pinned.
The original RC instance on port 18000 is separate.

## Acceptance envelope

| Item | Declared test target |
|---|---|
| Sustained load | 10 virtual users, 10 authenticated HTML GETs/second, 600 seconds |
| Accounts/data | 9 preflighted seeded accounts; initial dataset: 4 patients, 14 slots, 0 visits |
| Origin ramp | 1/5/10/20 users at 1/5/10/20 requests/second |
| Public ramp | 1/5/10 users at 1/5/10 requests/second |
| Normal success | Every offered request succeeds; zero queue drops, redirects, wrong-page responses or transport errors |
| Response time | End-to-end successful p95 ≤ 2 seconds at origin, ≤ 5 seconds publicly |
| Cold connections | Separate authenticated warmup per worker; every response succeeds within the same time bound |
| Controlled overload | 40 requests/second: some successes and explicit HTTP 429; no other failures/drops |
| Resource continuity | Every sample healthy; no OOM, container restart or changed container start time |
| Database | ≤ 20 runtime-role connections, no sampled idle transaction or waiting lock |
| Memory | Web last-quarter median growth ≤ 64 MiB relative to first-quarter median |
| Facts | Allowlisted business hash/counts unchanged after the test |

Virtual users reuse the nine seeded sessions; they do not represent newly
registered people. The workload covers front desk A/B, manager, doctor, patient
A/B, finance, headquarters and technical workspaces, including patient/visit,
availability, task, portal and quarter listing routes. The captured data size
defines the measurement scope; larger clinical datasets require separate tests.

The open-loop scheduler keeps offering the declared rate independently of
response completion. It bounds pending work to twice the worker count. A full
queue is recorded as a failed offered request. Response time includes scheduler
and queue delay. No failed request is retried or redirected into a login page
and then counted as success. Reported warmup requests are additional to timed
requests; a failed/slow warmup keeps the overall phase failed.

## Reproduce on the prepared Mac target

Run from the Mac project directory with Docker Desktop and the current registered
tunnel available. Normal CSRF-protected login and signed clinic selection happen
only in setup. Seed credentials, session cookies and raw reports stay in the
private `.g4/private` folder, excluded from Git and Docker build context.

```sh
SSL_CERT_FILE=/etc/ssl/cert.pem python3 scripts/g4_load.py setup
SSL_CERT_FILE=/etc/ssl/cert.pem python3 scripts/g4_load.py run \
  --scope origin --users 20 --rps 20 --duration 30 --report origin-20.json
SSL_CERT_FILE=/etc/ssl/cert.pem python3 scripts/g4_load.py run \
  --scope origin --users 20 --rps 40 --duration 20 \
  --expect-throttle --report overload-40.json
SSL_CERT_FILE=/etc/ssl/cert.pem python3 scripts/g4_load.py run \
  --scope public --users 10 --rps 10 --duration 600 --report public-soak.json
```

During the sustained run, launch the bounded observer in a second terminal:

```sh
python3 scripts/g4_observe.py --duration 630 --interval 15
```

The observer verifies explicit project/service/image ownership before sampling
the three existing containers. It issues read-only aggregate PostgreSQL queries,
checks the real loopback health response, and records resource use and Gunicorn
worker replacement. Gunicorn's planned `max_requests` worker recycling is
distinct from a container crash/restart. Failed observations remain failures.

Public HTTPS uses normal certificate and original-hostname verification. The
clients honor the Mac's configured HTTP proxy using CONNECT for HTTPS; proxy
credentials stay on CONNECT and are not forwarded to the application. An
explicit `g4_https_probe.py --connect-ip` retains its reviewed direct target.
System network settings are not changed. Origin mode is loopback proxy-scheme
emulation; public mode measures the actual free hostname through HTTPS.

## Repairs exposed by validation

1. The original 5-request/second origin-peer bucket rejected 10 of 60 requests
   in a 10-request/second health baseline. Mac tunnel traffic now uses the
   Cloudflare-supplied client key with a peer fallback, plus a 20-request/second
   gateway-wide dynamic-request bucket. Only loopback may expose this origin. Client-provided
   forwarding chains or session cookies never select the rate bucket.
2. Login GETs previously consumed the password-attempt budget. The strict
   10/minute, burst-10 login bucket now applies to POST only. General and global
   admission limits still apply to login GETs and POSTs.
3. The old temporary tunnel was retired by the provider: `Unauthorized: Tunnel
   not found`, despite a live process and healthy origin. Status now reports
   `RETIRED`/`DEGRADED`; start waits for registration before publishing readiness.
   Replacing that owned tunnel updates only the hostname/entry links while
   preserving credentials, immutable images and database facts.
4. The first public single-user ramp dropped one offered request while its
   initial TLS connection opened. Cold connection setup is now measured/gated
   separately before the steady scheduler starts. The failed initial result is
   retained; the queue and zero-failure acceptance rules remain enforced.
5. The first ten-minute public run failed: 5,943 of 6,000 requests succeeded,
   with 10 transport errors and 47 HTTP 530 responses around a tunnel reconnect.
   Its local service/resource observation passed. The helper now supports
   `auto`, `quic` and `http2`, records the actually registered protocol, and
   allows up to three minutes for automatic QUIC-to-HTTP/2 fallback. This Mac's
   network timed out on QUIC and subsequently registered HTTP/2. A later
   account preflight also stopped during a reconnect, before measurement; all
   nine accounts were then checked successfully before the repeated run.
   Neither fallback nor a successful short window proves that reconnect gaps
   have been eliminated. Original failures remain part of the evidence.
6. After the successful measured window, automatic selection returned to QUIC
   when HTTP/2 disconnected. QUIC dial timeouts then delayed recovery for
   minutes. The Mac helper retains HTTP/2 as its default; automatic selection
   remains an explicit option. This avoids re-probing blocked UDP on this host,
   while short HTTP/2 reconnect gaps and continuous availability remain outside
   the accepted envelope. A replacement hostname is checked separately; the
   measured window retains its actual original hostname and timestamps.

## Recorded bounded result — 2026-10-14

| Phase | Offered requests | Actual outcome | Successful p95 |
|---|---:|---|---:|
| Origin 20 users / 20 GETs per second / 30 seconds | 600 | 600 HTTP 200; no drops | 30.987 ms |
| Public 10 users / 10 GETs per second / 600 seconds | 6,000 | 6,000 HTTP 200; no drops | 565.652 ms |
| Origin controlled overload / 40 GETs per second / 20 seconds | 800 | 423 HTTP 200, 377 HTTP 429; no other failures/drops | 29.809 ms |
| Post-overload recovery / 10 GETs per second / 10 seconds | 100 | 100 HTTP 200; no drops | 37.310 ms |

The repeated public window lasted 600.354 seconds. Its ten additional cold
connections passed, with maximum startup latency 2,879.299 ms. The observer
captured 37 samples over about 630 seconds: every container stayed healthy,
with no sampled OOM, restart, idle transaction or waiting lock. Peak observed
Web memory was 123.2 MiB, and the first-to-last-quarter median changed by
−1.4 MiB. At most two runtime-role database connections were sampled. Planned
Gunicorn worker recycling occurred without a container restart.

The real gateway fixture admitted eleven no-CSRF POSTs to the existing CSRF
refusal (403), then limited thirteen with 429; all twelve subsequent login GETs
returned 200. This uses a documentation client key at trusted loopback; it does
not prove trust in arbitrary public forwarding headers. All 43 current-host
Chrome checks and all seven HTTPS checks passed. Allowlisted committed business
hash/counts, credentials, backup, immutable images, PG17 and timezone stayed
unchanged; only the temporary hostname and private login links changed.

The successful repeated window does not erase the earlier 57 failed requests
or the reconnecting preflight. Continuous tunnel availability and write/large-
dataset capacity remain unestablished. Overall G4 stays `PARTIAL`.

## Evidence and remaining scope

The sanitized record is `docs/evidence_g4/capacity-and-stability.json`; private
session files, logs, backup and data snapshots stay local. The acceptance record
separates bounded course capacity/stability from off-Mac recovery, whole-host
reboot and continuous availability. A short stable window does not prove the
absence of a memory leak or a maximum sustainable capacity. Overall G4 remains
partial until its other required components have evidence.

References checked 2026-10-14:

- [Nginx rate limiting and empty-key behavior](https://nginx.org/en/docs/http/ngx_http_limit_req_module.html)
- [Cloudflare original client/proxy headers](https://developers.cloudflare.com/fundamentals/reference/http-request-headers/)
- [Quick Tunnel limitations](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)
- [Python system proxy discovery](https://docs.python.org/3/library/urllib.request.html#urllib.request.getproxies)
- [Python HTTP CONNECT](https://docs.python.org/3/library/http.client.html#http.client.HTTPConnection.set_tunnel)
- [Cloudflared 2026.10.0 protocol selection](https://github.com/cloudflare/cloudflared/blob/2026.10.0/connection/protocol.go)
- [Cloudflared Quick Tunnel connection scope](https://github.com/cloudflare/cloudflared/blob/2026.10.0/cmd/cloudflared/tunnel/quick_tunnel.go)
