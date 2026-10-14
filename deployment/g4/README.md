# G4 preparation: course demonstration with synthetic data

Logic chain: freeze source/image → create separate private credentials → migrate
with the owner → serve with the restricted runtime → verify DNS/TLS and recovery.

This package is preparation for public acceptance（公网验收）, not a completed
public deployment. The first target starts in business read-only mode with
external AI disabled. Mac `.rc`, credentials, data volumes and port 18000 are
separate. Only the gateway publishes ports; Web, worker and PostgreSQL remain
on the internal Docker network.

The user selected a **temporary demonstration on this Mac with a free hostname**.
Follow [Mac temporary demo](MAC_TEMPORARY_DEMO.md): Cloudflare Quick Tunnel supplies
the hostname and public HTTPS, with no server/domain purchase or DNS changes.
The Mac, Docker and tunnel must stay running; restarting the tunnel changes its
hostname. This selection does not establish permanent deployment/recovery.

The separately prepared Linux topology is a new, dedicated Docker Compose project with
PostgreSQL 17 on the same host. Existing reverse proxies, managed databases,
CDNs, or IPv6 need a target-specific adaptation after their details are known.

## Information for a later Linux host

| Item | Needed details |
|---|---|
| Server | Already purchased or not; provider/region; public IPv4 and any IPv6; OS/version; CPU architecture, vCPU, RAM and free disk; Docker/Compose installed or not. |
| Access | Prefer an existing Mac SSH alias. Otherwise IP, SSH port, Linux username, sudo/Docker permission and the local private-key path. Do not send passwords, private-key contents or tokens in chat. |
| Existing services | Whether the host already runs anything, especially listeners on 80/443, Nginx/Caddy, and any database. Identify the deployment directory and firewall/security-group control. |
| Domain | One exact hostname, such as `adc.example.com`; DNS provider; ability to change A/AAAA records; current records; CDN/proxy mode, if any. Domain registration alone is insufficient. |
| Certificate | Existing certificate location/renewal mechanism, or contact email and choice of HTTP-01/DNS-01 for a new certificate. DNS API secrets remain in local private files. |
| Audience/data | Public read-only demonstration or a limited group allowed to write; approximate simultaneous users; fresh synthetic data or an explicitly requested trusted copy of the Mac synthetic data. |
| Recovery/operations | Private off-host backup destination, retention and desired recovery window; operator/alert channel. No alerts are sent without an explicit instruction. |

Ubuntu 24.04 LTS is a supported Docker Engine target. A provisional small-demo
budget is 2 vCPU, 4 GB RAM and 40 GB SSD; this is a planning assumption, not a
capacity test. Actual concurrency, storage and latency are G4 target checks.
If no server/domain exists, provide that fact plus budget and intended audience.

## What the preparation tools do

- `scripts/g4_prepare.py` renders a **new** private `.g4` folder. It generates
  separate admin, migration-owner and runtime passwords, pins every image and
  binds to loopback by default. It performs no SSH, DNS, Docker or database work.
- Runtime credentials are in `private/runtime.env`; Web/worker receive no owner
  password. `private/maintenance.env` is only for explicit management commands;
  maintenance settings refuse a Web-server process. DB bootstrap credentials
  stay in `private/database.env`.
- PostgreSQL initialization runs only on an empty data directory. The owner has
  no superuser/create-role rights; runtime owns no database/tables and cannot
  create schema objects. Default table/sequence privileges support normal app
  DML. An already initialized database is never silently reinitialized.
- Web checks runtime privileges and migration state before Gunicorn starts.
  Static collection is separate. The notification writer is an explicit profile
  and refuses read-only mode. Access logs rotate and omit request URLs, cookies and
  form content; seed credentials are excluded from container logging.
- `check_g4_deployment` runs Django deployment checks. Only W005/W021 are
  reviewed for the existing one-hour HSTS, no subdomain inheritance and no
  preload policy. All other warnings/errors block; checks are not silenced.
- `scripts/g4_https_probe.py` makes read-only GETs with certificate/hostname
  verification. It checks redirects, static files, secure CSRF cookie and
  forwarded-header/Host behavior. It never logs in or approves G4.

`.g4` is excluded from Git and Docker build context. Never paste/render private
Compose environment values into a public report. File hashes detect differences,
not publisher authenticity or a trustworthy server.

## Target execution sequence, after the details are confirmed

1. Inspect the actual Linux host, its explicit local Unix-socket Docker context,
   firewall, available ports, architecture and disk. Keep SSH available. Docker
   port publication can bypass UFW rules, so inspect the cloud firewall and
   Docker forwarding rules as well.
