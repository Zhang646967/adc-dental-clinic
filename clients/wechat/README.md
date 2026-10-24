# ADC native patient client / 患者微信小程序

Published service → scope and fee terms → exact service and time → explicit
confirmation → own appointment and waitlist progress.

This native WXML/WXSS/JavaScript client shares the website's patient authorization,
resource inventory and booking commands. The service journey includes service discovery,
service detail, selected-service continuation and a signed optional visit request.
It includes appointment/history, same-service rescheduling, cancellation, waitlist
registration/withdrawal and explicit offer acceptance/decline. It does not create
clinical assessments, payments or a WeChat identity/phone binding.

## Matched backend and content

Use the client with the matching C1.1 backend. See [release evidence](../../docs/evidence_c11/README.md) for the exact application and installed version. The client requires the subject-selection API and cannot be paired with the older C0.2 backend.

Before patients can book, a current-clinic manager must configure the actual
service/resources, complete its patient description and explicitly publish it
through **患者服务内容**. Templates remain drafts. No service, price or clinical
capability is invented by the client. Active but unpublished services cannot
start new native bookings or waitlist requests. Child services require a verified appointment grant from the front desk. Retained own appointments/offers use their existing domain rules.

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

`node scripts/verify_wechat.cjs` runs 114 source/transport checks and 26 actual Page-handler scenarios with mocked API responses. Separate five-clinic runs use real HTTP and PostgreSQL, plus Chrome website checks. All 12 WXML pages and the WXSS bundle passed the official offline compiler. See [C1.1 evidence](../../docs/evidence_c11/README.md).

These scopes do not establish WeChat developer-tool runtime, phone execution or experience release. AppID and independent cloud setup are still pending. Set `ADC_WECHAT_COMPILER_DIR` to available official compiler binaries for the offline syntax gate.

## C1.1 patient subjects

The native client now has 12 pages, including an explicit patient selector. Assigned accounts can use their own PatientAccess or a clinic-verified, time-limited appointment grant. Subject switching clears pending reviews and stale responses; booking, rescheduling and waitlist share the website commands. Delegation does not grant chart, invoice or clinical-consent access. Official offline compilation and Page/HTTP tests remain separate from WeChat runtime/device/experience acceptance.

C2.1 adds the own-patient health-history page (`pages/history/index`). It shares the website command, independent self-report versions, explicit confirmation and uncertain-response retry. Appointment delegates cannot report clinical history. There are14 native pages; official offline syntax, backend/Page-over-HTTP and actual WeChat runtime remain distinct. See [C2.1 evidence](../../docs/evidence_c21/README.md).
