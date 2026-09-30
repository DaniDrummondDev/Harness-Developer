---
version: 1
id: database
type: specialty
name: Databases
description: Relational data modelling, migrations, query performance and data integrity.
tags: [database, sql, persistence]
applies_to:
  stacks: [mysql, mariadb, postgresql, sqlite, sqlserver]
  capabilities: [database]
skills: [database]
---
# Specialty: Databases

**Profile.** Schema design, constraints, indexing, query plans, transactions and
isolation, zero-downtime migrations, backups and data retention.

**Checklist**
- Integrity enforced by constraints, not only by application code.
- Migrations reversible or with an explicit rollback/backup plan.
- New heavy queries checked for index use.
- Destructive changes follow the `breaking-changes` policy.
