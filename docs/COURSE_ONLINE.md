# Course online release（课程上线版）

Independent hosting → explicit business operations → encrypted recovery copies
→ evidence from the actual target. This guide describes the writable course
deployment. Current cloud acceptance is **NOT_RUN**: the server is not purchased.
Local rehearsals and the existing Mac demonstration are separate evidence.

## Selected hosting and inputs

- Tencent Cloud Lighthouse, Hong Kong, Ubuntu 24.04 amd64, 2 cores / 2 GB /
  40 GB, one month. Published reference: ¥38/month; verify actual checkout price,
  region and renewal settings before purchase. Hong Kong avoids the mainland
  server ICP-filing dependency.
- Free owned DuckDNS hostname: explicitly point its A record at the server IPv4.
  Clear unreviewed AAAA records. Verify DNS, trusted HTTPS and actual mainland
  China access without a proxy before sharing the course link.
- Required private inputs: IPv4, SSH username, local SSH-key path, a provider-
  verified SHA256 host-key fingerprint, and the registered hostname.
- Cloud firewall: public 80/443; SSH 22 restricted to the operator's network.
  PostgreSQL and Gunicorn have no published ports. Docker port publication can
  bypass UFW; inspect the cloud firewall and actual listening ports.

The server remains available while Mac is asleep. Off-host recovery is limited
to the **last verified backup downloaded to Mac**, not a guaranteed daily copy.
No public registration, external AI, real patient records or external payments
are part of this course deployment.

## Build and prepare（构建与准备）

Use a clean reviewed Git commit. Keep all artifacts in an ignored private folder;
never copy the Mac .rc or read-only .g4 into this new instance.

```sh
umask 077
mkdir -p .course-private
python3 scripts/g4_course.py --context desktop-linux \
  --docker /Applications/Docker.app/Contents/Resources/bin/docker \
  build --artifacts .course-private/build-amd64
```

The build exports source.tar, application.tar and build.json. It builds
linux/amd64 from git archive and records the source revision, immutable image ID
and archive checksums. Read these IDs privately; pin PostgreSQL 17 and
nginx:stable-alpine by digest, selecting amd64 images on the cloud host.

```sh
mkdir -p .course-private/cloud
python3 scripts/g4_prepare.py prepare \
  --output .course-private/cloud/.g4 --mode direct_tls \
  --access-mode course-writable --bind-ip 0.0.0.0 \
  --host YOUR_OWNED_HOSTNAME --source-commit FULL_TESTED_COMMIT \
  --app-image IMMUTABLE_APP_ID \
  --db-image postgres:17@sha256:VERIFIED_DIGEST \
  --nginx-image nginx:stable-alpine@sha256:VERIFIED_DIGEST
python3 scripts/g4_prepare.py inspect --output .course-private/cloud/.g4
```

Preparation defaults to read-only; enabling writes requires the explicit access
mode and a new direct-TLS bundle. The course worker starts without a separate
profile, under UID 10001, using runtime credentials. Schema/seed use separate
owner credentials. The initializer refuses existing business data.

Install the reviewed age/age-keygen tools on Mac, then create its recovery key:

```sh
python3 scripts/g4_remote.py generate-backup-key \
  --destination .course-private/backup-key
```

identity.txt stays on Mac; only the public recipient.txt goes to the server.
Retain the matching application image/source archives for recovery.

## First cloud deployment（首次云部署）

Store an owner-only ssh.json with this shape; all paths are absolute:

```json
{
  "host": "SERVER_PUBLIC_IPV4",
  "user": "ubuntu",
  "identity_file": "/absolute/private/ssh-key",
  "known_hosts_file": "/absolute/private/course-known-hosts",
  "fingerprint": "SHA256:PROVIDER_VERIFIED_HOST_KEY_FINGERPRINT",
  "sudo": true
}
```

The known-hosts file must contain exactly one key for that IPv4 on port 22.
Compare it with the fingerprint obtained through the server provider's trusted
console before trusting it. Strict SSH verification is never disabled.

