---
version: 1
id: docker
type: skill
name: Docker
description: How to build small, reproducible, secure container images and Compose setups.
tags: [docker, containers, infrastructure]
applies_to:
  stacks: [docker, docker-compose]
  capabilities: [containers]
---
# Skill: Docker

**Use when** writing Dockerfiles, Compose files or container-related scripts.

**How to do it well**
1. Pin base images to a specific version (digest for production); prefer slim/distroless.
2. Multi-stage builds: build tools stay in the builder stage; copy only artifacts.
3. Order layers for cache efficiency (dependency manifests before source); keep a
   `.dockerignore` that excludes `.git`, `.env`, build output and secrets.
4. Run as a non-root user; drop capabilities; read-only filesystem where possible.
5. Never bake secrets into images or build args; inject at runtime (env/secret mounts).
6. One process per container; declare `HEALTHCHECK`; log to stdout/stderr.
7. Compose: named volumes for data, explicit networks, `depends_on` with health conditions,
   configuration via environment files that are not committed.

**Verify**: image builds from a clean cache; container starts and passes its health check;
image scan shows no critical vulnerabilities.

**Pitfalls**: `latest` tags; `COPY . .` leaking secrets; running migrations on every
replica start; data in container layers instead of volumes.
