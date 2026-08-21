# Greenfield Product Fixture

This is the benchmark-owned greenfield product fixture: a project and activity management application for teams.

The fixture is intentionally small enough to reproduce locally and rich enough to exercise the full SDLC:

- Next.js, React, and TypeScript web application
- PostgreSQL and Prisma data model
- Docker and GitHub Actions execution contracts
- Users, organizations, memberships, projects, activities, audit events, and background jobs

The base fixture is not itself a benchmark task. Benchmark tasks live under [`/tasks/`](../../tasks/), and each task starts from an immutable product snapshot. Do not add task-specific behavior here outside a frozen product snapshot.

## Local development

Requirements: Node 22+, pnpm 11.21.0, and Docker.

```bash
pnpm install --frozen-lockfile
pnpm prisma:generate
pnpm dev
```

The application is available at `http://localhost:3000`.

## Health and readiness

| Endpoint | Purpose | Success | Failure |
| --- | --- | --- | --- |
| `GET /health` | Process liveness for existing callers | `200` `{ "service": "greenfield-product", "status": "ok" }` | Unchanged from the original liveness contract |
| `GET /health/ready` | Deployment readiness (PostgreSQL reachable via Prisma) | `200` `{ "status": "ready", "checks": { "database": "ok" } }` | `503` `{ "status": "not_ready", "checks": { "database": "unavailable" } }` |

Readiness probes PostgreSQL through Prisma with a minimal `SELECT 1` and a short bounded timeout. Responses never include credentials, connection strings, stack traces, or raw driver errors.

### Local or Docker smoke check

```bash
# Start PostgreSQL
docker compose up -d postgres

# Install, generate the Prisma client, and start the app
export DATABASE_URL=postgresql://app:app@localhost:5432/agentic_sdlc_greenfield
pnpm install --frozen-lockfile
pnpm prisma:generate
pnpm dev
```

In another shell:

```bash
# Liveness (unchanged)
curl -sS -i http://localhost:3000/health

# Readiness while the database is up
curl -sS -i http://localhost:3000/health/ready
# or: pnpm smoke:ready

# Make the required dependency unavailable and re-check readiness
docker compose stop postgres
curl -sS -i http://localhost:3000/health/ready
```

Expect HTTP `200` with `"status":"ready"` and `"checks":{"database":"ok"}` while Postgres is healthy, and HTTP `503` with `"status":"not_ready"` and `"checks":{"database":"unavailable"}` after it is stopped or the probe times out.

## Verification

```bash
pnpm lint
pnpm test
pnpm build
```

The pinned verification container runs the same checks with Node 22.13.0:

```bash
docker build --tag agentic-sdlc-greenfield:preflight-v1.0 .
```

The benchmark controller records the exact runtime, dependency lockfile, source commit, and verification outputs for every product snapshot.
