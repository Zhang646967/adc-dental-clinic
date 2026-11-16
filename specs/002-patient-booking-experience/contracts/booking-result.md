# Read an unconfirmed appointment result

The proposal used by confirmation identifies the exact attempt. Send it only in the request body. Recovery uses the current authenticated patient workspace and CSRF headers.

| Client | Request |
| --- | --- |
| Web | `POST /portal/booking-result/` with `kind`, `proposal_token`, CSRF and the web workspace field |
| WeChat | `POST /api/mini/v1/booking/result/` with `kind`, `proposal_token` and the existing mini-program session and workspace headers |

`kind` is `booking` for a new appointment or report follow-up and `reschedule` for a replacement. In the web recovery request for a new appointment, copy the original confirmation form's `token` value to `proposal_token`. Use the reschedule proposal unchanged. WeChat uses its own wrapped booking proposal unchanged.

- `SAVED` includes `visit_id` for the exact receipt, including the new appointment for a reschedule. Web also returns `url`; WeChat uses the regular visit detail.
- `UNCONFIRMED` has no `visit_id`. There may be an in-flight request. Retry the lookup or check the original visit/appointment list.
- Invalid or expired proposals and stale contexts use the existing rejection path. Recovery is available for up to one hour from preview while the same workspace and authorization remain valid. This does not extend the confirmation deadline.

Use recovery only after attempting confirmation and losing a definitive outcome. Never reissue a confirmation as a query. For cancellation and waitlist outcomes use the existing record routes, with the same visibility rule for the recovery action.