```sh
python3 scripts/g4_remote.py --ssh-config .course-private/ssh.json \
  --output .course-private/cloud/.g4 publish \
  --artifacts .course-private/build-amd64 \
  --recipient-file .course-private/backup-key/recipient.txt
```

Publish creates a new project-specific release folder under /srv/adc-course,
checks transfer hashes, provisions dependencies only on a dedicated empty Ubuntu
24.04 amd64 host, loads/pulls the pinned images, issues TLS, initializes the
empty database, seeds synthetic accounts once, and starts web/worker/gateway.
It installs daily encrypted server backups and twice-daily certificate checks.
An existing release folder is preserved and publication stops; diagnose an
interrupted run through pinned SSH rather than uploading over its private state.
Successful seeding is recorded before runtime startup; retrying deploy after a
runtime failure starts services without reseeding. Earlier initialization
failures require diagnosis.

Initial HTTP-01 uses a temporary challenge-only listener on port 80. Certbot
uses webroot for issuance and renewal; certificates are copied privately and
gateway reload follows nginx -t. Rehearsal certificates cannot contact the CA.

## Account handover and demonstration（账号交付）

Read .g4/private/demo-credentials.txt privately on the server; never attach it
to GitHub, screenshots or the report. Publish also downloads that initial
credential record privately to the Mac bundle for acceptance setup.
COURSE_ACCESS.md contains the fixed staff
and patient login links. Use technical account governance to create ordinary
assigned accounts, grant one role/clinic at a time, bind synthetic patients and
reset/disable accounts. Change passwords before handing accounts to users.
Do not grant SYSADMIN through that UI or use shared privileged accounts.

Demonstrate the complete [A/B routes](DEMO_ROUTES_RC1.md):

- A: register resources → future availability → patient booking/arrival →
  treatment/invoice → independent correction → quarterly costs/report/CSV.
  Independently verify 199.98 revenue, 130 costs, 69.98 profit and 7.00 fund;
  correction gives 99.99 revenue, -30.01 profit and preserved prior invoice version.
- B: pause intake → preserve existing promises → open/claim coordination →
  explicitly resolve visits → submit/independently review → maintain availability.
  Stop/restart the worker and verify delivery/deduplication. Reading is not
  claiming; review does not modify availability.

After synthetic workload tests, disable their ten ordinary load accounts using
governance. Preserve their records/audit history. Do not delete test rows or
reset the database after handing accounts to the class.

## Backup, synchronization and independent restore（备份恢复）

Server snapshots contain a PostgreSQL 17 custom-format dump, reviewed deployment
configuration, source/image identifiers and internal checksums, encrypted with
age X25519. Retain the latest completed copy for each UTC day: seven daily copies
on the server and 30 on Mac. Manual runs cannot crowd older daily recovery points out.
Corrupt files block synchronization/pruning. Partial downloads never replace a
verified copy. Plain temporary recovery material is removed after operations.

```sh
python3 scripts/g4_remote.py --ssh-config .course-private/ssh.json \
  --output .course-private/cloud/.g4 sync \
  --destination .course-private/mac-backups \
  --identity-file .course-private/backup-key/identity.txt
python3 scripts/g4_remote.py --ssh-config .course-private/ssh.json \
  --output .course-private/cloud/.g4 install-mac-job \
  --destination .course-private/mac-backups \
  --identity-file .course-private/backup-key/identity.txt \
  --age /absolute/reviewed/age
```

The Mac LaunchAgent runs at login and hourly while awake. Inspect last-sync.json;
manually synchronize before/after assessment and before the rental expires.
A server-side backup alone is not off-host recovery. On server loss, keep the
Mac backup/key/artifacts; initialize an independent empty replacement project.
The matched image/schema must be available. Restore never targets an existing
table set and never seeds after import.

