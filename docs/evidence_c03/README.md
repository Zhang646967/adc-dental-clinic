# C0.3 local patient-channel acceptance

Source candidate → executed migration/regression → five-clinic journeys → independent financial/resource facts → protected delivery.

Record date: 2026-10-23. [Scope and fix](../C03_RELEASE_ACCEPTANCE.md).

| Evidence | Scope |
|---|---|
| [regression.json](regression.json) | 1,095 rules, 1,474 PostgreSQL/HTTP/concurrency tests; first failure and correction retained |
| [browser.json](browser.json) | 187 actual Chrome/native-handler HTTP checks in five synthetic clinics; no WeChat runtime claim |
| [business_facts.json](business_facts.json) | 64 independent ORM checks, current invoice/posted cash totals, no new clinical or money effects |
| [native.json](native.json) | 107 source/transport checks, 23 mocked Page cases, official eleven-page offline compilation |
| [database metadata](../database/schema_snapshot.json) | Observed 70-table, 171-FK, 42-trigger structure; no business rows or secret defaults |
| [report validation](../report-source/validation.json) | Current formal Word/PDF content and visual review |

[Exact application CI](application_ci.json), [exact-image replay](exact_image.json), [original-database copy upgrade](copy_upgrade.json), [encrypted empty-database restore](encrypted_restore.json), [protected Mac update](mac_update.json), [263 target browser checks](mac_browser.json), [13 native read/preview checks](mac_mini.json) and [actual Mac schema](mac_schema.json) have now executed successfully. The source implementation's earlier NOT_RUN records remain historical; this folder records subsequent execution rather than rewriting them.

Historical capacity, prior monitoring gaps, WeChat platform and cloud results are not relabeled as current acceptance. This is not a commercial clinical replacement qualification.

Post-update evidence: [encrypted local backup](mac_after_backup.json), [retained collector failure and manual recovery](host_resolution.json), [brief observation](mac_observation.json). The collector failure detail was not retained; three independent samples and fresh healthy collector conditions permitted recorded incident closure. Its UNKNOWN interval and collection-gap event remain historical. This is not a root-cause fix or continuous-reliability acceptance.

[Delivery summary](delivery.json) binds the application commit, image, original-data comparison, explicit synthetic catalogue additions and current report. Ten post-recovery samples over 95.85 seconds were healthy; this is a brief observation. The final evidence commit has no application/native/schema behavior changes.
