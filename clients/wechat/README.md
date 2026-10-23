# ADC native patient client / 患者微信小程序

Published service → scope and fee terms → exact service and time → explicit
confirmation → own appointment and waitlist progress.

This native WXML/WXSS/JavaScript client shares the website's patient authorization,
resource inventory and booking commands. The C0.2 source adds service discovery,
service detail, selected-service continuation and a signed optional visit request.
It includes appointment/history, same-service rescheduling, cancellation, waitlist
registration/withdrawal and explicit offer acceptance/decline. It does not create
clinical assessments, payments or a WeChat identity/phone binding.

## Matched backend and content

Use the client with the matching C0.2 backend after its protected migration and
runtime gates. The current port-18000 installation has not been updated by this
source work. The earlier server's raw service catalogue does not implement the
new published-offerings contract; pairing versions is not an accepted deployment.

Before patients can book, a current-clinic manager must configure the actual
service/resources, complete its patient description and explicitly publish it
through **患者服务内容**. Templates remain drafts. No service, price or clinical
capability is invented by the client. Active but unpublished services cannot
start new native bookings or waitlist requests. Child services require front-desk
verification. Retained own appointments/offers use their existing domain rules.

## Local developer-tool import

1. Verify the identified matched backend and `/health/` in the isolated/protected
   workflow; do not point verification at an existing real-data database.
2. Import this directory in WeChat developer tools. The source uses `touristappid`
   and local loopback configuration for simulator development only.
3. Local domain-check relaxation is for the simulator, not an experience release.
   `127.0.0.1` on a phone refers to that phone, not the Mac.
4. Use a separately assigned synthetic patient account. No password is included
   in the repository or package. Existing local private credentials stay local;
   they must not become customer credentials.
5. Check **了解服务并预约** → offering details/fees/preparation → booking/request →
   confirmation → own appointment. Also check child services, stale descriptions,
   failed networking, fee changes, waitlist and existing-appointment rescheduling.

Prepare a separate import directory without changing source configuration:

```sh
python scripts/prepare_wechat.py --output /tmp/adc-mini-local --api-base http://127.0.0.1:18000
```

The command prepares files only. It does not update that backend or establish
simulator/device acceptance.

## Experience release inputs

A registered AppID, authorized developer, accepted HTTPS backend/request domain,
platform configuration and experience members are required. AppSecret must never
be placed in the client. Account activation/recovery and real-data initialization
remain separate commercial requirements; assigned-account login is retained.

```sh
python scripts/prepare_wechat.py --mode experience --appid wx0123456789abcdef --api-base https://YOUR-APPROVED-HOST --output /tmp/adc-mini-experience
```

Replace the example AppID/domain with the actual permitted values. The generator
keeps domain checks on for this mode, but does not upload, configure the platform
or verify a device. Current platform setup must be checked when that release is
actually undertaken.

## Actual verification scope

`node scripts/verify_wechat.cjs` runs source/event-binding/timezone/transport
checks and `verify_native_services.cjs`: 23 actual Page-handler scenarios with a
mocked API boundary. This does not execute Django, PostgreSQL or the WeChat bridge.
The 25 C0.2 API/transaction cases are authored for the real PostgreSQL gate and
have not run in this environment. Full current results and limitations are in
[the C0.2 release record](../../docs/C02_NATIVE_SERVICE_RELEASE.md).

There are now 11 pages. Earlier nine-page official offline compiler/HTTP evidence
is historical and does not cover this version. Current official WXML/WXSS
compilation, IDE/device execution, matching backend installation and experience
acceptance remain unexecuted. If current official compiler binaries are available,
set `ADC_WECHAT_COMPILER_DIR` for the verifier; syntax success alone is still not
runtime acceptance.
