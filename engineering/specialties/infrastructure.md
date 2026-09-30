---
version: 1
id: infrastructure
type: specialty
name: Infrastructure and containers
description: Container images, Compose/orchestration, environment configuration and runtime hardening.
tags: [infrastructure, docker, containers]
applies_to:
  stacks: [docker, docker-compose, kubernetes]
  capabilities: [containers]
skills: [docker, security]
---
# Specialty: Infrastructure and containers

**Profile.** Building and running services in containers: reproducible images, Compose
and orchestration manifests, configuration and secrets injection, health checks, resource
limits and runtime hardening.

**Checklist**
- Images pinned, minimal, non-root, free of secrets.
- Configuration and secrets injected at runtime; nothing sensitive committed.
- Health checks and resource limits declared.
- Persistent data on volumes with a backup story.