2. Check out a clean, CI-passing source commit and build on the target architecture
   using `Dockerfile.production`. Label the image with that source revision,
   inspect its image ID/digest and actual installed dependencies. Pull/review
   PostgreSQL 17 and Nginx, then record their digests. A digest alone is not a
   vulnerability or provenance attestation.
3. Run the offline generator on the target. Example placeholders below must be
   replaced with the actual reviewed values:

   ```sh
   python3 scripts/g4_prepare.py prepare \
     --host YOUR_HOSTNAME --source-commit FULL_COMMIT_SHA \
     --app-image sha256:APP_IMAGE_ID \
     --db-image postgres:17@sha256:DB_DIGEST \
     --nginx-image nginx:stable-alpine@sha256:NGINX_DIGEST
   python3 scripts/g4_prepare.py inspect
   ```

   The default is loopback. Public binding is an explicit later choice, after
   firewall review, using `--bind-ip` in a new prepared folder. The first
   bundle expects HTTP/HTTPS ports 80/443 on a dedicated host.
4. Obtain the actual trusted certificate. Place the complete chain and matching
   private key at `.g4/tls/fullchain.pem` and `.g4/tls/privkey.pem`; keep the key
   private. Plan renewal and tested Nginx reload. A self-signed local rehearsal
   does not satisfy this step. Initial HTTP-01 issuance may use a temporary
   standalone challenge listener before the TLS gateway starts; DNS-01 is an
   alternative. Avoid a conflict with existing port-80 services.
5. Pin the new project from `.g4/plan.json`. Every Compose command must specify
   this project, `.g4/compose.env` and `.g4/compose.yaml`; never combine with the
   Mac RC Compose file. Render all profiles to a mode-600 private JSON and run
   `g4_prepare.py inspect --rendered-compose PRIVATE_FILE` before starting.
6. Start only `db`; run the maintenance `schema` service; inspect runtime role
   privileges. For a fresh demo, run `bootstrap` once with stdout redirected to
   a mode-600 private credential file. It refuses existing domain data. For a
   trusted import, restore into a separate empty initialized project using the
   owner, one transaction and `--no-owner --no-privileges`; do not seed it.
7. Run `nginx -t`, start Web/gateway and inspect health. Verify actual A/AAAA
   resolution, public certificate trust and renewal, HTTP redirect, static files,
   cookies, CSRF, unknown Host and proxy headers from outside the server.
8. Exercise real browser roles on that hostname. Read-only public checks come
   first. Enabling business writes and the worker is a distinct choice based on
   the intended audience; repeat permission, notification and restart checks.

## Recovery and completion criteria

Before exposing the target, create a PostgreSQL custom-format dump with the
owner into private storage, with no owner/ACL metadata. A command such as
`pg_dump -Fc --no-owner --no-privileges` must be run against the explicitly
identified G4 database. Do not put passwords on command arguments or upload a
dump to GitHub. A backup left on the same server is insufficient for server loss.

Rehearse restore into a **different empty project/database**, in one transaction,
with exit-on-error. Compare stable account/grant, patient, visit, invoice-version,
amount and notification facts; verify login and role behavior. Preserve the
original database. Do not restore over a running target, delete its volume, or
roll back the binary/schema while ignoring new writes. Import does not recover
the reset Windows database; G2 remains a separate unmet requirement.

G4 needs evidence for the target host/images, DNS/trusted TLS, external HTTPS and
browser use, private ports, credentials/roles, backup/restore, service/worker
restart, monitoring/renewal and bounded capacity. Until these target checks run,
`G4_public_deployment.status` remains `NOT_RUN`; preparation is tracked separately.

## Primary references checked 2026-10-13

- [Django deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/)
- [Docker Engine on Ubuntu](https://docs.docker.com/engine/install/ubuntu/)
- [Docker networking/firewalls](https://docs.docker.com/engine/network/packet-filtering-firewalls/)
- [Let's Encrypt challenge types](https://letsencrypt.org/docs/challenge-types/)

Local preparation evidence: [rehearsal](../../docs/evidence_g4/preparation.json) and
[full isolated regression](../../docs/evidence_g4/postgresql-gate.json). The original
preparation passed 822 source checks and 704 Django tests. The selected Mac mode
passed 828 source checks and 705 Django tests in the PostgreSQL environment; see
[Mac regression](../../docs/evidence_g4/mac-postgresql-gate.json).
No model or application migration changed; verification cleanup succeeded.