For a replacement cloud host, prepare a NEW bundle using the original backup's
source/image; use publish with --restore-backup, --identity-file and the explicit
--trusted-synthetic-copy flag. Decryption happens on Mac and only the verified
dump/manifest travel through pinned SSH; the key remains on Mac.
Check business/credential digests and normal login after restore. Recovery target:
30 minutes once the replacement environment is ready. Restoring data is not
proof of original Windows/v0.7 recovery.

For an isolated Mac rehearsal, prepare a NEW direct-TLS course bundle on separate
loopback ports with --architecture arm64 (or amd64 for emulation); use the matching
image architecture in g4_course.py --rehearsal --architecture arm64 --ca-file
LOCAL_CA --output NEW_BUNDLE --context desktop-linux restore --backup-file
PRIVATE_BACKUP --identity-file PRIVATE_KEY --trusted-synthetic-copy.
Both projects stay intact. Never use down -v or overwrite a current database.

## Target acceptance（目标环境验收）

Run the full PostgreSQL regression gate, all seven role/browser and A/B scenarios,
account/password/grant refusals, worker restart and duplicate-submission checks
against the cloud address. Record application commit separately from later
evidence/documentation commits. Local or same-Mac results cannot pass cloud gates.

Capacity tooling uses ten distinct accounts created/granted through the normal
technical UI, then CSRF-protected login and signed clinic selection:

```sh
python3 scripts/g4_course_load.py --output .course-private/cloud/.g4 \
  --scope public prepare-synthetic-actors
python3 scripts/g4_course_load.py --output .course-private/cloud/.g4 \
  --scope public run --duration 1800 --rps 5
```

The measured workload is 80% authenticated GET / 20% valid synthetic
patient-creation POST, without retries. Require all 9,000 requests successful,
1,800 distinct created patients matching the run prefix, no queue drops or
unintended records, p95 <= 5 seconds, and no sampled OOM/restart/DB wait.
This write workload alone does not test booking conflicts or financial integrity;
those require the separate A/B and refusal scenarios.

scripts/g4_course_browser.cjs runs real Chrome smoke checks for seven roles,
normal signed clinic selection, a patient write, refusal and narrow large text.
Run it from a Mac with Playwright and Chrome, passing BUNDLE public. The origin
mode is restricted to separate loopback ports and pins the locally generated
certificate public key; it never relaxes public certificate validation.
These smoke checks supplement the complete A/B scenarios.

Execute scripts/g4_course_facts.py inside the explicitly matched runtime with
--project PROJECT and --load-prefix RECORDED_PREFIX. It emits hashed business
facts and created/distinct-name counts, never raw credentials/contact records.
Require both counts to equal successful_writes and planned_writes. Keep private
run/session/account files private; publish only sanitized metrics/evidence.

Finally verify mainland access without a proxy, external HTTPS/CSRF/Host/header
handling, Mac-off independence, whole-server reboot with persistent data,
certificate renewal dry-run/reload, an independently restored Mac download, and
24 hours of target observation. Update course readiness only after these pass.
The global release flag remains separate from the unresolved historical G2.

Use scripts/g4_course_observe.py on the server with --output BUNDLE --context
default --duration 86400 --interval 60. It samples the explicitly owned four
services and runtime-role database facts without changing them. Its origin-only
result must be paired with external public HTTPS observations. Any sampling
failure is retained; observations alone never grant course readiness.

Primary references:
[Tencent package](https://cloud.tencent.com/announce/detail/2131),
[Tencent filing rules](https://cloud.tencent.com/document/product/243/18908),
[DuckDNS](https://www.duckdns.org/spec.jsp),
[Docker Ubuntu installation](https://docs.docker.com/engine/install/ubuntu/),
[Certbot](https://eff-certbot.readthedocs.io/en/stable/using.html),
[PostgreSQL dump](https://www.postgresql.org/docs/17/app-pgdump.html),
[PostgreSQL restore](https://www.postgresql.org/docs/17/app-pgrestore.html),
[age](https://github.com/FiloSottile/age).
