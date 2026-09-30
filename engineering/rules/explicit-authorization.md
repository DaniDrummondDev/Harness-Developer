---
version: 1
id: explicit-authorization
type: rule
name: Explicit authorization
description: Every protected operation performs an explicit, testable authorization check; default is deny.
tags: [security, authorization]
applies_to:
  stacks: [laravel, django, fastapi, flask, rails, express, spring]
  capabilities: [api, web]
---
# Rule: Explicit authorization

**Instruction.** Every operation on a protected resource calls an explicit authorization
check (policy, gate, permission, guard) for the acting principal *and* the specific resource.
When no rule grants access, access is denied.

**Verifiable by**
- each protected route/handler/use case has an authorization call or declarative guard;
- tests cover allowed, forbidden (403) and unauthenticated (401) cases, including access
  to another tenant's or user's resource (IDOR);
- no reliance on hidden URLs, client-side checks or obscured ids.

**Why.** Missing object-level authorization is one of the most common and damaging API flaws.
