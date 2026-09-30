---
version: 1
id: php-laravel
type: specialty
name: PHP / Laravel
description: Laravel web applications and APIs - HTTP layer, authorization, Eloquent, queues and testing.
tags: [php, laravel, web, backend]
applies_to:
  stacks: [laravel]
skills: [laravel, database, testing]
rules: [thin-controllers, explicit-authorization, validation-at-boundaries]
---
# Specialty: PHP / Laravel

**Profile.** Laravel applications: routing, Form Requests, Policies/Gates, actions/services,
Eloquent, migrations, queues, Feature/Unit tests (PHPUnit or Pest), Larastan and Pint.

**Checklist**
- Controllers thin; validation in Form Requests; authorization via Policies.
- No N+1 queries; tenant scoping explicit; transactions around multi-writes.
- Migrations safe for the target data volume.
- Feature tests for 2xx, 401, 403 and 422 paths.
