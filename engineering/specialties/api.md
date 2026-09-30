---
version: 1
id: api
type: specialty
name: APIs
description: HTTP API design, contracts, versioning, error models and consumer compatibility.
tags: [api, http, web]
applies_to:
  capabilities: [api]
skills: [api, security]
rules: [thin-controllers, explicit-authorization, validation-at-boundaries]
---
# Specialty: APIs

**Profile.** Designing and evolving HTTP APIs: resource modelling, status codes, error
shapes, pagination, idempotency, versioning, OpenAPI contracts and compatibility with
existing consumers.

**Checklist**
- Contract documented and tested; changes additive unless a breaking change was approved.
- Consistent error model; validation errors per field.
- Every endpoint authorized; collections paginated and bounded.
