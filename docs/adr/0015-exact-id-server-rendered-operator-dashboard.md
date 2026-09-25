# ADR-0015: Render the operator dashboard from one exact timeline

## Status

Accepted.

## Date

2026-09-25.

## Context

Phases 5a through 5d established a bounded, metadata-only operator timeline with append-only local
history, control context and immutable provider provenance. Operators can inspect it through JSON,
but the roadmap still calls for a visual dashboard. Global activity discovery remains unsafe before
organization identity, tenant isolation and explicit operator authorization exist.

A browser-facing surface also creates an HTML injection and metadata-caching boundary. Provider
sources and other registry metadata are curated but still external input and must not be trusted as
markup.

## Decision

Add a server-rendered dashboard at `/operator` that accepts one exact `enforcement_id` and delegates
all correlation and integrity decisions to the existing `GetOperatorTimeline` use case. The page:

- does not list, search, paginate or discover records;
- renders only the metadata already allowlisted by the timeline;
- escapes every dynamic value and contains no client-side JavaScript;
- loads one same-origin stylesheet;
- applies `no-store`, a restrictive Content Security Policy, frame blocking, referrer suppression
  and browser capability restrictions;
- maps not-found and integrity failures to generic HTML states without exposing internal details;
- remains read-only and offers no approval, retry or reconciliation action.

Keep the JSON timeline contract unchanged. The dashboard is a presentation adapter over that
application contract, not a second source of timeline semantics.

## Alternatives considered

- Build a single-page application: rejected because it adds a JavaScript/toolchain and a larger
  content-security surface without product value for the exact-ID slice.
- Add global recent-activity discovery: rejected until identity, tenant isolation and explicit
  operator authorization exist.
- Render directly from SQLite: rejected because it would duplicate application integrity and
  attention logic in the transport layer.
- Embed inline styles: rejected so the page can enforce `style-src 'self'` without
  `unsafe-inline`.

## Consequences

Operators can inspect decision, enforcement, tool-action, lifecycle, control and provider context
in a responsive browser view. The page intentionally requires an already-known enforcement ID and
does not make the operator surface a discovery API.

## Security and privacy impact

The dashboard cannot recover prompts, values, tool arguments/results, assertions, credentials or
approval actor identity because those fields are absent from the timeline contract. All dynamic
metadata is HTML-escaped. Responses are not browser-cacheable, cannot be framed and do not send a
referrer. Existing deployment access controls must still protect both `/operator` and `/v1/operator`.

## Operational impact

No dependency, persistence migration, background process or outbound network call is added. The
dashboard performs the same bounded local reads as the JSON timeline and serves a small local CSS
response. Existing exact-ID error and availability semantics remain fail closed.

## Follow-up

- Add organization identity, tenant isolation and operator authorization before global discovery.
- Add accessibility and browser regression checks if the visual surface grows.
- Define separately authorized reconciliation workflows.
- Consider a richer frontend only after operator workflows require it.
