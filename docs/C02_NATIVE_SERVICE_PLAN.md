# C0.2 — Native patient service journey

Status: planned before implementation, 2026-10-22. Builds on source candidate
`05730d8`; the installed port-18000 baseline is unchanged.

## Problem and outcome

The website has explicit clinic-managed service publication, but the native
patient channel still lists raw active services, omits their content/fees and
starts with clinic selection. A patient must be able to understand a published
offering, choose it, review the fee basis and preparation, and carry that choice
and an optional visit request into confirmation and their own visit detail.

## Implementation sequence

1. Reuse the website's published, complete, operational service projection in
   the native catalogue/detail API. Preserve NULL versus known-zero fees and
   expose only public clinician identifiers/names. No automatic publishing.
2. Add native discovery/detail pages and an explicit selected-service handoff.
   Child offerings direct to front-desk verification. Remove course marketing
   from customer copy while retaining an accurate compact environment label.
3. Require a published self-bookable offering for new native candidates,
   booking previews and waitlist registration. Bind the optional 500-character
   patient request into the signed preview; confirmation ignores edited raw
   fields. Preserve shared commands, locking, receipts and authorization.
4. Preserve own historical appointments, offers and same-service rescheduling
   even when a public description is withdrawn. Test that compatibility along
   with stale selection, safe errors, publication gates and request replay.

## Acceptance criteria

- Draft, incomplete, inactive or resource-disabled offerings are absent from
  native discovery and cannot start a new booking/waitlist registration.
- All published categories remain discoverable; CHILDREN cannot self-book.
- Service detail includes scope, suitability, limitations, preparation, exact
  fee mode/nullable amount/note, clinic contact and current public dentists.
- Service selection survives discovery → detail → booking; no silent fallback
  to a different service and no invented generic-service option.
- Signed preview and own visit show the submitted patient request. Replays
  return the saved visit's current state without overwriting the request.
- Rescheduling uses an own-visit projection; unpublished historical service
  information does not leak into the general catalogue.
- Existing CSRF, workspace, role and ownership checks remain authoritative.
- No new schema/migration, clinical eligibility claim or fee collection.

## Verification and release boundary

Execute local pure-Python rules, native transport/page-handler tests, syntax and
integrity checks. Author real Django/PostgreSQL HTTP regressions for the target
gate; do not report them as executed without that environment. Native simulator,
official compiler/device, protected migration, browser and deployment evidence
remain distinct. A source commit/patch is not a running release or commercial
clinical qualification. Preserve all 40 current migrations byte-for-byte.

Next priority after this slice: run the protected source/migration/HTTP gate and
verify the installed patient journey; then scope intake and clinical-record
work under the commercial master plan rather than adding unverified clinical
workflow or prescribing authority here.

## Implementation outcome

The bounded source implementation is complete. See
[C02_NATIVE_SERVICE_RELEASE.md](C02_NATIVE_SERVICE_RELEASE.md) for the final
behavior, executed checks and still-pending runtime acceptance. SERVICE-02 is
IMPLEMENTED, not VERIFIED or RELEASED; the installed entry is unchanged.
