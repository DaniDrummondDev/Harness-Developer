---
version: 1
id: database
type: skill
name: Relational databases
description: How to design schemas, write safe migrations and efficient queries for relational databases.
tags: [database, sql, persistence]
applies_to:
  stacks: [mysql, mariadb, postgresql, sqlite, sqlserver]
  capabilities: [database]
---
# Skill: Relational databases

**Use when** changing schemas, migrations, queries or data access code.

**How to do it well**
1. Model constraints in the database: primary keys, foreign keys, `NOT NULL`, unique and
   check constraints; the application is not the only guard.
2. Migrations are versioned, small and forward-only; separate schema changes from large
   data backfills; plan zero-downtime steps (add -> backfill -> switch -> remove).
3. Destructive changes (drop/rename column or table, type narrowing) follow the
   `breaking-changes` policy and need a backup/rollback plan.
4. Always use parameterized queries or the ORM's bindings.
5. Index for the actual query patterns (foreign keys, filters, sort columns); check plans
   with `EXPLAIN` for new heavy queries.
6. Wrap multi-statement invariants in transactions; choose isolation consciously.
7. Store money as integer minor units or exact decimals, timestamps in UTC.

**Verify**: migrations run up (and down when supported) on a clean database; tests cover
constraints and the new queries.

**Pitfalls**: N+1 queries; long locks from migrations on big tables; implicit type casts
defeating indexes; relying on default ordering without `ORDER BY`.
