# Pilot: expose service readiness for deployment checks

## Context

The Northstar service currently exposes a basic health response. Operations needs a deployment-facing signal that distinguishes a process that is alive from a service that is ready to accept traffic.

## Goal

Add a small, documented readiness capability to the greenfield product so an automated deployment check can determine whether the service is ready.

## Constraints

- Preserve the existing health behavior for current callers.
- Do not expose credentials, connection strings, or other secrets.
- Keep the change focused on the service contract and its verification.
- Follow the repository's existing Next.js, TypeScript, and Prisma conventions.

## Evidence available to the implementer

- The application has a health route under `src/app/health/route.ts`.
- The product includes a PostgreSQL/Prisma data model and a Docker verification path.
- The result must be usable by a deployment or local smoke check.

## Observable outcome

A reviewer should be able to identify the readiness contract, exercise it locally, and understand how it behaves when a required dependency is unavailable.

## Notes for the benchmark

This issue is intentionally incomplete. The requirements lead must record ambiguities, ask the deterministic oracle when needed, and publish the final traceability matrix as part of the run artifacts.

