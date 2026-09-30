---
version: 1
id: thin-controllers
type: rule
name: Thin controllers
description: Controllers/handlers only translate transport to application calls; business logic lives elsewhere.
tags: [architecture, web]
applies_to:
  stacks: [laravel, django, fastapi, flask, rails, express, spring]
  capabilities: [api, web]
---
# Rule: Thin controllers

**Instruction.** A controller (route handler, view, endpoint) only: authenticates/authorizes,
validates and maps the request, calls one application service/use case/action, and maps the
result or error to a response.

**Verifiable by**
- no database queries, external calls or business branching inside controller methods;
- controller methods stay short (rule of thumb: under ~20 lines);
- business logic is reachable and testable without the HTTP layer.

**Why.** Logic in controllers is duplicated across entry points (CLI, jobs, queues) and is
hard to test.
