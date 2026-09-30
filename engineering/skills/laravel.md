---
version: 1
id: laravel
type: skill
name: Laravel
description: How to implement features in Laravel - routing, form requests, policies, services/actions, Eloquent, queues and tests.
tags: [php, laravel, web, backend]
applies_to:
  stacks: [laravel]
---
# Skill: Laravel

**Use when** changing a Laravel application.

**How to do it well**
1. Route -> controller (thin) -> Form Request (validation + `authorize()`) -> action/service
   -> Eloquent/repository. Controllers return resources/responses only.
2. Authorize with Policies/Gates (`$this->authorize`, `can` middleware) on every protected action.
3. Validate with Form Requests; never trust `$request->all()`; guard mass assignment with
   `$fillable`.
4. Eloquent: avoid N+1 (`with()`), use transactions for multi-write operations, scope
   tenant data explicitly.
5. Migrations are forward-only and reversible when feasible; never edit an applied migration.
6. Long or external work goes to queued jobs with retries and idempotency.
7. Configuration via `config/*.php` reading `env()` only there; never call `env()` elsewhere.
8. Tests: Feature tests for HTTP behaviour (`RefreshDatabase`), Unit tests for actions;
   cover 401/403/422 paths.

**Verify**: `php artisan test` (or Pest), static analysis (PHPStan/Larastan), Pint.

**Pitfalls**: logic in controllers or models' boot hooks; `env()` outside config (breaks with
config cache); unguarded models; missing indexes on foreign keys.
