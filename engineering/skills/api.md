---
version: 1
id: api
type: skill
name: HTTP API design
description: How to design and evolve HTTP APIs - resources, status codes, validation errors, pagination, versioning and idempotency.
tags: [api, http, web]
applies_to:
  capabilities: [api]
---
# Skill: HTTP API design

**Use when** adding or changing HTTP endpoints.

**How to do it well**
1. Model resources with nouns and standard methods; keep URLs stable.
2. Status codes: 200/201/204 success, 400/422 validation, 401 unauthenticated, 403
   forbidden, 404 not found, 409 conflict, 429 throttled, 5xx server faults only.
3. One consistent error shape (e.g. RFC 9457 problem details) with field-level validation
   messages; never leak stack traces.
4. Paginate every collection (cursor preferred for large/mutable sets); bound page size.
5. Make retries safe: idempotency keys for non-idempotent creates, ETags for concurrency.
6. Evolve additively; breaking changes follow the `breaking-changes` policy (new version or
   deprecation window).
7. Document the contract (OpenAPI) in the same change as the code and test it.

**Verify**: contract/feature tests per endpoint including 401/403/422 and pagination edges.

**Pitfalls**: exposing internal ids or models directly; unbounded queries; chatty endpoints
causing N+1 round trips; inconsistent date/number formats.
