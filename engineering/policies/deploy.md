---
version: 1
id: deploy
type: policy
name: Deployment safety
description: Deploys require green gates, a rollback plan and verification; production requires explicit approval.
tags: [deployment, release, process]
applies_to:
  always: true
---
# Policy: Deployment safety

Mandatory whenever the project is deployed to any shared environment. It applies to every
project so that it can never be skipped by forgetting to declare a capability.

1. Only a build that passed all required gates (tests, lint, security, migrations) is deployed.
2. Every deploy has a known rollback plan before it starts; high-risk changes prove it.
3. Production deploys require explicit human approval; they are never triggered by a
   probabilistic decision alone.
4. Migrations run before or with the deploy, are verified, and destructive migrations follow
   the `breaking-changes` policy.
5. A deploy is complete only after post-deploy verification (health, smoke tests, error rate).
   Until then it is not "released".
6. Failed verification triggers the configured rollback or escalation; it is never ignored.
